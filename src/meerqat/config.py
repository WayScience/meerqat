"""Configuration models and helpers for Meerqat."""

from __future__ import annotations

import json
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
MAX_TEMPERATURE = 2.0


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
    context_window: int


DEFAULT_MODEL_SPECS: dict[str, ModelSpec] = {
    "tinyllama": ModelSpec(
        alias="tinyllama",
        repo_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
        filename="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        context_window=2048,
    ),
    "qwen2.5-3b-instruct": ModelSpec(
        alias="qwen2.5-3b-instruct",
        repo_id="Qwen/Qwen2.5-3B-Instruct-GGUF",
        filename="qwen2.5-3b-instruct-q4_k_m.gguf",
        context_window=32768,
    ),
}


@dataclass(frozen=True)
class LLMConfig:
    """Core LLM review configuration."""

    enabled: bool = True
    provider: str = "instructor"
    model_alias: str = "tinyllama"
    repo_id: str | None = None
    filename: str | None = None
    cache_dir: Path | None = None
    offline: bool = False
    auto_start_server: bool = True
    n_ctx: int = 2048
    n_threads: int = 8
    max_tokens: int = 256
    temperature: float = 0.2
    base_url: str = "http://127.0.0.1:8000/v1"
    server_startup_timeout: float = 30.0

    def __post_init__(self) -> None:
        """Validate core LLM configuration values."""
        if self.provider not in {"instructor", "langchain"}:
            raise ValueError("llm.provider must be either 'instructor' or 'langchain'.")
        if self.model_alias not in DEFAULT_MODEL_SPECS and not (
            self.repo_id and self.filename
        ):
            raise ValueError(
                "Unknown llm.model_alias. Provide a built-in alias or both "
                "llm.repo_id and llm.filename."
            )
        if bool(self.repo_id) != bool(self.filename):
            raise ValueError(
                "Custom model configuration requires both llm.repo_id and llm.filename."
            )
        if self.n_ctx <= 0:
            raise ValueError("llm.n_ctx must be positive.")
        if self.n_threads <= 0:
            raise ValueError("llm.n_threads must be positive.")
        if self.max_tokens <= 0:
            raise ValueError("llm.max_tokens must be positive.")
        if not 0 <= self.temperature <= MAX_TEMPERATURE:
            raise ValueError(
                f"llm.temperature must be between 0 and {MAX_TEMPERATURE:g}."
            )
        if self.server_startup_timeout <= 0:
            raise ValueError("llm.server_startup_timeout must be positive.")
        if not self.base_url:
            raise ValueError("llm.base_url must not be empty.")

    def resolved_model(self) -> ModelSpec:
        """Resolve the selected or custom model specification."""
        if self.repo_id and self.filename:
            return ModelSpec(
                alias=self.model_alias,
                repo_id=self.repo_id,
                filename=self.filename,
                context_window=self.n_ctx,
            )
        return DEFAULT_MODEL_SPECS[self.model_alias]

    def resolved_n_ctx(self) -> int:
        """Clamp the requested context window to the selected model's limit."""
        return min(self.n_ctx, self.resolved_model().context_window)

    def display_dict(self) -> dict[str, Any]:
        """Return a compact, notebook-friendly summary of the LLM config."""
        return {
            "provider": self.provider,
            "model": self.model_alias,
            "base_url": self.base_url,
            "n_ctx": self.resolved_n_ctx(),
            "server_startup_timeout": self.server_startup_timeout,
        }

    def __repr__(self) -> str:
        """Render a compact string form for notebooks and logs."""
        return json.dumps(self.display_dict(), indent=2)

    __str__ = __repr__


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

    def __post_init__(self) -> None:
        """Validate top-level configuration values."""
        if (
            self.expected_images_per_plate is not None
            and self.expected_images_per_plate <= 0
        ):
            raise ValueError("expected_images_per_plate must be positive when set.")
        if self.expected_plate_count is not None and self.expected_plate_count <= 0:
            raise ValueError("expected_plate_count must be positive when set.")
        if self.assay_template not in DEFAULT_ASSAY_TEMPLATES:
            raise ValueError(
                f"Unknown assay_template '{self.assay_template}'. "
                f"Expected one of: {', '.join(sorted(DEFAULT_ASSAY_TEMPLATES))}."
            )
        if not self.metadata_plate_column:
            raise ValueError("metadata_plate_column must not be empty.")

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

    def display_dict(self) -> dict[str, Any]:
        """Return a compact, notebook-friendly summary of the config."""
        return self.llm.display_dict()

    def __repr__(self) -> str:
        """Render a compact string form for notebooks and logs."""
        return json.dumps(self.display_dict(), indent=2)

    __str__ = __repr__


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
