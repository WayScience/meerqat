"""CLI tests for Meerqat."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from meerqat.cli import main
from meerqat.models import (
    BatchValidationReport,
    ReadyCheck,
    ReadyReport,
    ValidationReport,
    ValidationSummary,
)

SYSTEM_ERROR_EXIT = 3


def _cli_env(tmp_path: Path) -> dict[str, str]:
    """Build a subprocess environment for direct CLI execution."""
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not existing else os.pathsep.join((src_path, existing))
    )
    return env


def test_cli_validate_writes_json_report(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """The validate command should emit reports and exit cleanly."""
    report_path = tmp_path / "cli-report.json"
    config_path = _write_test_config(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "meerqat.cli",
            "validate",
            str(valid_dataset),
            "--metadata",
            str(metadata_csv),
            "--config",
            str(config_path),
            "--report-json",
            str(report_path),
        ],
        capture_output=True,
        env=_cli_env(tmp_path),
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["status"] == "pass"
    assert "Meerqat Report" in result.stdout


def test_cli_validate_discovers_metadata_without_flag(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """The validate command should auto-discover nearby metadata files."""
    report_path = tmp_path / "cli-report.json"
    config_path = _write_test_config(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "meerqat.cli",
            "validate",
            str(valid_dataset),
            "--config",
            str(config_path),
            "--report-json",
            str(report_path),
        ],
        capture_output=True,
        env=_cli_env(tmp_path),
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["metadata_record_count"] == 1


def test_cli_batch_validate_returns_warning_exit_code(tmp_path: Path) -> None:
    """Batch validation should propagate warning exit codes."""
    dataset = tmp_path / "dataset"
    config_path = _write_test_config(tmp_path)
    plate = dataset / "Plate_A01"
    plate.mkdir(parents=True)
    (plate / "Index.xml").write_text(
        '<Plate PlateID="Plate_A01"></Plate>', encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "meerqat.cli",
            "batch-validate",
            str(dataset),
            "--config",
            str(config_path),
        ],
        capture_output=True,
        env=_cli_env(tmp_path),
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert '"warn_count": 1' in result.stdout


def test_cli_models_lists_presets() -> None:
    """The models command should list built-in presets."""
    env = _cli_env(Path.cwd())
    result = subprocess.run(
        [sys.executable, "-m", "meerqat.cli", "models"],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "qwen2.5-3b-instruct" in result.stdout


def test_cli_ready_renders_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ready command should render readiness results as JSON."""
    monkeypatch.setattr(
        "meerqat.cli.ready",
        lambda config, llm_config: ReadyReport(
            status="pass",
            provider=llm_config.provider,
            model=llm_config.model_alias,
            checks=(ReadyCheck(name="probe", status="pass", detail="ok"),),
        ),
    )

    exit_code = main(["ready"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["checks"][0]["name"] == "probe"


def test_cli_batch_validate_unknown_status_returns_system_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unknown batch status values should map to system-error exit code."""
    config_path = _write_test_config(tmp_path)
    dataset = tmp_path / "dataset"
    dataset.mkdir()

    monkeypatch.setattr(
        "meerqat.cli.batch_validate",
        lambda datasets, metadata_paths, config: BatchValidationReport(
            reports=(
                ValidationReport(
                    summary=ValidationSummary(
                        status="mystery",
                        dataset_id="dataset",
                        plate_count=0,
                        metadata_record_count=0,
                        image_count=0,
                        issue_counts={},
                        ready_for_pipeline=False,
                    ),
                    issues=(),
                ),
            )
        ),
    )
    monkeypatch.setattr(
        "meerqat.cli.write_reports",
        lambda report, json_path=None, markdown_path=None, html_path=None: None,
    )

    exit_code = main(["batch-validate", str(dataset), "--config", str(config_path)])

    assert exit_code == SYSTEM_ERROR_EXIT
    payload = json.loads(capsys.readouterr().out)
    assert payload["reports"][0]["summary"]["status"] == "mystery"


def _write_test_config(tmp_path: Path) -> Path:
    """Write a config that disables LLM review for deterministic CLI tests."""
    config_path = tmp_path / "test-config.yaml"
    config_path.write_text("llm:\n  enabled: false\n", encoding="utf-8")
    return config_path
