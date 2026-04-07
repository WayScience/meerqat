"""Command line interface for Meerqat."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import replace
from pathlib import Path

from meerqat.config import DEFAULT_MODEL_SPECS, LLMConfig, ValidationConfig, load_config
from meerqat.main import batch_validate, ready, validate_dataset, write_reports
from meerqat.models import BatchValidationReport, ReadyReport, ValidationReport
from meerqat.reporting import report_to_markdown


def _exit_code(status: str) -> int:
    """Map status to the documented exit code."""
    if status == "pass":
        return 0
    if status == "warn":
        return 1
    if status == "fail":
        return 2
    return 3


def _render_stdout(
    report: ValidationReport | BatchValidationReport | ReadyReport,
) -> str:
    """Render CLI output."""
    if isinstance(report, BatchValidationReport | ReadyReport):
        return json.dumps(report.to_dict(), indent=2)
    return report_to_markdown(report)


def _build_llm_config(args: argparse.Namespace, base: ValidationConfig) -> LLMConfig:
    """Build LLM config from CLI arguments."""
    existing = base.llm
    updates: dict[str, object] = {}
    for arg_name, field_name in (
        ("llm_provider", "provider"),
        ("llm_model", "model_alias"),
        ("llm_repo_id", "repo_id"),
        ("llm_filename", "filename"),
        ("llm_n_ctx", "n_ctx"),
        ("llm_threads", "n_threads"),
        ("llm_max_tokens", "max_tokens"),
        ("llm_temperature", "temperature"),
        ("llm_base_url", "base_url"),
    ):
        value = getattr(args, arg_name)
        if value is not None:
            updates[field_name] = value
    if args.llm_cache_dir is not None:
        updates["cache_dir"] = Path(args.llm_cache_dir)
    if args.offline:
        updates["offline"] = True
    return replace(existing, **updates)


def _validate_command(args: argparse.Namespace) -> int:
    """Handle single-dataset validation."""
    base_config = load_config(args.config)
    active_config = base_config.with_cli_overrides(
        dataset_id=args.dataset_id,
        fail_on_warning=args.fail_on_warning or base_config.fail_on_warning,
        llm=_build_llm_config(args, base_config),
    )
    report = validate_dataset(
        args.dataset,
        metadata_paths=args.metadata,
        config=active_config,
    )
    write_reports(
        report,
        json_path=args.report_json,
        markdown_path=args.report_markdown,
        html_path=args.report_html,
    )
    print(_render_stdout(report))
    return _exit_code(report.summary.status)


def _batch_validate_command(args: argparse.Namespace) -> int:
    """Handle multi-dataset validation."""
    base_config = load_config(args.config)
    active_config = base_config.with_cli_overrides(
        fail_on_warning=args.fail_on_warning or base_config.fail_on_warning,
        llm=_build_llm_config(args, base_config),
    )
    report = batch_validate(
        args.datasets,
        metadata_paths=args.metadata,
        config=active_config,
    )
    write_reports(report, json_path=args.report_json)
    print(_render_stdout(report))
    statuses = [entry.summary.status for entry in report.reports]
    if "fail" in statuses:
        return 2
    if "warn" in statuses:
        return 1
    if statuses and all(status == "pass" for status in statuses):
        return 0
    return 3


def _models_command() -> int:
    """List built-in model presets."""
    for alias, spec in sorted(DEFAULT_MODEL_SPECS.items()):
        print(f"{alias}\t{spec.repo_id}\t{spec.filename}")
    return 0


def _ready_command(args: argparse.Namespace) -> int:
    """Run the local-runtime readiness probe."""
    base_config = load_config(args.config)
    llm_config = _build_llm_config(args, base_config)
    report = ready(config=base_config, llm_config=llm_config)
    print(_render_stdout(report))
    return 0 if report.status == "pass" else 2


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="meerqat")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print a full traceback on CLI system errors.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument("--config")

    def add_llm_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--llm-provider",
            choices=("langchain", "instructor"),
        )
        target.add_argument("--llm-model")
        target.add_argument("--llm-repo-id")
        target.add_argument("--llm-filename")
        target.add_argument("--llm-cache-dir")
        target.add_argument(
            "--llm-base-url",
            help="OpenAI-compatible local endpoint. Defaults to http://127.0.0.1:8000/v1.",
        )
        target.add_argument("--llm-n-ctx", type=int)
        target.add_argument("--llm-threads", type=int)
        target.add_argument("--llm-max-tokens", type=int)
        target.add_argument("--llm-temperature", type=float)
        target.add_argument(
            "--offline",
            action="store_true",
            help=(
                "Require local-only model access. Defaults to disabled unless "
                "passed or set in config."
            ),
        )

    def add_validation_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument("--metadata", action="append")
        target.add_argument("--dataset-id")
        target.add_argument("--report-json")
        target.add_argument("--report-markdown")
        target.add_argument("--report-html")
        target.add_argument("--fail-on-warning", action="store_true")

    def add_batch_validation_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument("--metadata", action="append")
        target.add_argument("--report-json")
        target.add_argument("--fail-on-warning", action="store_true")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("dataset")
    add_shared_flags(validate_parser)
    add_validation_flags(validate_parser)
    add_llm_flags(validate_parser)
    validate_parser.set_defaults(handler=_validate_command)

    batch_parser = subparsers.add_parser("batch-validate")
    batch_parser.add_argument("datasets", nargs="+")
    add_shared_flags(batch_parser)
    add_batch_validation_flags(batch_parser)
    add_llm_flags(batch_parser)
    batch_parser.set_defaults(handler=_batch_validate_command)

    models_parser = subparsers.add_parser("models")
    models_parser.set_defaults(handler=lambda _args: _models_command())

    ready_parser = subparsers.add_parser("ready")
    add_shared_flags(ready_parser)
    add_llm_flags(ready_parser)
    ready_parser.set_defaults(handler=_ready_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as error:
        if getattr(args, "debug", False):
            traceback.print_exc(file=sys.stderr)
        print(f"Meerqat system error: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
