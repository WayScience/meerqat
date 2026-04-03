"""Command line interface for Meerqat."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from meerqat.config import DEFAULT_MODEL_SPECS, LLMConfig, ValidationConfig, load_config
from meerqat.main import batch_validate, validate_dataset, write_reports
from meerqat.models import BatchValidationReport, ValidationReport
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


def _render_stdout(report: ValidationReport | BatchValidationReport) -> str:
    """Render CLI output."""
    if isinstance(report, BatchValidationReport):
        return json.dumps(report.to_dict(), indent=2)
    return report_to_markdown(report)


def _build_llm_config(args: argparse.Namespace, base: ValidationConfig) -> LLMConfig:
    """Build LLM config from CLI arguments."""
    existing = base.llm
    model_alias = args.llm_model or existing.model_alias
    return LLMConfig(
        enabled=existing.enabled,
        provider=args.llm_provider or existing.provider,
        model_alias=model_alias,
        repo_id=args.llm_repo_id or existing.repo_id,
        filename=args.llm_filename or existing.filename,
        cache_dir=Path(args.llm_cache_dir)
        if args.llm_cache_dir
        else existing.cache_dir,
        offline=args.offline or existing.offline,
        n_ctx=args.llm_n_ctx or existing.n_ctx,
        n_threads=args.llm_threads or existing.n_threads,
        max_tokens=args.llm_max_tokens or existing.max_tokens,
        temperature=args.llm_temperature
        if args.llm_temperature is not None
        else existing.temperature,
        base_url=args.llm_base_url or existing.base_url,
    )


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
    return 0


def _models_command() -> int:
    """List built-in model presets."""
    for alias, spec in sorted(DEFAULT_MODEL_SPECS.items()):
        print(f"{alias}\t{spec.repo_id}\t{spec.filename}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="meerqat")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument("--metadata", action="append")
        target.add_argument("--config")
        target.add_argument("--dataset-id")
        target.add_argument("--report-json")
        target.add_argument("--report-markdown")
        target.add_argument("--report-html")
        target.add_argument("--fail-on-warning", action="store_true")
        target.add_argument(
            "--advisory",
            action="store_true",
            help="Compatibility flag. LLM review now runs by default.",
        )
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

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("dataset")
    add_common_flags(validate_parser)
    validate_parser.set_defaults(handler=_validate_command)

    batch_parser = subparsers.add_parser("batch-validate")
    batch_parser.add_argument("datasets", nargs="+")
    add_common_flags(batch_parser)
    batch_parser.set_defaults(handler=_batch_validate_command)

    models_parser = subparsers.add_parser("models")
    models_parser.set_defaults(handler=lambda _args: _models_command())

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as error:
        print(f"Meerqat system error: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
