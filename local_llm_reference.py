from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from huggingface_hub import hf_hub_download
from langchain_community.llms import LlamaCpp
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

@dataclass(frozen=True)
class ModelSpec:
    repo_id: str
    filename: str

# Example: swap to any GGUF you prefer
DEFAULT_MODEL = ModelSpec(
    repo_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
    filename="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
)

def get_cached_model_path(spec: ModelSpec, cache_dir: Path | None = None, offline: bool = False) -> str:
    """
    Download the GGUF if needed and return its local path.
    - Uses HF cache by default (recommended).
    - Set offline=True to require local-only (no network).
    """
    kwargs = {}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    if offline:
        kwargs["local_files_only"] = True  # will error if not already cached

    return hf_hub_download(repo_id=spec.repo_id, filename=spec.filename, **kwargs)

def build_llm(model_path: str) -> LlamaCpp:
    # LangChain llama.cpp wrapper (langchain-community) :contentReference[oaicite:3]{index=3}
    return LlamaCpp(
        model_path=model_path,
        n_ctx=4096,
        temperature=0.7,
        max_tokens=256,
        n_threads=8,   # tune per machine
        verbose=False,
    )

def run_loop(prompts: Iterable[str], offline_after_first: bool = True) -> list[str]:
    # First run: allow download (offline=False)
    model_path = get_cached_model_path(DEFAULT_MODEL, offline=False)

    # Later runs: optionally force “local-only”
    if offline_after_first:
        model_path = get_cached_model_path(DEFAULT_MODEL, offline=True)

    llm = build_llm(model_path)

    template = PromptTemplate.from_template(
        "You are a helpful assistant. Write concise, high-signal output.\n\n{user}\n"
    )
    chain = template | llm | StrOutputParser()

    outputs = []
    for p in prompts:
        outputs.append(chain.invoke({"user": p}))
    return outputs

if __name__ == "__main__":
    prompts = [
        "Draft a 5-bullet release note for a bioimage Python package.",
        "Write a short README section explaining how caching works.",
    ]
    for out in run_loop(prompts):
        print("----")
        print(out)