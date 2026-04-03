"""Human and machine readable reporting helpers."""

from __future__ import annotations

import html
import json
from pathlib import Path

from meerqat.models import BatchValidationReport, ValidationReport

LLM_DISCLAIMER = (
    "LLM-derived hints and findings can be wrong. Verify them against the "
    "underlying dataset before acting on them."
)


def _markdown_filetree_lines(report: ValidationReport) -> list[str]:
    """Render the filetree section for Markdown reports."""
    filetree = report.dataset.filetree_summary if report.dataset is not None else None
    if filetree is None:
        return ["", "Filetree details were not available."]
    lines = [""]
    if filetree.file_extensions:
        lines.append("- File extensions:")
        for extension, count in sorted(filetree.file_extensions.items()):
            lines.append(f"  - `{extension}`: `{count}`")
    else:
        lines.append("- File extensions: none detected")
    if filetree.empty_directories:
        lines.append("- Empty directories:")
        for directory in filetree.empty_directories:
            lines.append(f"  - `{directory}`")
    else:
        lines.append("- Empty directories: none")
    if filetree.similarly_named_directories:
        lines.append("- Similarly named directories:")
        for left, right in filetree.similarly_named_directories:
            lines.append(f"  - `{left}` <-> `{right}`")
    else:
        lines.append("- Similarly named directories: none")
    return lines


def _html_filetree_items(report: ValidationReport) -> str:
    """Render the filetree section for HTML reports."""
    filetree = report.dataset.filetree_summary if report.dataset is not None else None
    if filetree is None:
        return "<li>Filetree details were not available.</li>"
    extension_items = (
        "".join(
            f"<li><code>{html.escape(extension)}</code>: {count}</li>"
            for extension, count in sorted(filetree.file_extensions.items())
        )
        or "<li>No file extensions detected.</li>"
    )
    empty_dir_items = (
        "".join(
            f"<li>{html.escape(directory)}</li>"
            for directory in filetree.empty_directories
        )
        or "<li>No empty directories detected.</li>"
    )
    similar_dir_items = (
        "".join(
            (
                "<li>"
                f"{html.escape(left)} <strong>&lt;-&gt;</strong> {html.escape(right)}"
                "</li>"
            )
            for left, right in filetree.similarly_named_directories
        )
        or "<li>No similarly named directories detected.</li>"
    )
    return (
        "<li><strong>File extensions</strong><ul>"
        f"{extension_items}</ul></li>"
        "<li><strong>Empty directories</strong><ul>"
        f"{empty_dir_items}</ul></li>"
        "<li><strong>Similarly named directories</strong><ul>"
        f"{similar_dir_items}</ul></li>"
    )


def report_to_markdown(report: ValidationReport) -> str:
    """Render a report as Markdown."""
    lines = [
        f"# Meerqat Report: {report.summary.dataset_id}",
        "",
        f"- Status: `{report.summary.status}`",
        f"- LLM review: `{report.llm_review.status}`",
        f"- Plates: `{report.summary.plate_count}`",
        f"- Metadata records: `{report.summary.metadata_record_count}`",
        f"- Images: `{report.summary.image_count}`",
        "",
        "## Filetree",
    ]
    lines.extend(
        [
            *_markdown_filetree_lines(report),
            "",
            "## Issues",
        ]
    )
    if not report.issues:
        lines.append("")
        lines.append("No deterministic issues were detected.")
    for issue in report.issues:
        location = f" ({issue.plate_id})" if issue.plate_id else ""
        lines.append("")
        lines.append(f"- `{issue.severity}` `{issue.code}`{location}: {issue.message}")
        if issue.remediation:
            lines.append(f"  Remediation: {issue.remediation}")
    if report.llm_findings:
        lines.extend(["", "## LLM Findings"])
        lines.extend(["", f"_Note: {LLM_DISCLAIMER}_"])
        for finding in report.llm_findings:
            location = f" ({finding.plate_id})" if finding.plate_id else ""
            lines.append("")
            lines.append(
                f"- `{finding.confidence}` `{finding.category}`{location}: "
                f"{finding.summary} {finding.detail}"
            )
    if report.advisory_hints:
        lines.extend(["", "## LLM Hints"])
        lines.extend(["", f"_Note: {LLM_DISCLAIMER}_"])
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
    filetree_items = _html_filetree_items(report)
    hint_items = "".join(
        (
            "<li>"
            f"<strong>{html.escape(hint.confidence)}</strong> "
            f"{html.escape(hint.title)}: {html.escape(hint.detail)}"
            "</li>"
        )
        for hint in report.advisory_hints
    )
    finding_items = "".join(
        (
            "<li>"
            f"<strong>{html.escape(finding.confidence)}</strong> "
            f"<code>{html.escape(finding.category)}</code> "
            f"{html.escape(finding.summary)}: {html.escape(finding.detail)}"
            "</li>"
        )
        for finding in report.llm_findings
    )
    finding_section = (
        (
            f"<h2>LLM Findings</h2><p><em>{html.escape(LLM_DISCLAIMER)}</em></p>"
            f"<ul>{finding_items}</ul>"
        )
        if finding_items
        else ""
    )
    advisory_section = (
        f"<h2>LLM Hints</h2><p><em>{html.escape(LLM_DISCLAIMER)}</em></p>"
        f"<ul>{hint_items}</ul>"
        if hint_items
        else ""
    )
    return (
        "<html><head><title>Meerqat Report</title></head><body>"
        f"<h1>Meerqat Report: {html.escape(report.summary.dataset_id)}</h1>"
        f"<p>Status: <strong>{html.escape(report.summary.status)}</strong></p>"
        f"<p>LLM review: <strong>{html.escape(report.llm_review.status)}</strong></p>"
        "<ul>"
        f"<li>Plates: {report.summary.plate_count}</li>"
        f"<li>Metadata records: {report.summary.metadata_record_count}</li>"
        f"<li>Images: {report.summary.image_count}</li>"
        "</ul>"
        f"<h2>Filetree</h2><ul>{filetree_items}</ul>"
        f"<h2>Issues</h2><ul>{issue_items}</ul>"
        f"{finding_section}"
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
