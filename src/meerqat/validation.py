"""Deterministic dataset validation."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from meerqat.config import ValidationConfig
from meerqat.models import Dataset, ValidationIssue, ValidationReport, ValidationSummary
from meerqat.normalization import normalize_identifier


def _issue(  # noqa: PLR0913
    code: str,
    severity: str,
    message: str,
    *,
    plate_id: str | None = None,
    path: Path | None = None,
    remediation: str | None = None,
) -> ValidationIssue:
    """Create a structured validation issue."""
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        plate_id=plate_id,
        path=str(path) if path is not None else None,
        remediation=remediation,
    )


def _status_from_issues(
    issues: tuple[ValidationIssue, ...], fail_on_warning: bool
) -> str:
    """Collapse issue severities into a report status."""
    severities = {issue.severity for issue in issues}
    if "error" in severities:
        return "fail"
    if "warning" in severities:
        return "fail" if fail_on_warning else "warn"
    return "pass"


def validate_dataset_model(  # noqa: C901, PLR0912
    dataset: Dataset,
    config: ValidationConfig,
) -> ValidationReport:
    """Run deterministic validation rules over an ingested dataset."""
    template = config.resolved_template()
    issues: list[ValidationIssue] = []

    if not dataset.plates:
        issues.append(
            _issue(
                "dataset.no_plates",
                "error",
                "No plate directories were detected in the dataset root.",
                path=dataset.root,
                remediation=(
                    "Ensure the dataset root contains plate directories or plate files."
                ),
            )
        )

    metadata_ids = {
        normalize_identifier(record.plate_id) for record in dataset.metadata_records
    }
    plate_ids = {normalize_identifier(plate.plate_id) for plate in dataset.plates}

    if (
        config.expected_plate_count is not None
        and len(dataset.plates) != config.expected_plate_count
    ):
        issues.append(
            _issue(
                "dataset.plate_count_mismatch",
                "error",
                (
                    f"Expected {config.expected_plate_count} plates but found "
                    f"{len(dataset.plates)}."
                ),
                path=dataset.root,
            )
        )

    for plate in dataset.plates:
        if (
            template.plate_name_pattern
            and re.match(template.plate_name_pattern, plate.plate_id) is None
        ):
            issues.append(
                _issue(
                    "plate.invalid_name",
                    "warning",
                    (
                        f"Plate name '{plate.plate_id}' does not match the "
                        "configured pattern."
                    ),
                    plate_id=plate.plate_id,
                    path=plate.path,
                )
            )

        for required_file in template.required_files:
            if not (plate.path / required_file).exists():
                issues.append(
                    _issue(
                        "plate.missing_required_file",
                        "error",
                        f"Required file '{required_file}' is missing.",
                        plate_id=plate.plate_id,
                        path=plate.path / required_file,
                        remediation=(
                            "Restore the expected acquisition output before processing."
                        ),
                    )
                )

        if template.require_xml and plate.xml_path is None:
            issues.append(
                _issue(
                    "plate.missing_xml",
                    "error",
                    "No XML metadata file was found for the plate.",
                    plate_id=plate.plate_id,
                    path=plate.path,
                )
            )

        if plate.xml_path is not None:
            try:
                ElementTree.parse(plate.xml_path)
            except ElementTree.ParseError:
                issues.append(
                    _issue(
                        "plate.invalid_xml",
                        "error",
                        "The XML metadata file is not parseable.",
                        plate_id=plate.plate_id,
                        path=plate.xml_path,
                    )
                )

        if plate.xml_plate_id and normalize_identifier(
            plate.xml_plate_id
        ) != normalize_identifier(plate.plate_id):
            issues.append(
                _issue(
                    "plate.xml_folder_mismatch",
                    "error",
                    (
                        f"Folder '{plate.plate_id}' does not match XML plate "
                        "identifier "
                        f"'{plate.xml_plate_id}'."
                    ),
                    plate_id=plate.plate_id,
                    path=plate.xml_path,
                )
            )

        if not plate.image_files:
            issues.append(
                _issue(
                    "plate.no_images",
                    "warning",
                    "No supported image files were found for the plate.",
                    plate_id=plate.plate_id,
                    path=plate.path,
                )
            )

        if (
            template.expected_images_per_plate is not None
            and len(plate.image_files) != template.expected_images_per_plate
        ):
            issues.append(
                _issue(
                    "plate.image_count_mismatch",
                    "warning",
                    (
                        f"Expected {template.expected_images_per_plate} "
                        "images but found "
                        f"{len(plate.image_files)}."
                    ),
                    plate_id=plate.plate_id,
                    path=plate.path,
                )
            )

        for image_path in plate.zero_byte_images:
            issues.append(
                _issue(
                    "image.zero_byte",
                    "warning",
                    "Zero-byte image detected.",
                    plate_id=plate.plate_id,
                    path=image_path,
                    remediation="Re-export or re-copy the affected image file.",
                )
            )

        if len(plate.image_modalities) > 1:
            issues.append(
                _issue(
                    "plate.mixed_modalities",
                    "warning",
                    (
                        "Multiple image modalities were detected in a single plate: "
                        f"{', '.join(plate.image_modalities)}."
                    ),
                    plate_id=plate.plate_id,
                    path=plate.path,
                )
            )

        if metadata_ids and normalize_identifier(plate.plate_id) not in metadata_ids:
            issues.append(
                _issue(
                    "metadata.missing_for_plate",
                    "warning",
                    "No metadata record maps to this plate.",
                    plate_id=plate.plate_id,
                    path=plate.path,
                    remediation="Add a metadata row for the missing plate.",
                )
            )

    if dataset.metadata_records:
        extra_metadata = metadata_ids - plate_ids
        for record in dataset.metadata_records:
            if normalize_identifier(record.plate_id) in extra_metadata:
                issues.append(
                    _issue(
                        "metadata.orphan_record",
                        "warning",
                        (
                            f"Metadata record '{record.plate_id}' does not "
                            "map to a real plate."
                        ),
                        plate_id=record.plate_id,
                        path=Path(record.source),
                        remediation=(
                            "Remove the orphan metadata row or add the missing plate."
                        ),
                    )
                )

    issue_counts = Counter(issue.severity for issue in issues)
    status = _status_from_issues(tuple(issues), config.fail_on_warning)
    summary = ValidationSummary(
        status=status,
        dataset_id=dataset.dataset_id,
        plate_count=len(dataset.plates),
        metadata_record_count=len(dataset.metadata_records),
        image_count=sum(len(plate.image_files) for plate in dataset.plates),
        issue_counts=dict(issue_counts),
        ready_for_pipeline=status == "pass",
    )
    return ValidationReport(
        summary=summary,
        issues=tuple(issues),
        dataset=dataset,
        rule_results={
            "template": template.name,
            "expected_plate_count": config.expected_plate_count,
            "expected_images_per_plate": template.expected_images_per_plate,
        },
    )
