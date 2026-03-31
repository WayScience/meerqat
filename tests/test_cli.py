"""CLI tests for Meerqat."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_cli_validate_writes_json_report(
    valid_dataset: Path, metadata_csv: Path, tmp_path: Path
) -> None:
    """The validate command should emit reports and exit cleanly."""
    report_path = tmp_path / "cli-report.json"
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "meerqat.cli",
            "validate",
            str(valid_dataset),
            "--metadata",
            str(metadata_csv),
            "--report-json",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["status"] == "pass"
    assert "Meerqat Report" in result.stdout


def test_cli_batch_validate_returns_warning_exit_code(tmp_path: Path) -> None:
    """Batch validation should propagate warning exit codes."""
    dataset = tmp_path / "dataset"
    plate = dataset / "Plate_A01"
    plate.mkdir(parents=True)
    (plate / "Index.xml").write_text(
        '<Plate PlateID="Plate_A01"></Plate>', encoding="utf-8"
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "meerqat.cli",
            "batch-validate",
            str(dataset),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert '"warn_count": 1' in result.stdout


def test_cli_models_lists_presets() -> None:
    """The models command should list built-in presets."""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "meerqat.cli", "models"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "qwen2.5-3b-instruct" in result.stdout
