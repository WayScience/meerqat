"""Regression tests derived from real-world incident reports."""

from __future__ import annotations

from pathlib import Path

from meerqat import LLMConfig, ValidationConfig, validate_dataset


def _write_plate(
    root: Path,
    plate_name: str,
    *,
    xml_plate_id: str | None,
    image_count: int = 1,
    nested_xml: bool = False,
) -> None:
    """Create a synthetic plate directory."""
    plate_dir = root / plate_name
    image_dir = plate_dir / "Images"
    image_dir.mkdir(parents=True)

    if xml_plate_id is not None:
        xml_target = image_dir / "Index.xml" if nested_xml else plate_dir / "Index.xml"
        xml_target.write_text(
            f'<Plate PlateID="{xml_plate_id}"></Plate>',
            encoding="utf-8",
        )

    for image_number in range(image_count):
        (image_dir / f"image_{image_number:04d}.tiff").write_bytes(b"pixels")


def test_chp134_screen_level_incident_scenario(tmp_path: Path) -> None:
    """Catch plate-count, naming, XML, and metadata gaps from a reported incident."""
    dataset = tmp_path / "chp134_screen"
    metadata_path = tmp_path / "chp134_metadata.csv"

    standard_plate_ids = [
        f"BR00149{plate_number:03d}" for plate_number in range(310, 336)
    ]
    for plate_id in standard_plate_ids:
        _write_plate(dataset, plate_id, xml_plate_id=plate_id)

    _write_plate(dataset, "Assay Plate_1_5", xml_plate_id="Assay Plate_1_5")
    _write_plate(dataset, "Assay Plate_1_3", xml_plate_id=None)

    metadata_lines = ["plate_id,condition"]
    metadata_lines.extend(f"{plate_id},screen" for plate_id in standard_plate_ids[:-1])
    metadata_path.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")

    report = validate_dataset(
        dataset,
        metadata_paths=[metadata_path],
        config=ValidationConfig(
            expected_plate_count=27,
            llm=LLMConfig(enabled=False),
        ),
    )

    issue_codes = {issue.code for issue in report.issues}

    assert report.summary.status == "fail"
    assert "dataset.plate_count_mismatch" in issue_codes
    assert "plate.invalid_name" in issue_codes
    assert "plate.missing_required_file" in issue_codes
    assert "plate.missing_xml" in issue_codes
    assert "metadata.missing_for_plate" in issue_codes

    missing_metadata_plates = {
        issue.plate_id
        for issue in report.issues
        if issue.code == "metadata.missing_for_plate"
    }
    assert missing_metadata_plates >= {
        "BR00149335",
        "Assay Plate_1_5",
        "Assay Plate_1_3",
    }


def test_br00149334_partial_plate_incident_scenario(tmp_path: Path) -> None:
    """Catch nested XML mismatches and partial image-set risk."""
    dataset = tmp_path / "br00149334_dataset"
    metadata_path = tmp_path / "metadata.csv"
    metadata_path.write_text(
        "plate_id,condition\nBR00149334,screen\n",
        encoding="utf-8",
    )

    _write_plate(
        dataset,
        "BR00149334",
        xml_plate_id="Assay Plate_1_3",
        image_count=221,
        nested_xml=True,
    )

    report = validate_dataset(
        dataset,
        metadata_paths=[metadata_path],
        config=ValidationConfig(
            expected_images_per_plate=3456,
            llm=LLMConfig(enabled=False),
        ),
    )

    issue_codes = {issue.code for issue in report.issues}

    assert report.summary.status == "fail"
    assert "plate.xml_folder_mismatch" in issue_codes
    assert "plate.image_count_mismatch" in issue_codes
    assert "plate.missing_required_file" not in issue_codes
    assert "plate.missing_xml" not in issue_codes
