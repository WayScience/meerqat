"""Integration coverage for the local llama.cpp runtime."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from meerqat.config import LLMConfig
from meerqat.llm import _runtime_environment, get_cached_model_path


@pytest.mark.integration
def test_local_llama_cpp_runtime_can_generate_with_cached_model() -> None:
    """The local llama.cpp runtime should load and generate without mocks."""
    config = LLMConfig(
        provider="langchain",
        model_alias="tinyllama",
        offline=True,
        n_ctx=512,
        n_threads=4,
        max_tokens=8,
        temperature=0.0,
    )
    try:
        model_path = get_cached_model_path(config.resolved_model(), offline=True)
    except Exception as error:  # pragma: no cover - environment-dependent
        pytest.skip(f"cached TinyLlama model unavailable: {error}")

    env = _runtime_environment(config)
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from llama_cpp import Llama; "
                f"llm = Llama(model_path={model_path!r}, n_ctx=512, "
                "n_gpu_layers=0, offload_kqv=False, verbose=False); "
                "reply = llm('Reply with exactly one word.', max_tokens=8, "
                "temperature=0.0); "
                "print(reply['choices'][0]['text'].strip())"
            ),
        ],
        capture_output=True,
        check=False,
        env={**os.environ, **env},
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
