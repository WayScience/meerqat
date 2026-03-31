"""Optional advisory LLM integrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from meerqat.config import LLMConfig, ModelSpec
from meerqat.models import AdvisoryHint, ValidationReport


class AdvisoryHintModel(BaseModel):
    """Structured advisory item."""

    title: str
    detail: str
    confidence: str = "medium"


class AdvisoryPayload(BaseModel):
    """Structured advisory output."""

    hints: list[AdvisoryHintModel] = Field(default_factory=list)


def get_cached_model_path(
    spec: ModelSpec,
    *,
    cache_dir: Path | None = None,
    offline: bool = False,
) -> str:
    """Download or resolve a GGUF model path."""
    from huggingface_hub import hf_hub_download

    kwargs: dict[str, Any] = {}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    if offline:
        kwargs["local_files_only"] = True
    return hf_hub_download(repo_id=spec.repo_id, filename=spec.filename, **kwargs)


def _build_langchain_llm(model_path: str, config: LLMConfig) -> object:
    """Build a direct llama.cpp-backed LangChain model."""
    from langchain_community.llms import LlamaCpp

    return LlamaCpp(
        model_path=model_path,
        n_ctx=config.n_ctx,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        n_threads=config.n_threads,
        verbose=False,
    )


def _invoke_langchain(
    report: ValidationReport, config: LLMConfig
) -> tuple[AdvisoryHint, ...]:
    """Run advisory inference against a local GGUF model."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import PromptTemplate

    model_path = get_cached_model_path(
        config.resolved_model(),
        cache_dir=config.cache_dir,
        offline=config.offline,
    )
    llm = _build_langchain_llm(model_path, config)
    prompt = PromptTemplate.from_template(
        "You are advising on a bioimaging dataset validation report.\n"
        "Return strict JSON matching this schema:\n"
        '{"hints":[{"title":"string","detail":"string","confidence":"low|medium|high"}]}\n'
        "Focus on naming patterns, likely root causes, metadata remediation, "
        "and config suggestions.\n"
        "Keep the list short and high-signal.\n\n"
        "{report_json}\n"
    )
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke({"report_json": json.dumps(report.to_dict(), indent=2)})
    return _parse_hints(response)


def _invoke_instructor(
    report: ValidationReport, config: LLMConfig
) -> tuple[AdvisoryHint, ...]:
    """Run advisory inference through an OpenAI-compatible local server."""
    import instructor
    from openai import OpenAI

    client = instructor.from_openai(
        OpenAI(base_url=config.base_url, api_key="meerqat-local")
    )
    payload = client.chat.completions.create(
        model=config.model_alias,
        response_model=AdvisoryPayload,
        messages=[
            {
                "role": "system",
                "content": (
                    "You analyze bioimaging validation reports and return "
                    "concise, actionable hints."
                ),
            },
            {"role": "user", "content": json.dumps(report.to_dict(), indent=2)},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return tuple(
        AdvisoryHint(
            title=hint.title,
            detail=hint.detail,
            confidence=hint.confidence,
        )
        for hint in payload.hints
    )


def _parse_hints(raw: str) -> tuple[AdvisoryHint, ...]:
    """Parse JSON advisory hints."""
    try:
        payload = AdvisoryPayload.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as error:
        return (
            AdvisoryHint(
                title="LLM output could not be parsed",
                detail=f"Advisory mode returned invalid structured output: {error}",
                confidence="low",
            ),
        )
    return tuple(
        AdvisoryHint(
            title=hint.title,
            detail=hint.detail,
            confidence=hint.confidence,
        )
        for hint in payload.hints
    )


def generate_advisory_hints(
    report: ValidationReport,
    config: LLMConfig,
) -> tuple[AdvisoryHint, ...]:
    """Generate optional advisory hints."""
    if not config.enabled:
        return ()
    if config.provider == "instructor":
        return _invoke_instructor(report, config)
    return _invoke_langchain(report, config)
