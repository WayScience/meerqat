"""Unit tests covering configuration, reporting, LLM helpers, and CLI dispatch."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from meerqat import validate_dataset
from meerqat.cli import build_parser, main
from meerqat.config import LLMConfig, load_config
from meerqat.ingestion import ingest_dataset
from meerqat.llm import _parse_hints, generate_advisory_hints, get_cached_model_path
from meerqat.models import AdvisoryHint, BatchValidationReport, ValidationReport
from meerqat.reporting import report_to_html, report_to_markdown, write_json_report

SYSTEM_ERROR_EXIT = 3


def test_load_config_and_template_resolution(tmp_path: Path) -> None:
    """Config loading should hydrate nested LLM config and template overrides."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "dataset_id: run_01",
                "assay_template: generic_microscopy",
                "required_files:",
                "  - manifest.txt",
                "llm:",
                "  enabled: true",
                "  model_alias: tinyllama",
                "  offline: true",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    template = config.resolved_template()

    assert config.dataset_id == "run_01"
    assert config.llm.enabled is True
    assert config.llm.offline is True
    assert template.required_files == ("manifest.txt",)
    assert template.require_xml is False


def test_ingest_dataset_handles_root_plate_and_missing_metadata(
    valid_dataset: Path,
) -> None:
    """Ingestion should preserve discovered plate metadata."""
    dataset = ingest_dataset(valid_dataset)

    assert dataset.dataset_id == valid_dataset.name
    assert dataset.plates[0].xml_plate_id == "Plate_A01"
    assert dataset.plates[0].image_modalities == (".tiff",)


def test_reporting_helpers_cover_batch_and_advisory(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """Reporting helpers should serialize single and batch reports."""
    report = validate_dataset(valid_dataset, metadata_paths=[metadata_csv])
    advisory_report = ValidationReport(
        summary=report.summary,
        issues=report.issues,
        advisory_hints=(
            AdvisoryHint(title="Pattern", detail="Likely plate naming drift."),
        ),
        dataset=report.dataset,
        rule_results=report.rule_results,
    )
    batch = BatchValidationReport(reports=(advisory_report,))
    batch_path = tmp_path / "batch.json"

    markdown = report_to_markdown(advisory_report)
    html = report_to_html(advisory_report)
    write_json_report(batch_path, batch)

    assert "Advisory Hints" in markdown
    assert "Likely plate naming drift." in html
    assert (
        json.loads(batch_path.read_text(encoding="utf-8"))["summary"]["dataset_count"]
        == 1
    )


def test_llm_helpers_parse_and_skip_when_disabled(
    valid_dataset: Path, metadata_csv: Path
) -> None:
    """LLM helpers should parse structured JSON and no-op when disabled."""
    report = validate_dataset(valid_dataset, metadata_paths=[metadata_csv])

    hints = _parse_hints(
        (
            '{"hints":[{"title":"Config suggestion","detail":"Set '
            'expected_images_per_plate.","confidence":"high"}]}'
        )
    )
    assert hints[0].confidence == "high"
    assert generate_advisory_hints(report, LLMConfig(enabled=False)) == ()


def test_llm_helpers_return_parse_error_for_bad_json() -> None:
    """Invalid JSON should produce a low-confidence parse warning."""
    hints = _parse_hints("not json")

    assert len(hints) == 1
    assert hints[0].title == "LLM output could not be parsed"


def test_get_cached_model_path_delegates_to_huggingface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model downloads should delegate to the Hugging Face helper."""
    seen: dict[str, object] = {}

    def fake_download(**kwargs: object) -> str:
        seen.update(kwargs)
        return "/tmp/model.gguf"

    fake_module = types.SimpleNamespace(hf_hub_download=fake_download)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_module)
    path = get_cached_model_path(
        LLMConfig(model_alias="tinyllama").resolved_model(),
        cache_dir=Path("/tmp/cache"),
        offline=True,
    )

    assert path == "/tmp/model.gguf"
    assert seen["repo_id"] == "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"
    assert seen["local_files_only"] is True


def test_cli_parser_and_main_dispatch(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """Direct CLI dispatch should cover validate, batch, and models paths."""
    parser = build_parser()
    args = parser.parse_args(["models"])
    assert callable(args.handler)

    report_path = tmp_path / "report.json"
    validate_code = main(
        [
            "validate",
            str(valid_dataset),
            "--metadata",
            str(metadata_csv),
            "--report-json",
            str(report_path),
        ]
    )
    assert validate_code == 0

    warning_dataset = tmp_path / "warning_dataset"
    warning_plate = warning_dataset / "Plate_A02"
    warning_plate.mkdir(parents=True)
    (warning_plate / "Index.xml").write_text(
        '<Plate PlateID="Plate_A02"></Plate>',
        encoding="utf-8",
    )

    batch_code = main(["batch-validate", str(warning_dataset)])
    assert batch_code == 1

    models_code = main(["models"])
    assert models_code == 0


def test_cli_main_returns_system_error_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI should convert unexpected exceptions into exit code 3."""
    monkeypatch.setattr(
        "meerqat.cli._models_command",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert main(["models"]) == SYSTEM_ERROR_EXIT


def test_validate_dataset_adds_advisory_hints(
    monkeypatch: pytest.MonkeyPatch, valid_dataset: Path, metadata_csv: Path
) -> None:
    """The public API should attach advisory hints when enabled."""
    monkeypatch.setattr(
        "meerqat.main.generate_advisory_hints",
        lambda report, config: (
            AdvisoryHint(title="Hint", detail=report.summary.status),
        ),
    )

    report = validate_dataset(
        valid_dataset,
        metadata_paths=[metadata_csv],
        llm_config=LLMConfig(enabled=True),
    )

    assert report.advisory_hints[0].detail == "pass"
