"""Human and machine readable reporting helpers."""

from __future__ import annotations

import html
import json
from pathlib import Path

from meerqat.models import BatchValidationReport, ValidationReport


def report_to_markdown(report: ValidationReport) -> str:
    """Render a report as Markdown."""
    lines = [
        f"# Meerqat Report: {report.summary.dataset_id}",
        "",
        f"- Status: `{report.summary.status}`",
        f"- Plates: `{report.summary.plate_count}`",
        f"- Metadata records: `{report.summary.metadata_record_count}`",
        f"- Images: `{report.summary.image_count}`",
        "",
        "## Issues",
    ]
    if not report.issues:
        lines.append("")
        lines.append("No deterministic issues were detected.")
    for issue in report.issues:
        location = f" ({issue.plate_id})" if issue.plate_id else ""
        lines.append("")
        lines.append(f"- `{issue.severity}` `{issue.code}`{location}: {issue.message}")
        if issue.remediation:
            lines.append(f"  Remediation: {issue.remediation}")
    if report.advisory_hints:
        lines.extend(["", "## Advisory Hints"])
        for hint in report.advisory_hints:
            lines.append("")
            lines.append(f"- `{hint.confidence}` {hint.title}: {hint.detail}")
    return "\n".join(lines) + "\n"


def report_to_html(report: ValidationReport) -> str:
    """Render a report as lightweight HTML."""
    issue_items = (
        "".join(
            (
                "<li>"
                f"<strong>{html.escape(issue.severity)}</strong> "
                f"<code>{html.escape(issue.code)}</code> "
                f"{html.escape(issue.message)}"
                "</li>"
            )
            for issue in report.issues
        )
        or "<li>No deterministic issues were detected.</li>"
    )
    hint_items = "".join(
        (
            "<li>"
            f"<strong>{html.escape(hint.confidence)}</strong> "
            f"{html.escape(hint.title)}: {html.escape(hint.detail)}"
            "</li>"
        )
        for hint in report.advisory_hints
    )
    advisory_section = (
        f"<h2>Advisory Hints</h2><ul>{hint_items}</ul>" if hint_items else ""
    )
    return (
        "<html><head><title>Meerqat Report</title></head><body>"
        f"<h1>Meerqat Report: {html.escape(report.summary.dataset_id)}</h1>"
        f"<p>Status: <strong>{html.escape(report.summary.status)}</strong></p>"
        "<ul>"
        f"<li>Plates: {report.summary.plate_count}</li>"
        f"<li>Metadata records: {report.summary.metadata_record_count}</li>"
        f"<li>Images: {report.summary.image_count}</li>"
        "</ul>"
        f"<h2>Issues</h2><ul>{issue_items}</ul>"
        f"{advisory_section}"
        "</body></html>"
    )


def write_report_file(path: str | Path, contents: str) -> None:
    """Write a text report."""
    Path(path).write_text(contents, encoding="utf-8")


def write_json_report(
    path: str | Path, report: ValidationReport | BatchValidationReport
) -> None:
    """Write a JSON report."""
    Path(path).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
