"""Public API for Meerqat."""

from __future__ import annotations

from pathlib import Path

from meerqat.config import LLMConfig, ValidationConfig, load_config
from meerqat.ingestion import ingest_dataset
from meerqat.llm import generate_advisory_hints
from meerqat.models import BatchValidationReport, ValidationReport
from meerqat.reporting import (
    report_to_html,
    report_to_markdown,
    write_json_report,
    write_report_file,
)
from meerqat.validation import validate_dataset_model


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
    hints = generate_advisory_hints(report, active_config.llm)
    return ValidationReport(
        summary=report.summary,
        issues=report.issues,
        dataset=report.dataset,
        rule_results=report.rule_results,
        advisory_hints=hints,
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
    return BatchValidationReport(reports=reports)


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
