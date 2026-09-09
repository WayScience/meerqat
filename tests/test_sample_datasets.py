"""Regression tests for the checked-in sample datasets."""

from __future__ import annotations

from pathlib import Path

from meerqat import ValidationConfig, validate_dataset

DATA_ROOT = Path(__file__).parent / "data"


def test_valid_minimal_dataset(config_without_llm: ValidationConfig) -> None:
    """The valid sample dataset should pass."""
    report = validate_dataset(
        DATA_ROOT / "valid_minimal" / "dataset",
        metadata_paths=[DATA_ROOT / "valid_minimal" / "metadata.csv"],
        config=config_without_llm,
    )

    assert report.summary.status == "pass"
    assert report.issues == ()


def test_missing_index_dataset(config_without_llm: ValidationConfig) -> None:
    """A missing XML file should fail validation."""
    report = validate_dataset(
        DATA_ROOT / "missing_index" / "dataset",
        metadata_paths=[DATA_ROOT / "missing_index" / "metadata.csv"],
        config=config_without_llm,
    )

    assert report.summary.status == "fail"
    assert {issue.code for issue in report.issues} >= {
        "plate.missing_required_file",
        "plate.missing_xml",
    }


def test_xml_mismatch_dataset(config_without_llm: ValidationConfig) -> None:
    """A folder/XML mismatch should be reported."""
    report = validate_dataset(
        DATA_ROOT / "xml_mismatch" / "dataset",
        metadata_paths=[DATA_ROOT / "xml_mismatch" / "metadata.csv"],
        config=config_without_llm,
    )

    assert report.summary.status == "fail"
    assert {issue.code for issue in report.issues} >= {"plate.xml_folder_mismatch"}


def test_missing_metadata_dataset(config_without_llm: ValidationConfig) -> None:
    """A missing metadata mapping should warn."""
    report = validate_dataset(
        DATA_ROOT / "missing_metadata" / "dataset",
        metadata_paths=[DATA_ROOT / "missing_metadata" / "metadata.csv"],
        config=config_without_llm,
    )

    assert report.summary.status == "warn"
    assert {issue.code for issue in report.issues} >= {
        "metadata.missing_for_plate",
        "metadata.orphan_record",
    }


def test_mixed_modalities_dataset(config_without_llm: ValidationConfig) -> None:
    """Mixed image modalities should warn."""
    report = validate_dataset(
        DATA_ROOT / "mixed_modalities" / "dataset",
        metadata_paths=[DATA_ROOT / "mixed_modalities" / "metadata.csv"],
        config=config_without_llm,
    )

    assert report.summary.status == "warn"
    assert {issue.code for issue in report.issues} >= {"plate.mixed_modalities"}


def test_filetree_risks_dataset(config_without_llm: ValidationConfig) -> None:
    """Filetree-risk sample should surface dataset-level warnings."""
    report = validate_dataset(
        DATA_ROOT / "filetree_risks" / "dataset",
        metadata_paths=[DATA_ROOT / "filetree_risks" / "metadata.csv"],
        config=config_without_llm,
    )

    assert report.summary.status == "warn"
    assert {issue.code for issue in report.issues} >= {
        "dataset.empty_directory",
        "dataset.similar_directories",
    }
