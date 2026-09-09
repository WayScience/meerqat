"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from meerqat import LLMConfig, ValidationConfig


@pytest.fixture
def config_without_llm() -> ValidationConfig:
    """Return a validation config that skips the runtime review."""
    return ValidationConfig(llm=LLMConfig(enabled=False))


@pytest.fixture
def valid_dataset(tmp_path: Path) -> Path:
    """Create a representative valid dataset."""
    dataset = tmp_path / "dataset"
    plate = dataset / "Plate_A01"
    plate.mkdir(parents=True)
    (plate / "Index.xml").write_text(
        '<Plate PlateID="Plate_A01"></Plate>', encoding="utf-8"
    )
    (plate / "image_001.tiff").write_bytes(b"pixels")
    return dataset


@pytest.fixture
def metadata_csv(tmp_path: Path) -> Path:
    """Create a metadata CSV."""
    path = tmp_path / "metadata.csv"
    path.write_text("plate_id,condition\nPlate_A01,control\n", encoding="utf-8")
    return path
