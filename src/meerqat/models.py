"""Core domain models for Meerqat."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class LLMHint:
    """Hint produced by the LLM review layer."""

    title: str
    detail: str
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the hint to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class LLMFinding:
    """Model-derived suspected dataset issue."""

    category: str
    summary: str
    detail: str
    confidence: str = "medium"
    plate_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the finding to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class LLMReview:
    """Status and output of the model review phase."""

    status: str = "not_run"
    provider: str | None = None
    model: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the review metadata to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class ReportProvenance:
    """Report schema and environment provenance."""

    schema_version: str = REPORT_SCHEMA_VERSION
    generated_at: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    )
    package_version: str = "0+unknown"
    python_version: str = ""
    platform: str = ""
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_review_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the provenance to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class ReadyCheck:
    """A single readiness check result."""

    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the readiness check to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class ReadyReport:
    """Runtime readiness report for MeerQat."""

    status: str
    model: str
    provider: str
    checks: tuple[ReadyCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the readiness report to a dictionary."""
        statuses = [check.status for check in self.checks]
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "checks": [check.to_dict() for check in self.checks],
            "summary": {
                "check_count": len(self.checks),
                "pass_count": statuses.count("pass"),
                "warn_count": statuses.count("warn"),
                "fail_count": statuses.count("fail"),
            },
        }


@dataclass(frozen=True)
class ValidationIssue:
    """A structured validation problem."""

    code: str
    severity: str
    message: str
    plate_id: str | None = None
    path: str | None = None
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the issue to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class MetadataRecord:
    """Normalized metadata row."""

    plate_id: str
    source: str
    values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class FiletreeSummary:
    """Dataset-wide filetree inventory and heuristics."""

    file_extensions: dict[str, int] = field(default_factory=dict)
    empty_directories: tuple[str, ...] = ()
    similarly_named_directories: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the filetree summary to a dictionary."""
        return {
            "file_extensions": dict(self.file_extensions),
            "empty_directories": list(self.empty_directories),
            "similarly_named_directories": [
                list(pair) for pair in self.similarly_named_directories
            ],
        }


@dataclass(frozen=True)
class Plate:
    """Plate-level dataset inventory."""

    plate_id: str
    path: Path
    xml_path: Path | None
    xml_plate_id: str | None
    image_files: tuple[Path, ...] = ()
    zero_byte_images: tuple[Path, ...] = ()
    image_modalities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the plate to a dictionary."""
        return {
            "plate_id": self.plate_id,
            "path": str(self.path),
            "xml_path": str(self.xml_path) if self.xml_path is not None else None,
            "xml_plate_id": self.xml_plate_id,
            "image_files": [str(path) for path in self.image_files],
            "zero_byte_images": [str(path) for path in self.zero_byte_images],
            "image_modalities": list(self.image_modalities),
        }


@dataclass(frozen=True)
class Dataset:
    """Ingested dataset representation."""

    dataset_id: str
    root: Path
    plates: tuple[Plate, ...]
    metadata_records: tuple[MetadataRecord, ...] = ()
    filetree_summary: FiletreeSummary = field(default_factory=FiletreeSummary)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the dataset to a dictionary."""
        return {
            "dataset_id": self.dataset_id,
            "root": str(self.root),
            "plates": [plate.to_dict() for plate in self.plates],
            "metadata_records": [record.to_dict() for record in self.metadata_records],
            "filetree_summary": self.filetree_summary.to_dict(),
        }


@dataclass(frozen=True)
class ValidationSummary:
    """Counts and readiness summary."""

    status: str
    dataset_id: str
    plate_count: int
    metadata_record_count: int
    image_count: int
    issue_counts: dict[str, int]
    ready_for_pipeline: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize the summary to a dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    """Top-level validation result."""

    summary: ValidationSummary
    issues: tuple[ValidationIssue, ...]
    llm_hints: tuple[LLMHint, ...] = ()
    llm_findings: tuple[LLMFinding, ...] = ()
    llm_review: LLMReview = field(default_factory=LLMReview)
    dataset: Dataset | None = None
    rule_results: dict[str, Any] = field(default_factory=dict)
    provenance: ReportProvenance = field(default_factory=ReportProvenance)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a dictionary."""
        return {
            "schema_version": self.provenance.schema_version,
            "provenance": self.provenance.to_dict(),
            "summary": self.summary.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "llm_hints": [hint.to_dict() for hint in self.llm_hints],
            "llm_findings": [finding.to_dict() for finding in self.llm_findings],
            "llm_review": self.llm_review.to_dict(),
            "dataset": self.dataset.to_dict() if self.dataset is not None else None,
            "rule_results": self.rule_results,
        }


@dataclass(frozen=True)
class BatchValidationReport:
    """Aggregated batch validation results."""

    reports: tuple[ValidationReport, ...]
    provenance: ReportProvenance = field(default_factory=ReportProvenance)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the batch report to a dictionary."""
        total = len(self.reports)
        statuses = [report.summary.status for report in self.reports]
        return {
            "schema_version": self.provenance.schema_version,
            "provenance": self.provenance.to_dict(),
            "reports": [report.to_dict() for report in self.reports],
            "summary": {
                "dataset_count": total,
                "pass_count": statuses.count("pass"),
                "warn_count": statuses.count("warn"),
                "fail_count": statuses.count("fail"),
            },
        }
