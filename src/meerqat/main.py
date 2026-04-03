"""Public API for Meerqat."""

from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path

from meerqat.config import LLMConfig, ValidationConfig, load_config
from meerqat.ingestion import ingest_dataset
from meerqat.llm import generate_llm_review, run_ready_checks
from meerqat.models import (
    BatchValidationReport,
    LLMReview,
    ReadyReport,
    ReportProvenance,
    ValidationReport,
)
from meerqat.reporting import (
    report_to_html,
    report_to_markdown,
    write_json_report,
    write_report_file,
)
from meerqat.validation import validate_dataset_model


def _package_version() -> str:
    """Return the installed package version when available."""
    try:
        return importlib.metadata.version("meerqat")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


def _build_provenance(llm_review: LLMReview) -> ReportProvenance:
    """Build report provenance for a completed validation run."""
    return ReportProvenance(
        package_version=_package_version(),
        python_version=platform.python_version(),
        platform=f"{platform.system()}-{platform.machine()}",
        llm_provider=llm_review.provider,
        llm_model=llm_review.model,
        llm_review_status=llm_review.status,
    )


def validate_dataset(
    dataset_path: str | Path,
    *,
    metadata_paths: list[str | Path] | None = None,
    config_path: str | Path | None = None,
    config: ValidationConfig | None = None,
    llm_config: LLMConfig | None = None,
) -> ValidationReport:
    """Ingest and validate a single dataset."""
    active_config = config or load_config(config_path)
    if llm_config is not None:
        active_config = active_config.with_cli_overrides(llm=llm_config)
    dataset = ingest_dataset(
        dataset_path,
        metadata_paths=metadata_paths,
        config=active_config,
    )
    report = validate_dataset_model(dataset, active_config)
    llm_review = generate_llm_review(report, active_config.llm)
    llm_review_obj = LLMReview(
        status=llm_review.status,
        provider=llm_review.provider,
        model=llm_review.model,
        error=llm_review.error,
    )
    return ValidationReport(
        summary=report.summary,
        issues=report.issues,
        dataset=report.dataset,
        rule_results=report.rule_results,
        llm_hints=llm_review.hints,
        llm_findings=llm_review.findings,
        llm_review=llm_review_obj,
        provenance=_build_provenance(llm_review_obj),
    )


def batch_validate(
    dataset_paths: list[str | Path],
    *,
    metadata_paths: list[str | Path] | None = None,
    config_path: str | Path | None = None,
    config: ValidationConfig | None = None,
    llm_config: LLMConfig | None = None,
) -> BatchValidationReport:
    """Validate multiple datasets."""
    reports = tuple(
        validate_dataset(
            path,
            metadata_paths=metadata_paths,
            config_path=config_path,
            config=config,
            llm_config=llm_config,
        )
        for path in dataset_paths
    )
    representative_review = reports[0].llm_review if reports else LLMReview()
    return BatchValidationReport(
        reports=reports,
        provenance=_build_provenance(representative_review),
    )


def ready(
    *,
    config_path: str | Path | None = None,
    config: ValidationConfig | None = None,
    llm_config: LLMConfig | None = None,
) -> ReadyReport:
    """Run a local-runtime readiness probe for MeerQat."""
    active_config = config or load_config(config_path)
    active_llm = llm_config or active_config.llm
    return run_ready_checks(active_llm)


def write_reports(
    report: ValidationReport | BatchValidationReport,
    *,
    json_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
    html_path: str | Path | None = None,
) -> None:
    """Write report outputs."""
    if json_path is not None:
        write_json_report(json_path, report)
    if isinstance(report, ValidationReport):
        if markdown_path is not None:
            write_report_file(markdown_path, report_to_markdown(report))
        if html_path is not None:
            write_report_file(html_path, report_to_html(report))
