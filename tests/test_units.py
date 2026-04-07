"""Unit tests covering configuration, reporting, LLM helpers, and CLI dispatch."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

from meerqat import ready, validate_dataset
from meerqat.cli import build_parser, main
from meerqat.config import DEFAULT_MODEL_SPECS, LLMConfig, ValidationConfig, load_config
from meerqat.ingestion import ingest_dataset, load_metadata_records
from meerqat.llm import (
    HF_HUB_DISABLE_PROGRESS_ENV,
    TQDM_IPROGRESS_WARNING,
    _parse_hints,
    _resolve_instructor_model_name,
    _review_payload,
    _runtime_environment,
    generate_llm_review,
    get_cached_model_path,
)
from meerqat.models import (
    BatchValidationReport,
    LLMFinding,
    LLMHint,
    ReadyCheck,
    ReadyReport,
    ValidationReport,
)
from meerqat.reporting import report_to_html, report_to_markdown, write_json_report

SYSTEM_ERROR_EXIT = 3


def _report_without_llm(valid_dataset: Path, metadata_csv: Path) -> ValidationReport:
    """Build a validation report without invoking the local model."""
    return validate_dataset(
        valid_dataset,
        metadata_paths=[metadata_csv],
        config=ValidationConfig(llm=LLMConfig(enabled=False)),
    )


def _raise_exc(error: BaseException) -> None:
    """Raise a provided exception for monkeypatch helpers."""
    raise error


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
    assert config.llm.provider == "instructor"
    assert (
        config.llm.resolved_n_ctx() == DEFAULT_MODEL_SPECS["tinyllama"].context_window
    )
    assert template.required_files == ("manifest.txt",)
    assert template.require_xml is False


def test_resolved_template_honors_explicit_empty_required_files() -> None:
    """Explicit empty required_files overrides should be preserved."""
    config = ValidationConfig(required_files=())

    template = config.resolved_template()

    assert template.required_files == ()


def test_invalid_config_values_raise_clear_errors() -> None:
    """Config validation should reject impossible runtime values."""
    with pytest.raises(ValueError, match=r"llm\.n_ctx must be positive"):
        LLMConfig(n_ctx=0)

    with pytest.raises(ValueError, match="Unknown assay_template"):
        ValidationConfig(assay_template="not_a_template")


def test_validation_config_repr_is_notebook_friendly() -> None:
    """ValidationConfig should render a compact LLM summary by default."""
    rendered = repr(ValidationConfig())

    assert '"provider": "instructor"' in rendered
    assert '"model": "tinyllama"' in rendered
    assert '"base_url": "http://127.0.0.1:8000/v1"' in rendered


def test_ingest_dataset_handles_root_plate_and_missing_metadata(
    valid_dataset: Path,
) -> None:
    """Ingestion should preserve discovered plate metadata."""
    dataset = ingest_dataset(valid_dataset)

    assert dataset.dataset_id == valid_dataset.name
    assert dataset.plates[0].xml_plate_id == "Plate_A01"
    assert dataset.plates[0].image_modalities == (".tiff",)
    assert dataset.filetree_summary.file_extensions[".tiff"] == 1
    assert dataset.filetree_summary.file_extensions[".xml"] == 1


def test_ingest_dataset_tracks_empty_and_similar_directories(tmp_path: Path) -> None:
    """Dataset ingestion should summarize nViz-style filetree signals."""
    dataset_root = tmp_path / "dataset"
    plate = dataset_root / "Plate_A01"
    plate.mkdir(parents=True)
    (plate / "Index.xml").write_text('<Plate PlateID="Plate_A01"></Plate>')
    (plate / "image_001.tiff").write_bytes(b"pixels")
    (dataset_root / "empty_dir").mkdir()
    (dataset_root / "segment_A").mkdir()
    (dataset_root / "segment_B").mkdir()

    dataset = ingest_dataset(dataset_root)

    assert any(
        path.endswith("empty_dir")
        for path in dataset.filetree_summary.empty_directories
    )
    assert any(
        left.endswith("segment_A") and right.endswith("segment_B")
        for left, right in dataset.filetree_summary.similarly_named_directories
    )


def test_ingest_dataset_extracts_case_insensitive_nested_plate_attributes(
    tmp_path: Path,
) -> None:
    """Nested XML plate attributes should be read regardless of key casing."""
    dataset_root = tmp_path / "dataset"
    plate = dataset_root / "Plate_A01"
    plate.mkdir(parents=True)
    (plate / "Index.xml").write_text(
        '<Root><Plate Name="Plate_A01" /></Root>',
        encoding="utf-8",
    )
    (plate / "image_001.tiff").write_bytes(b"pixels")

    dataset = ingest_dataset(dataset_root)

    assert dataset.plates[0].xml_plate_id == "Plate_A01"


def test_load_metadata_records_skips_unreadable_file(
    tmp_path: Path,
) -> None:
    """Unreadable metadata files should be skipped without aborting ingestion."""
    bad_file = tmp_path / "broken.xlsx"
    bad_file.write_text("not an xlsx file", encoding="utf-8")
    good_file = tmp_path / "metadata.csv"
    good_file.write_text("plate_id,compound\nPlate_A01,DMSO\n", encoding="utf-8")

    records = load_metadata_records(
        [bad_file, good_file],
        ValidationConfig(llm=LLMConfig(enabled=False)),
    )

    assert len(records) == 1
    assert records[0].plate_id == "Plate_A01"


def test_reporting_helpers_cover_batch_and_hints(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """Reporting helpers should serialize single and batch reports."""
    report = _report_without_llm(valid_dataset, metadata_csv)
    hint_report = ValidationReport(
        summary=report.summary,
        issues=report.issues,
        llm_hints=(LLMHint(title="Pattern", detail="Likely plate naming drift."),),
        dataset=report.dataset,
        rule_results=report.rule_results,
    )
    batch = BatchValidationReport(reports=(hint_report,))
    batch_path = tmp_path / "batch.json"

    markdown = report_to_markdown(hint_report)
    html = report_to_html(hint_report)
    write_json_report(batch_path, batch)

    assert "## Filetree" in markdown
    assert "Schema version" in markdown
    assert "LLM Hints" in markdown
    assert "Likely plate naming drift." in html
    assert "File extensions" in html
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0.0"
    assert payload["provenance"]["generated_at"].endswith("Z")
    assert payload["summary"]["dataset_count"] == 1


def test_llm_helpers_parse_and_skip_when_disabled(
    valid_dataset: Path, metadata_csv: Path
) -> None:
    """LLM helpers should parse structured JSON and return disabled hints."""
    report = _report_without_llm(valid_dataset, metadata_csv)

    hints = _parse_hints(
        (
            '{"hints":[{"title":"Config suggestion","detail":"Set '
            'expected_images_per_plate.","confidence":"high"}]}'
        )
    )
    assert hints[0].confidence == "high"
    assert generate_llm_review(report, LLMConfig(enabled=False)).hints == ()


def test_llm_review_payload_includes_filetree_summary(
    valid_dataset: Path, metadata_csv: Path
) -> None:
    """The LLM payload should receive dataset-wide filetree heuristics."""
    report = _report_without_llm(valid_dataset, metadata_csv)

    payload = _review_payload(report)

    assert payload["filetree_summary"]["file_extensions"][".xml"] == 1
    assert payload["filetree_summary"]["empty_directories"] == []


def test_llm_review_returns_disabled_status_when_disabled(
    valid_dataset: Path, metadata_csv: Path
) -> None:
    """The core review result should explain when the LLM is disabled."""
    report = _report_without_llm(valid_dataset, metadata_csv)

    review = generate_llm_review(report, LLMConfig(enabled=False))

    assert review.status == "disabled"


def test_runtime_environment_builds_macos_cpu_shim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """macOS runtime setup should create a CPU-only llama.cpp library path."""
    fake_package_dir = tmp_path / "fake_llama_cpp"
    fake_lib_dir = fake_package_dir / "lib"
    fake_lib_dir.mkdir(parents=True)
    for name in (
        "libllama.dylib",
        "libggml.dylib",
        "libggml-cpu.dylib",
        "libggml-blas.dylib",
    ):
        (fake_lib_dir / name).write_text("", encoding="utf-8")

    def fake_find_spec(name: str) -> object:
        assert name == "llama_cpp"
        return types.SimpleNamespace(submodule_search_locations=[str(fake_package_dir)])

    def fake_run(*args: object, **kwargs: object) -> object:
        output_index = args[0].index("-o") + 1
        output_path = Path(args[0][output_index])
        output_path.write_text("", encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.delenv("LLAMA_CPP_LIB_PATH", raising=False)
    monkeypatch.delenv("GGML_BACKEND_PATH", raising=False)

    env = _runtime_environment(LLMConfig(cache_dir=tmp_path))

    runtime_lib_dir = Path(env["LLAMA_CPP_LIB_PATH"])
    assert env["GGML_BACKEND_PATH"] == str(runtime_lib_dir)
    assert (runtime_lib_dir / "libggml-metal.0.dylib").exists()
    assert (runtime_lib_dir / "libllama.dylib").exists()


def test_llm_helpers_return_parse_error_for_bad_json() -> None:
    """Invalid JSON should produce a low-confidence parse warning."""
    hints = _parse_hints("not json")

    assert len(hints) == 1
    assert hints[0].title == "LLM output could not be parsed"


def test_llm_prefers_instructor_and_falls_back_to_langchain(
    monkeypatch: pytest.MonkeyPatch,
    valid_dataset: Path,
    metadata_csv: Path,
) -> None:
    """Instructor should be preferred, with LangChain as fallback."""
    report = _report_without_llm(valid_dataset, metadata_csv)
    calls: list[str] = []

    def fail_instructor(report: object, config: object) -> tuple[LLMHint, ...]:
        calls.append("instructor")
        raise ModuleNotFoundError("instructor unavailable")

    def ok_langchain(report: object, config: object) -> object:
        calls.append("langchain")
        return types.SimpleNamespace(
            hints=(LLMHint(title="Fallback", detail="langchain"),),
            findings=(),
            provider="langchain",
            model="qwen2.5-3b-instruct",
            status="completed",
            error=None,
        )

    monkeypatch.setattr(
        "meerqat.llm._ensure_local_instructor_server",
        lambda config: None,
    )
    monkeypatch.setattr("meerqat.llm._invoke_instructor", fail_instructor)
    monkeypatch.setattr("meerqat.llm._invoke_langchain", ok_langchain)

    review = generate_llm_review(report, LLMConfig(enabled=True))

    assert calls == ["instructor", "langchain"]
    assert review.hints[0].title == "Fallback"


def test_llm_attempts_local_server_start_before_instructor(
    monkeypatch: pytest.MonkeyPatch,
    valid_dataset: Path,
    metadata_csv: Path,
) -> None:
    """Instructor mode should ensure the local server before querying it."""
    report = _report_without_llm(valid_dataset, metadata_csv)
    calls: list[str] = []

    monkeypatch.setattr(
        "meerqat.llm._ensure_local_instructor_server",
        lambda config: calls.append("ensure"),
    )
    monkeypatch.setattr(
        "meerqat.llm._invoke_instructor",
        lambda report, config: (
            calls.append("instructor"),
            types.SimpleNamespace(
                hints=(LLMHint(title="Hint", detail="ready"),),
                findings=(),
                provider="instructor",
                model="qwen2.5-3b-instruct",
                status="completed",
                error=None,
            ),
        )[1],
    )

    review = generate_llm_review(report, LLMConfig(enabled=True))

    assert calls == ["ensure", "instructor"]
    assert review.hints[0].detail == "ready"


def test_llm_retries_instructor_after_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    valid_dataset: Path,
    metadata_csv: Path,
) -> None:
    """Instructor mode should retry after bootstrapping a local server."""
    report = _report_without_llm(valid_dataset, metadata_csv)
    calls: list[str] = []

    monkeypatch.setattr(
        "meerqat.llm._ensure_local_instructor_server",
        lambda config: calls.append("ensure"),
    )

    def flaky_instructor(report: object, config: object) -> object:
        calls.append("instructor")
        if calls.count("instructor") == 1:
            raise RuntimeError("Connection error.")
        return types.SimpleNamespace(
            hints=(LLMHint(title="Hint", detail="retried"),),
            findings=(),
            provider="instructor",
            model="qwen2.5-3b-instruct",
            status="completed",
            error=None,
        )

    monkeypatch.setattr("meerqat.llm._invoke_instructor", flaky_instructor)

    review = generate_llm_review(report, LLMConfig(enabled=True))

    assert calls == ["ensure", "instructor", "ensure", "instructor"]
    assert review.hints[0].detail == "retried"


def test_llm_returns_failed_review_when_all_paths_fail(
    monkeypatch: pytest.MonkeyPatch,
    valid_dataset: Path,
    metadata_csv: Path,
) -> None:
    """The core review should surface a structured failure instead of crashing."""
    report = _report_without_llm(valid_dataset, metadata_csv)

    monkeypatch.setattr(
        "meerqat.llm._ensure_local_instructor_server",
        lambda config: _raise_exc(RuntimeError("startup failed")),
    )
    monkeypatch.setattr(
        "meerqat.llm._invoke_instructor",
        lambda report, config: _raise_exc(ModuleNotFoundError("instructor missing")),
    )
    monkeypatch.setattr(
        "meerqat.llm._invoke_langchain",
        lambda report, config: _raise_exc(
            ModuleNotFoundError("langchain_core missing")
        ),
    )

    review = generate_llm_review(report, LLMConfig(enabled=True))

    assert review.status == "failed"
    assert "Run `uv sync`" in (review.error or "")
    assert review.hints[0].title == "LLM review unavailable"


def test_resolve_instructor_model_name_prefers_server_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instructor mode should use the model id exposed by the server."""
    monkeypatch.setattr(
        "meerqat.llm._fetch_models_payload",
        lambda base_url: {"data": [{"id": "Qwen2.5-3B-Instruct-Q4_K_M.gguf"}]},
    )

    model_name = _resolve_instructor_model_name(
        "http://127.0.0.1:8000/v1", "qwen2.5-3b-instruct"
    )

    assert model_name == "Qwen2.5-3B-Instruct-Q4_K_M.gguf"


def test_get_cached_model_path_delegates_to_huggingface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model downloads should delegate to the Hugging Face helper."""
    seen: dict[str, object] = {}
    progress_calls: list[str | None] = []
    filter_calls: list[dict[str, object]] = []

    def fake_download(**kwargs: object) -> str:
        seen.update(kwargs)
        return "/tmp/model.gguf"

    fake_module = types.SimpleNamespace(
        hf_hub_download=fake_download,
        utils=types.SimpleNamespace(
            disable_progress_bars=lambda name=None: progress_calls.append(name)
        ),
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_module)
    monkeypatch.setitem(
        sys.modules,
        "tqdm.std",
        types.SimpleNamespace(TqdmWarning=UserWarning),
    )
    monkeypatch.delenv(HF_HUB_DISABLE_PROGRESS_ENV, raising=False)
    monkeypatch.setattr(
        "warnings.filterwarnings",
        lambda *args, **kwargs: filter_calls.append(kwargs),
    )
    path = get_cached_model_path(
        LLMConfig(model_alias="tinyllama").resolved_model(),
        cache_dir=Path("/tmp/cache"),
        offline=True,
    )

    assert path == "/tmp/model.gguf"
    assert seen["repo_id"] == "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"
    assert seen["local_files_only"] is True
    assert progress_calls == [None]
    assert os.environ[HF_HUB_DISABLE_PROGRESS_ENV] == "1"
    assert filter_calls[0]["category"] is UserWarning
    assert TQDM_IPROGRESS_WARNING in str(filter_calls[0]["message"])


def test_cli_parser_and_main_dispatch(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """Direct CLI dispatch should cover validate, batch, and models paths."""
    parser = build_parser()
    args = parser.parse_args(["models"])
    assert callable(args.handler)
    ready_args = parser.parse_args(["ready"])
    assert callable(ready_args.handler)

    report_path = tmp_path / "report.json"
    config_path = tmp_path / "cli-config.yaml"
    config_path.write_text("llm:\n  enabled: false\n", encoding="utf-8")
    validate_code = main(
        [
            "validate",
            str(valid_dataset),
            "--metadata",
            str(metadata_csv),
            "--config",
            str(config_path),
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

    batch_code = main(
        ["batch-validate", str(warning_dataset), "--config", str(config_path)]
    )
    assert batch_code == 1

    models_code = main(["models"])
    assert models_code == 0


def test_ready_api_uses_runtime_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public readiness API should delegate to the runtime probe."""
    monkeypatch.setattr(
        "meerqat.main.run_ready_checks",
        lambda llm_config: ReadyReport(
            status="pass",
            provider=llm_config.provider,
            model=llm_config.model_alias,
            checks=(ReadyCheck(name="probe", status="pass", detail="ok"),),
        ),
    )

    report = ready()

    assert report.status == "pass"
    assert report.checks[0].name == "probe"


def test_cli_main_returns_system_error_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI should convert unexpected exceptions into exit code 3."""
    monkeypatch.setattr(
        "meerqat.cli._models_command",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert main(["models"]) == SYSTEM_ERROR_EXIT


def test_validate_dataset_adds_llm_hints(
    monkeypatch: pytest.MonkeyPatch, valid_dataset: Path, metadata_csv: Path
) -> None:
    """The public API should attach LLM hints when enabled."""
    monkeypatch.setattr(
        "meerqat.main.generate_llm_review",
        lambda report, config: types.SimpleNamespace(
            hints=(LLMHint(title="Hint", detail=report.summary.status),),
            findings=(
                LLMFinding(
                    category="filetree",
                    summary="Possible hidden issue",
                    detail="A likely hidden issue.",
                ),
            ),
            provider="instructor",
            model="qwen2.5-3b-instruct",
            status="completed",
            error=None,
        ),
    )

    report = validate_dataset(valid_dataset, metadata_paths=[metadata_csv])

    assert report.llm_hints[0].detail == "pass"
    assert report.llm_findings[0].category == "filetree"
    assert report.llm_review.status == "completed"


def test_validate_dataset_fails_when_llm_review_unavailable(
    monkeypatch: pytest.MonkeyPatch, valid_dataset: Path, metadata_csv: Path
) -> None:
    """Validation should fail when the required LLM review does not complete."""
    monkeypatch.setattr(
        "meerqat.main.generate_llm_review",
        lambda report, config: types.SimpleNamespace(
            hints=(),
            findings=(),
            provider="instructor",
            model="tinyllama",
            status="failed",
            error="runtime unavailable",
        ),
    )

    report = validate_dataset(valid_dataset, metadata_paths=[metadata_csv])

    assert report.summary.status == "fail"
    assert report.summary.ready_for_pipeline is False
    assert "error" in report.summary.issue_counts
    assert any(issue.code == "llm.review_unavailable" for issue in report.issues)
