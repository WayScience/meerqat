"""Dataset scanning and parsing helpers."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import defusedxml.ElementTree as ET
import pandas as pd
from defusedxml.common import DefusedXmlException

from meerqat.config import IMAGE_EXTENSIONS, ValidationConfig
from meerqat.models import Dataset, FiletreeSummary, MetadataRecord, Plate

SIMILAR_DIRECTORY_THRESHOLD = 0.88
METADATA_EXTENSIONS = (".csv", ".xlsx", ".xls")
COMPOUND_IMAGE_EXTENSIONS = (".ome.zarr", ".ome.tif", ".ome.tiff")
LOGGER = logging.getLogger(__name__)


def _supported_image_extension(path: Path) -> str | None:
    """Return the canonical supported image extension for a path."""
    name = path.name.lower()
    for extension in COMPOUND_IMAGE_EXTENSIONS:
        if name.endswith(extension):
            return extension
    suffix = path.suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else None


def _inventory_extension(path: Path) -> str | None:
    """Return the extension label used for filetree inventory."""
    compound_extension = _supported_image_extension(path)
    if compound_extension is not None:
        return compound_extension
    if path.is_file():
        return path.suffix.lower() or None
    return None


def _looks_like_plate(path: Path) -> bool:
    """Detect whether a directory appears to contain a plate."""
    if any(path.rglob("*.xml")):
        return True
    return any(
        _supported_image_extension(candidate) is not None
        for candidate in path.rglob("*")
        if candidate.is_file() or candidate.is_dir()
    )


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
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, DefusedXmlException, OSError):
        return None
    candidates: list[str] = []
    root_attrib = {key.lower(): value for key, value in root.attrib.items()}
    for key in ("PlateID", "PlateName", "Name", "ID", "id", "name"):
        value = root_attrib.get(key.lower())
        if value:
            candidates.append(value)
    for element in root.iter():
        if element.tag.lower().endswith("plate") or "plate" in element.tag.lower():
            element_attrib = {
                key.lower(): value for key, value in element.attrib.items()
            }
            for key in ("id", "name", "plateid", "platename"):
                value = element_attrib.get(key)
                if value:
                    candidates.append(value)
            text = (element.text or "").strip()
            if text:
                candidates.append(text)
    return candidates[0] if candidates else None


def _collect_image_files(plate_dir: Path) -> tuple[Path, ...]:
    """Collect supported image assets."""
    image_files = [
        path
        for path in plate_dir.rglob("*")
        if _supported_image_extension(path) is not None
        and (path.is_file() or path.is_dir())
    ]
    return tuple(sorted(set(image_files)))


def _zero_byte_images(image_files: tuple[Path, ...]) -> tuple[Path, ...]:
    """Return any zero-byte image files."""
    return tuple(
        path for path in image_files if path.is_file() and path.stat().st_size == 0
    )


def _image_modalities(image_files: tuple[Path, ...]) -> tuple[str, ...]:
    """Infer image modality extensions."""
    modalities = {
        _supported_image_extension(path) or (path.suffix.lower() or path.name.lower())
        for path in image_files
    }
    return tuple(sorted(modalities))


def _build_filetree_summary(dataset_root: Path) -> FiletreeSummary:
    """Summarize dataset-wide filetree patterns."""
    directory_children: Counter[str] = Counter()
    directories: list[Path] = []
    file_extensions: Counter[str] = Counter()
    similarity_buckets: dict[tuple[int, str], list[Path]] = defaultdict(list)

    for path in dataset_root.rglob("*"):
        resolved = path.resolve()
        directory_children[str(resolved.parent)] += 1
        if path.is_dir():
            directories.append(resolved)
            relative = resolved.relative_to(dataset_root)
            bucket_key = (len(relative.parts), resolved.name.lower()[:4])
            similarity_buckets[bucket_key].append(resolved)
        elif path.is_file():
            extension = _inventory_extension(path)
            if extension is not None:
                file_extensions[extension] += 1

    empty_directories = tuple(
        sorted(str(path) for path in directories if directory_children[str(path)] == 0)
    )
    similar_pairs: list[tuple[str, str]] = []
    for bucket in similarity_buckets.values():
        sorted_bucket = sorted(bucket)
        for index, left in enumerate(sorted_bucket):
            left_text = str(left.relative_to(dataset_root))
            for right in sorted_bucket[index + 1 :]:
                right_text = str(right.relative_to(dataset_root))
                similarity = SequenceMatcher(None, left_text, right_text).ratio()
                if similarity >= SIMILAR_DIRECTORY_THRESHOLD:
                    similar_pairs.append((str(left), str(right)))
    return FiletreeSummary(
        file_extensions=dict(sorted(file_extensions.items())),
        empty_directories=empty_directories,
        similarly_named_directories=tuple(sorted(similar_pairs)),
    )


def load_metadata_records(
    metadata_paths: list[str | Path],
    config: ValidationConfig,
) -> tuple[MetadataRecord, ...]:
    """Load metadata from CSV or XLSX files."""
    records: list[MetadataRecord] = []
    for raw_path in metadata_paths:
        path = Path(raw_path)
        try:
            if path.suffix.lower() == ".csv":
                frame = pd.read_csv(path)
            else:
                frame = pd.read_excel(path)
        except Exception:
            LOGGER.exception("Failed to load metadata file '%s'; skipping.", path)
            continue
        frame.columns = [str(column).strip() for column in frame.columns]
        if config.metadata_plate_column not in frame.columns:
            continue
        for row in frame.to_dict(orient="records"):
            plate_value = row.get(config.metadata_plate_column)
            if plate_value is None or pd.isna(plate_value):
                continue
            normalized_plate_id = str(plate_value).strip()
            if not normalized_plate_id:
                continue
            records.append(
                MetadataRecord(
                    plate_id=normalized_plate_id,
                    source=str(path),
                    values=dict(row),
                )
            )
    return tuple(records)


def _discover_metadata_paths(dataset_root: Path) -> tuple[Path, ...]:
    """Look for likely metadata files near the dataset root."""
    preferred_stems = {"metadata", "meta", "plate_metadata"}
    local_candidates: list[Path] = []
    parent_candidates: list[Path] = []
    if dataset_root.exists():
        for extension in METADATA_EXTENSIONS:
            local_candidates.extend(
                path for path in dataset_root.glob(f"*{extension}") if path.is_file()
            )
    if dataset_root.parent.exists():
        for extension in METADATA_EXTENSIONS:
            parent_candidates.extend(
                path
                for path in dataset_root.parent.glob(f"*{extension}")
                if path.is_file() and path.stem.lower() in preferred_stems
            )
    unique_local = sorted(set(local_candidates))
    preferred_local = [
        path for path in unique_local if path.stem.lower() in preferred_stems
    ]
    remaining_local = [path for path in unique_local if path not in preferred_local]
    unique_parent = sorted(set(parent_candidates))
    parent_results = unique_parent if len(unique_parent) == 1 else []
    return tuple(preferred_local + remaining_local + parent_results)


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
        if metadata_paths is not None
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
