"""Configuration models and helpers for Meerqat."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".ome.tif",
    ".ome.tiff",
)


@dataclass(frozen=True)
class AssayTemplate:
    """Deterministic expectations for a dataset family."""

    name: str
    required_files: tuple[str, ...]
    plate_name_pattern: str | None = None
    expected_images_per_plate: int | None = None
    require_xml: bool = True


DEFAULT_ASSAY_TEMPLATES: dict[str, AssayTemplate] = {
    "phenix_harmony": AssayTemplate(
        name="phenix_harmony",
        required_files=("Index.xml",),
        plate_name_pattern=r"^[A-Za-z0-9_.-]+$",
        require_xml=True,
    ),
    "generic_microscopy": AssayTemplate(
        name="generic_microscopy",
        required_files=(),
        plate_name_pattern=r"^[A-Za-z0-9_.-]+$",
        require_xml=False,
    ),
}


@dataclass(frozen=True)
class ModelSpec:
    """A local GGUF model reference."""

    alias: str
    repo_id: str
    filename: str


DEFAULT_MODEL_SPECS: dict[str, ModelSpec] = {
    "tinyllama": ModelSpec(
        alias="tinyllama",
        repo_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
        filename="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
    ),
    "qwen2.5-3b-instruct": ModelSpec(
        alias="qwen2.5-3b-instruct",
        repo_id="Qwen/Qwen2.5-3B-Instruct-GGUF",
        filename="qwen2.5-3b-instruct-q4_k_m.gguf",
    ),
}


@dataclass(frozen=True)
class LLMConfig:
    """Optional advisory LLM configuration."""

    enabled: bool = False
    provider: str = "langchain"
    model_alias: str = "qwen2.5-3b-instruct"
    repo_id: str | None = None
    filename: str | None = None
    cache_dir: Path | None = None
    offline: bool = False
    n_ctx: int = 4096
    n_threads: int = 8
    max_tokens: int = 512
    temperature: float = 0.2
    base_url: str = "http://127.0.0.1:8000/v1"

    def resolved_model(self) -> ModelSpec:
        """Resolve the selected or custom model specification."""
        if self.repo_id and self.filename:
            return ModelSpec(
                alias=self.model_alias,
                repo_id=self.repo_id,
                filename=self.filename,
            )
        return DEFAULT_MODEL_SPECS[self.model_alias]


@dataclass(frozen=True)
class ValidationConfig:
    """Validation behavior controls."""

    dataset_id: str | None = None
    assay_template: str = "phenix_harmony"
    required_files: tuple[str, ...] = ()
    plate_name_pattern: str | None = None
    expected_images_per_plate: int | None = None
    expected_plate_count: int | None = None
    metadata_plate_column: str = "plate_id"
    fail_on_warning: bool = False
    llm: LLMConfig = field(default_factory=LLMConfig)

    def with_cli_overrides(
        self,
        *,
        dataset_id: str | None = None,
        fail_on_warning: bool | None = None,
        llm: LLMConfig | None = None,
    ) -> "ValidationConfig":
        """Return a config updated with CLI-provided overrides."""
        next_config = self
        if dataset_id is not None:
            next_config = replace(next_config, dataset_id=dataset_id)
        if fail_on_warning is not None:
            next_config = replace(next_config, fail_on_warning=fail_on_warning)
        if llm is not None:
            next_config = replace(next_config, llm=llm)
        return next_config

    def resolved_template(self) -> AssayTemplate:
        """Merge built-in templates with explicit overrides."""
        template = DEFAULT_ASSAY_TEMPLATES[self.assay_template]
        required_files = self.required_files or template.required_files
        plate_name_pattern = self.plate_name_pattern or template.plate_name_pattern
        expected_images_per_plate = (
            self.expected_images_per_plate or template.expected_images_per_plate
        )
        return AssayTemplate(
            name=template.name,
            required_files=required_files,
            plate_name_pattern=plate_name_pattern,
            expected_images_per_plate=expected_images_per_plate,
            require_xml=template.require_xml,
        )


def _normalize_llm_config(raw: dict[str, Any]) -> LLMConfig:
    """Build an LLM config from a mapping."""
    payload = dict(raw)
    cache_dir = payload.get("cache_dir")
    if cache_dir is not None:
        payload["cache_dir"] = Path(cache_dir)
    return LLMConfig(**payload)


def load_config(path: str | Path | None) -> ValidationConfig:
    """Load a validation config from YAML."""
    if path is None:
        return ValidationConfig()

    with Path(path).open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}

    payload = dict(raw)
    if "required_files" in payload and payload["required_files"] is not None:
        payload["required_files"] = tuple(payload["required_files"])
    if "llm" in payload:
        payload["llm"] = _normalize_llm_config(payload["llm"] or {})
    return ValidationConfig(**payload)
