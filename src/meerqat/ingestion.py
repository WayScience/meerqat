"""Dataset scanning and parsing helpers."""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd

from meerqat.config import IMAGE_EXTENSIONS, ValidationConfig
from meerqat.models import Dataset, FiletreeSummary, MetadataRecord, Plate

SIMILAR_DIRECTORY_THRESHOLD = 0.88
METADATA_EXTENSIONS = (".csv", ".xlsx", ".xls")


def _looks_like_plate(path: Path) -> bool:
    """Detect whether a directory appears to contain a plate."""
    if any(path.rglob("*.xml")):
        return True
    for extension in IMAGE_EXTENSIONS:
        if extension.startswith(".ome."):
            if any(path.rglob(f"*{extension}")):
                return True
            continue
        if any(path.rglob(f"*{extension}")):
            return True
    return any(path.rglob("*.ome.zarr"))


def _discover_plate_dirs(dataset_root: Path) -> list[Path]:
    """Find candidate plate directories."""
    children = sorted(path for path in dataset_root.iterdir() if path.is_dir())
    plates = [path for path in children if _looks_like_plate(path)]
    if plates:
        return plates
    if _looks_like_plate(dataset_root):
        return [dataset_root]
    return children


def _find_xml_path(plate_dir: Path) -> Path | None:
    """Pick the most relevant XML path for a plate."""
    preferred = plate_dir / "Index.xml"
    if preferred.exists():
        return preferred
    nested_preferred = sorted(plate_dir.rglob("Index.xml"))
    if nested_preferred:
        return nested_preferred[0]
    xml_files = sorted(plate_dir.rglob("*.xml"))
    return xml_files[0] if xml_files else None


def _extract_xml_plate_id(xml_path: Path | None) -> str | None:
    """Extract a plate identifier from XML content when possible."""
    if xml_path is None:
        return None
    root = ElementTree.parse(xml_path).getroot()
    candidates: list[str] = []
    for key in ("PlateID", "PlateName", "Name", "ID", "id", "name"):
        value = root.attrib.get(key)
        if value:
            candidates.append(value)
    for element in root.iter():
        if element.tag.lower().endswith("plate") or "plate" in element.tag.lower():
            for key in ("id", "name", "plateid", "platename"):
                value = element.attrib.get(key)
                if value:
                    candidates.append(value)
            text = (element.text or "").strip()
            if text:
                candidates.append(text)
    return candidates[0] if candidates else None


def _collect_image_files(plate_dir: Path) -> tuple[Path, ...]:
    """Collect supported image assets."""
    image_files: list[Path] = []
    for extension in IMAGE_EXTENSIONS:
        image_files.extend(
            path for path in plate_dir.rglob(f"*{extension}") if path.is_file()
        )
    image_files.extend(path for path in plate_dir.glob("*.ome.zarr") if path.is_dir())
    return tuple(sorted(set(image_files)))


def _zero_byte_images(image_files: tuple[Path, ...]) -> tuple[Path, ...]:
    """Return any zero-byte image files."""
    return tuple(
        path for path in image_files if path.is_file() and path.stat().st_size == 0
    )


def _image_modalities(image_files: tuple[Path, ...]) -> tuple[str, ...]:
    """Infer image modality extensions."""
    modalities = {
        ".ome.zarr"
        if path.name.endswith(".ome.zarr")
        else "".join(path.suffixes[-2:]) or path.suffix
        for path in image_files
    }
    return tuple(sorted(modalities))


def _build_filetree_summary(dataset_root: Path) -> FiletreeSummary:
    """Summarize dataset-wide filetree patterns."""
    paths = tuple(dataset_root.rglob("*"))
    directory_children = Counter(str(path.parent.resolve()) for path in paths)
    empty_directories = tuple(
        sorted(
            str(path.resolve())
            for path in paths
            if path.is_dir() and directory_children[str(path.resolve())] == 0
        )
    )
    file_extensions = dict(
        sorted(
            Counter(
                path.suffix for path in paths if path.is_file() and path.suffix
            ).items()
        )
    )
    directories = tuple(sorted(path.resolve() for path in paths if path.is_dir()))
    similar_pairs: list[tuple[str, str]] = []
    for index, left in enumerate(directories):
        left_text = str(left.relative_to(dataset_root))
        for right in directories[index + 1 :]:
            right_text = str(right.relative_to(dataset_root))
            similarity = SequenceMatcher(None, left_text, right_text).ratio()
            if similarity >= SIMILAR_DIRECTORY_THRESHOLD:
                similar_pairs.append((str(left), str(right)))
    return FiletreeSummary(
        file_extensions=file_extensions,
        empty_directories=empty_directories,
        similarly_named_directories=tuple(similar_pairs),
    )


def load_metadata_records(
    metadata_paths: list[str | Path],
    config: ValidationConfig,
) -> tuple[MetadataRecord, ...]:
    """Load metadata from CSV or XLSX files."""
    records: list[MetadataRecord] = []
    for raw_path in metadata_paths:
        path = Path(raw_path)
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
        else:
            frame = pd.read_excel(path)
        frame.columns = [str(column).strip() for column in frame.columns]
        if config.metadata_plate_column not in frame.columns:
            continue
        for row in frame.to_dict(orient="records"):
            plate_value = row.get(config.metadata_plate_column)
            if plate_value is None:
                continue
            records.append(
                MetadataRecord(
                    plate_id=str(plate_value),
                    source=str(path),
                    values=dict(row),
                )
            )
    return tuple(records)


def _discover_metadata_paths(dataset_root: Path) -> tuple[Path, ...]:
    """Look for likely metadata files near the dataset root."""
    search_roots = (dataset_root, dataset_root.parent)
    candidates: list[Path] = []
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for extension in METADATA_EXTENSIONS:
            candidates.extend(
                path for path in search_root.glob(f"*{extension}") if path.is_file()
            )
    unique_candidates = sorted(set(candidates))
    preferred = [
        path
        for path in unique_candidates
        if path.stem.lower() in {"metadata", "meta", "plate_metadata"}
    ]
    remainder = [path for path in unique_candidates if path not in preferred]
    return tuple(preferred + remainder)


def ingest_dataset(
    dataset_path: str | Path,
    *,
    metadata_paths: list[str | Path] | None = None,
    config: ValidationConfig | None = None,
) -> Dataset:
    """Scan a dataset into a normalized in-memory model."""
    active_config = config or ValidationConfig()
    root = Path(dataset_path).resolve()
    plate_dirs = _discover_plate_dirs(root)
    plates: list[Plate] = []
    for plate_dir in plate_dirs:
        xml_path = _find_xml_path(plate_dir)
        xml_plate_id = _extract_xml_plate_id(xml_path) if xml_path is not None else None
        image_files = _collect_image_files(plate_dir)
        plates.append(
            Plate(
                plate_id=plate_dir.name,
                path=plate_dir,
                xml_path=xml_path,
                xml_plate_id=xml_plate_id,
                image_files=image_files,
                zero_byte_images=_zero_byte_images(image_files),
                image_modalities=_image_modalities(image_files),
            )
        )
    resolved_metadata_paths = (
        [Path(path) for path in metadata_paths]
        if metadata_paths
        else list(_discover_metadata_paths(root))
    )
    metadata_records = load_metadata_records(resolved_metadata_paths, active_config)
    dataset_id = active_config.dataset_id or root.name
    return Dataset(
        dataset_id=dataset_id,
        root=root,
        plates=tuple(plates),
        metadata_records=metadata_records,
        filetree_summary=_build_filetree_summary(root),
    )
