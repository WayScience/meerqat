"""API tests for Meerqat."""

from __future__ import annotations

import json
from pathlib import Path

from meerqat import (
    DEFAULT_MODEL_SPECS,
    LLMConfig,
    ValidationConfig,
    batch_validate,
    validate_dataset,
)
from meerqat.main import write_reports

EXPECTED_BATCH_REPORTS = 2


def _without_llm() -> ValidationConfig:
    """Return a validation config that skips the runtime review."""
    return ValidationConfig(llm=LLMConfig(enabled=False))


def test_validate_dataset_passes(valid_dataset: Path, metadata_csv: Path) -> None:
    """A complete dataset should pass deterministic validation."""
    report = validate_dataset(
        valid_dataset,
        metadata_paths=[metadata_csv],
        config=_without_llm(),
    )

    assert report.summary.status == "pass"
    assert report.summary.plate_count == 1
    assert report.summary.image_count == 1
    assert report.issues == ()
    assert report.provenance.schema_version == "1.0.0"
    assert report.provenance.llm_review_status == "disabled"


def test_validate_dataset_discovers_nearby_metadata(
    valid_dataset: Path, metadata_csv: Path
) -> None:
    """Validation should auto-discover metadata when none is provided."""
    report = validate_dataset(valid_dataset)

    assert report.summary.status == "pass"
    assert report.summary.metadata_record_count == 1


def test_validate_dataset_detects_multiple_issues(
    tmp_path: Path, metadata_csv: Path
) -> None:
    """Meerqat should detect structural, metadata, and image issues."""
    dataset = tmp_path / "broken_dataset"
    plate = dataset / "Plate-B02"
    plate.mkdir(parents=True)
    (plate / "Index.xml").write_text(
        '<Plate PlateID="Plate_X99"></Plate>', encoding="utf-8"
    )
    (plate / "image_001.tiff").write_bytes(b"")
    config = ValidationConfig(
        expected_images_per_plate=2,
        llm=LLMConfig(enabled=False),
    )

    report = validate_dataset(dataset, metadata_paths=[metadata_csv], config=config)

    assert report.summary.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "plate.xml_folder_mismatch" in codes
    assert "plate.image_count_mismatch" in codes
    assert "image.zero_byte" in codes
    assert "metadata.missing_for_plate" in codes
    assert "metadata.orphan_record" in codes


def test_validate_dataset_detects_filetree_risks(tmp_path: Path) -> None:
    """Meerqat should surface empty and similarly named directories."""
    dataset = tmp_path / "dataset"
    plate = dataset / "Plate_A01"
    plate.mkdir(parents=True)
    (plate / "Index.xml").write_text(
        '<Plate PlateID="Plate_A01"></Plate>',
        encoding="utf-8",
    )
    (plate / "image_001.tiff").write_bytes(b"pixels")
    (dataset / "empty_dir").mkdir()
    (dataset / "segment_A").mkdir()
    (dataset / "segment_B").mkdir()

    report = validate_dataset(
        dataset,
        config=ValidationConfig(llm=LLMConfig(enabled=False)),
    )

    codes = {issue.code for issue in report.issues}
    assert "dataset.empty_directory" in codes
    assert "dataset.similar_directories" in codes
    assert report.rule_results["file_extensions"][".xml"] == 1
    assert any(
        path.endswith("empty_dir") for path in report.rule_results["empty_directories"]
    )


def test_write_reports_outputs_all_formats(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """All report writers should emit files."""
    report = validate_dataset(
        valid_dataset,
        metadata_paths=[metadata_csv],
        config=_without_llm(),
    )
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    html_path = tmp_path / "report.html"

    write_reports(
        report,
        json_path=json_path,
        markdown_path=markdown_path,
        html_path=html_path,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0.0"
    assert payload["provenance"]["package_version"]
    assert payload["summary"]["status"] == "pass"
    assert "# Meerqat Report" in markdown_path.read_text(encoding="utf-8")
    assert "<html>" in html_path.read_text(encoding="utf-8")


def test_batch_validate_aggregates_reports(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """Batch validation should preserve per-dataset results."""
    second_dataset = tmp_path / "second_dataset"
    second_plate = second_dataset / "Plate_A02"
    second_plate.mkdir(parents=True)
    (second_plate / "Index.xml").write_text(
        '<Plate PlateID="Plate_A02"></Plate>',
        encoding="utf-8",
    )

    batch = batch_validate(
        [valid_dataset, second_dataset],
        metadata_paths=[metadata_csv],
        config=_without_llm(),
    )

    assert len(batch.reports) == EXPECTED_BATCH_REPORTS
    assert {report.summary.status for report in batch.reports} == {"pass", "warn"}
    assert batch.provenance.schema_version == "1.0.0"


def test_llm_config_resolves_preset_and_custom_model() -> None:
    """Model selection should be configurable."""
    assert DEFAULT_MODEL_SPECS["qwen2.5-3b-instruct"].repo_id

    custom = LLMConfig(
        enabled=True,
        model_alias="custom",
        repo_id="repo/example",
        filename="model.gguf",
    )

    resolved = custom.resolved_model()
    assert resolved.repo_id == "repo/example"
    assert resolved.filename == "model.gguf"
