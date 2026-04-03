"""Core LLM review integrations."""

from __future__ import annotations

import atexit
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from pydantic import BaseModel, Field, ValidationError

from meerqat.config import LLMConfig, ModelSpec
from meerqat.models import (
    LLMFinding,
    LLMHint,
    ReadyCheck,
    ReadyReport,
    ValidationReport,
)

_SERVER_PROCESSES: dict[str, subprocess.Popen[str]] = {}
HTTP_SERVER_ERROR_STATUS = 500
HTTP_SCHEMES = {"http", "https"}
MACOS_CPU_RUNTIME_DIRNAME = "llama_cpp_macos_cpu"
SERVER_RUNTIME_MODULES = (
    "uvicorn",
    "fastapi",
    "sse_starlette",
    "starlette_context",
    "pydantic_settings",
)
HF_HUB_DISABLE_PROGRESS_ENV = "HF_HUB_DISABLE_PROGRESS_BARS"
TQDM_IPROGRESS_WARNING = "IProgress not found"


class HintModel(BaseModel):
    """Structured hint item."""

    title: str
    detail: str
    confidence: str = "medium"


class FindingModel(BaseModel):
    """Structured suspected issue returned by the model."""

    category: str
    summary: str
    detail: str
    confidence: str = "medium"
    plate_id: str | None = None


class AdvisoryPayload(BaseModel):
    """Structured LLM review output."""

    hints: list[HintModel] = Field(default_factory=list)
    findings: list[FindingModel] = Field(default_factory=list)


class LLMReviewResult(BaseModel):
    """Structured result returned to the main validation flow."""

    hints: tuple[LLMHint, ...] = ()
    findings: tuple[LLMFinding, ...] = ()
    provider: str | None = None
    model: str | None = None
    status: str = "not_run"
    error: str | None = None


def _review_payload(report: ValidationReport) -> dict[str, Any]:
    """Build a compact payload for model review."""
    dataset = report.dataset
    plates: list[dict[str, Any]] = []
    metadata_plate_ids: set[str] = set()
    if dataset is not None:
        metadata_plate_ids = {
            record.plate_id for record in dataset.metadata_records if record.plate_id
        }
        plates = [
            {
                "plate_id": plate.plate_id,
                "xml_plate_id": plate.xml_plate_id,
                "has_xml": plate.xml_path is not None,
                "image_count": len(plate.image_files),
                "zero_byte_image_count": len(plate.zero_byte_images),
                "image_modalities": list(plate.image_modalities),
                "has_metadata": plate.plate_id in metadata_plate_ids,
            }
            for plate in dataset.plates
        ]
    return {
        "summary": report.summary.to_dict(),
        "issues": [issue.to_dict() for issue in report.issues],
        "filetree_summary": dataset.filetree_summary.to_dict()
        if dataset is not None
        else {
            "file_extensions": {},
            "empty_directories": [],
            "similarly_named_directories": [],
        },
        "plates": plates,
        "metadata_plate_ids": sorted(metadata_plate_ids),
        "rule_result_keys": sorted(report.rule_results.keys()),
    }


def _default_runtime_dir(config: LLMConfig) -> Path:
    """Return the directory used for local runtime helper files."""
    if config.cache_dir is not None:
        return config.cache_dir / MACOS_CPU_RUNTIME_DIRNAME
    return Path.home() / ".cache" / "meerqat" / MACOS_CPU_RUNTIME_DIRNAME


def _llama_cpp_lib_dir() -> Path:
    """Locate the installed llama_cpp shared-library directory."""
    spec = importlib.util.find_spec("llama_cpp")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError(
            "The installed llama-cpp-python package could not be located."
        )
    package_dir = Path(next(iter(spec.submodule_search_locations)))
    lib_dir = package_dir / "lib"
    if not lib_dir.exists():
        raise RuntimeError(f"llama_cpp library directory not found at {lib_dir}.")
    return lib_dir


def _write_macos_metal_stub(runtime_lib_dir: Path) -> None:
    """Compile a minimal Metal backend shim for CPU-only macOS execution."""
    source_path = runtime_lib_dir / "metal_stub.c"
    source_path.write_text(
        "void *ggml_backend_metal_reg(void) { return 0; }\n",
        encoding="utf-8",
    )
    output_path = runtime_lib_dir / "libggml-metal.0.dylib"
    compiler = shutil.which("cc") or shutil.which("clang")
    if compiler is None:
        raise RuntimeError(
            "Failed to build the macOS CPU-only llama.cpp runtime shim because "
            "no C compiler was found. Install the macOS command line tools and "
            "try again."
        )
    try:
        subprocess.run(
            [
                compiler,
                "-dynamiclib",
                "-o",
                str(output_path),
                str(source_path),
                "-install_name",
                "@rpath/libggml-metal.0.dylib",
            ],
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        stderr = getattr(error, "stderr", "") or ""
        stdout = getattr(error, "stdout", "") or ""
        details = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
        raise RuntimeError(
            "Failed to build the macOS CPU-only llama.cpp runtime shim with "
            f"compiler '{compiler}'. Install the macOS command line tools and "
            f"try again. {details or error}"
        ) from error
    for alias in ("libggml-metal.dylib", "libggml-metal.0.9.8.dylib"):
        alias_path = runtime_lib_dir / alias
        if alias_path.exists() or alias_path.is_symlink():
            alias_path.unlink()
        alias_path.symlink_to(output_path.name)


def _prepare_macos_cpu_runtime(config: LLMConfig) -> Path:
    """Create a CPU-only llama.cpp runtime directory for macOS."""

    def build_runtime(runtime_root: Path) -> Path:
        runtime_lib_dir = runtime_root / "lib"
        runtime_lib_dir.mkdir(parents=True, exist_ok=True)
        source_lib_dir = _llama_cpp_lib_dir()
        for source_path in source_lib_dir.glob("*.dylib"):
            if source_path.name.startswith("libggml-metal"):
                continue
            target_path = runtime_lib_dir / source_path.name
            if target_path.exists() or target_path.is_symlink():
                target_path.unlink()
            shutil.copy2(source_path, target_path)
        if not (runtime_lib_dir / "libggml-metal.0.dylib").exists():
            _write_macos_metal_stub(runtime_lib_dir)
        return runtime_lib_dir

    try:
        return build_runtime(_default_runtime_dir(config))
    except PermissionError:
        temp_root = (
            Path(
                tempfile.mkdtemp(
                    prefix="meerqat-",
                    dir=tempfile.gettempdir(),
                )
            )
            / MACOS_CPU_RUNTIME_DIRNAME
        )
        os.chmod(temp_root.parent, 0o700)
        return build_runtime(temp_root)


def _runtime_environment(config: LLMConfig) -> dict[str, str]:
    """Build environment variables for llama.cpp-backed execution."""
    env = os.environ.copy()
    if env.get("LLAMA_CPP_LIB_PATH"):
        return env
    if sys.platform != "darwin":
        return env
    runtime_lib_dir = _prepare_macos_cpu_runtime(config)
    env["LLAMA_CPP_LIB_PATH"] = str(runtime_lib_dir)
    env.setdefault("GGML_BACKEND_PATH", str(runtime_lib_dir))
    return env


def _activate_runtime_environment(config: LLMConfig) -> dict[str, str]:
    """Apply runtime environment variables for the current process."""
    env = _runtime_environment(config)
    for key in ("LLAMA_CPP_LIB_PATH", "GGML_BACKEND_PATH"):
        value = env.get(key)
        if value:
            os.environ[key] = value
    return env


def _models_url(base_url: str) -> str:
    """Build the OpenAI-compatible models endpoint."""
    parsed = urllib_parse.urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if not path.endswith("/models"):
        path = f"{path}/models"
    return urllib_parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
    )


def _validated_models_url(base_url: str) -> str:
    """Return a validated models URL for HTTP(S) local or remote endpoints."""
    models_url = _models_url(base_url)
    scheme = urllib_parse.urlsplit(models_url).scheme.lower()
    if scheme not in HTTP_SCHEMES:
        raise ValueError(
            f"Unsupported LLM endpoint scheme '{scheme}'. Use http or https."
        )
    return models_url


def _is_local_base_url(base_url: str) -> bool:
    """Return whether the configured endpoint points at localhost."""
    hostname = (urllib_parse.urlsplit(base_url).hostname or "").strip("[]").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _server_is_ready(base_url: str) -> bool:
    """Check whether an OpenAI-compatible endpoint is reachable."""
    try:
        with urllib_request.urlopen(
            _validated_models_url(base_url),
            timeout=1,
        ) as response:
            return response.status < HTTP_SERVER_ERROR_STATUS
    except (urllib_error.URLError, TimeoutError, ValueError):
        return False


def _fetch_models_payload(base_url: str) -> dict[str, Any]:
    """Fetch the OpenAI-compatible models payload."""
    with urllib_request.urlopen(_validated_models_url(base_url), timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve_instructor_model_name(base_url: str, requested_model: str) -> str:
    """Resolve the model id exposed by the local OpenAI-compatible server."""
    try:
        payload = _fetch_models_payload(base_url)
    except (
        json.JSONDecodeError,
        urllib_error.URLError,
        TimeoutError,
        ValueError,
    ):
        return requested_model

    raw_models = payload.get("data", [])
    model_ids = [
        str(entry.get("id"))
        for entry in raw_models
        if isinstance(entry, dict) and entry.get("id")
    ]
    if not model_ids:
        return requested_model
    if requested_model in model_ids:
        return requested_model

    normalized_requested = requested_model.lower().replace("_", "-")
    for model_id in model_ids:
        normalized_id = model_id.lower().replace("_", "-")
        if (
            normalized_requested in normalized_id
            or normalized_id in normalized_requested
        ):
            return model_id
        model_name = Path(model_id).stem.lower().replace("_", "-")
        if normalized_requested in model_name or model_name in normalized_requested:
            return model_id
    return model_ids[0]


def _cleanup_server_processes() -> None:
    """Terminate any helper server processes started by MeerQat."""
    for process in _SERVER_PROCESSES.values():
        if process.poll() is None:
            process.terminate()


atexit.register(_cleanup_server_processes)


def _wait_for_server(
    base_url: str,
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
) -> None:
    """Wait for a spawned local server to become reachable."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _server_is_ready(base_url):
            return
        if process.poll() is not None:
            raise RuntimeError("llama.cpp server exited before becoming ready.")
        time.sleep(0.5)
    raise RuntimeError(
        "Timed out waiting for the local llama.cpp server after "
        f"{timeout_seconds:g} seconds."
    )


def _ensure_server_runtime_dependencies() -> None:
    """Check that the local Instructor server runtime is installed."""
    missing = []
    for module_name in SERVER_RUNTIME_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            missing.append(module_name)
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(
            "Local llama.cpp server dependencies are missing: "
            f"{names}. Run `uv sync` to install the full MeerQat package."
        )


def _ensure_local_instructor_server(config: LLMConfig) -> None:
    """Start a local llama.cpp server if the configured local endpoint is down."""
    if not config.auto_start_server or not _is_local_base_url(config.base_url):
        return
    if _server_is_ready(config.base_url):
        return
    _ensure_server_runtime_dependencies()

    existing_process = _SERVER_PROCESSES.get(config.base_url)
    if existing_process is not None and existing_process.poll() is None:
        _wait_for_server(
            config.base_url,
            existing_process,
            timeout_seconds=config.server_startup_timeout,
        )
        return

    model_path = get_cached_model_path(
        config.resolved_model(),
        cache_dir=config.cache_dir,
        offline=config.offline,
    )
    parsed = urllib_parse.urlsplit(config.base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    runtime_env = _runtime_environment(config)
    command = [
        sys.executable,
        "-m",
        "llama_cpp.server",
        "--model",
        model_path,
        "--host",
        host,
        "--port",
        str(port),
        "--n_ctx",
        str(config.resolved_n_ctx()),
    ]
    process = subprocess.Popen(
        command,
        env=runtime_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    _SERVER_PROCESSES[config.base_url] = process
    _wait_for_server(
        config.base_url,
        process,
        timeout_seconds=config.server_startup_timeout,
    )


def get_cached_model_path(
    spec: ModelSpec,
    *,
    cache_dir: Path | None = None,
    offline: bool = False,
) -> str:
    """Download or resolve a GGUF model path."""
    os.environ.setdefault(HF_HUB_DISABLE_PROGRESS_ENV, "1")
    tqdm_std = importlib.import_module("tqdm.std")
    warnings.filterwarnings(
        "ignore",
        message=f".*{TQDM_IPROGRESS_WARNING}.*",
        category=tqdm_std.TqdmWarning,
    )
    huggingface_hub = importlib.import_module("huggingface_hub")
    utils = getattr(huggingface_hub, "utils", None)
    if utils is not None and hasattr(utils, "disable_progress_bars"):
        utils.disable_progress_bars()
    hf_hub_download = huggingface_hub.hf_hub_download
    kwargs: dict[str, Any] = {}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    if offline:
        kwargs["local_files_only"] = True
    return hf_hub_download(repo_id=spec.repo_id, filename=spec.filename, **kwargs)


def _build_langchain_llm(model_path: str, config: LLMConfig) -> object:
    """Build a direct llama.cpp-backed LangChain model."""
    _activate_runtime_environment(config)
    LlamaCpp = importlib.import_module("langchain_community.llms").LlamaCpp
    return LlamaCpp(
        model_path=model_path,
        n_ctx=config.resolved_n_ctx(),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        n_threads=config.n_threads,
        verbose=False,
    )


def _build_prompt() -> str:
    """Return the shared prompt for the LLM review stage."""
    return (
        "You analyze bioimaging dataset validation reports.\n"
        "Return strict JSON matching this schema:\n"
        "{{"
        '"hints":[{{"title":"string","detail":"string","confidence":"low|medium|high"}}],'
        '"findings":[{{"category":"filetree|metadata|xml|images|content|pipeline",'
        '"summary":"string","detail":"string","confidence":"low|medium|high",'
        '"plate_id":"string|null"}}]'
        "}}\n"
        "Findings should describe suspected problems or likely hidden risks "
        "that fit the observed filetree or content patterns.\n"
        "Hints should stay concise and actionable.\n"
        "Do not restate the full report.\n\n"
        "{review_json}\n"
    )


def _payload_to_review(
    payload: AdvisoryPayload,
    *,
    provider: str,
    model: str,
) -> LLMReviewResult:
    """Convert a structured payload into a review result."""
    return LLMReviewResult(
        hints=tuple(
            LLMHint(
                title=hint.title,
                detail=hint.detail,
                confidence=hint.confidence,
            )
            for hint in payload.hints
        ),
        findings=tuple(
            LLMFinding(
                category=finding.category,
                summary=finding.summary,
                detail=finding.detail,
                confidence=finding.confidence,
                plate_id=finding.plate_id,
            )
            for finding in payload.findings
        ),
        provider=provider,
        model=model,
        status="completed",
    )


def _invoke_langchain(report: ValidationReport, config: LLMConfig) -> LLMReviewResult:
    """Run model review against a local GGUF model."""
    StrOutputParser = importlib.import_module(
        "langchain_core.output_parsers"
    ).StrOutputParser
    PromptTemplate = importlib.import_module("langchain_core.prompts").PromptTemplate

    model_path = get_cached_model_path(
        config.resolved_model(),
        cache_dir=config.cache_dir,
        offline=config.offline,
    )
    llm = _build_langchain_llm(model_path, config)
    prompt = PromptTemplate.from_template(_build_prompt())
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke(
        {"review_json": json.dumps(_review_payload(report), indent=2)}
    )
    return _parse_payload(response, provider="langchain", model=config.model_alias)


def _invoke_instructor(report: ValidationReport, config: LLMConfig) -> LLMReviewResult:
    """Run model review through an OpenAI-compatible local server."""
    instructor = importlib.import_module("instructor")
    OpenAI = importlib.import_module("openai").OpenAI
    client = instructor.from_openai(
        OpenAI(base_url=config.base_url, api_key="meerqat-local")
    )
    model_name = _resolve_instructor_model_name(config.base_url, config.model_alias)
    payload = client.chat.completions.create(
        model=model_name,
        response_model=AdvisoryPayload,
        messages=[
            {
                "role": "system",
                "content": (
                    "You analyze bioimaging validation reports and return "
                    "concise hints plus suspected hidden issues."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(_review_payload(report), indent=2),
            },
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return _payload_to_review(payload, provider="instructor", model=model_name)


def _parse_payload(raw: str, *, provider: str, model: str) -> LLMReviewResult:
    """Parse JSON model output."""
    try:
        payload = AdvisoryPayload.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as error:
        return LLMReviewResult(
            hints=(
                LLMHint(
                    title="LLM output could not be parsed",
                    detail=f"LLM review returned invalid structured output: {error}",
                    confidence="low",
                ),
            ),
            provider=provider,
            model=model,
            status="degraded",
            error=str(error),
        )
    return _payload_to_review(payload, provider=provider, model=model)


def _parse_hints(raw: str) -> tuple[LLMHint, ...]:
    """Parse JSON LLM review hints."""
    return _parse_payload(raw, provider="unknown", model="unknown").hints


def _format_dependency_error(
    instructor_error: BaseException | None = None,
    langchain_error: BaseException | None = None,
) -> str:
    """Format a clearer error when LLM dependencies are unavailable."""
    details: list[str] = []
    if instructor_error is not None:
        details.append(f"instructor path failed: {instructor_error}")
    if langchain_error is not None:
        details.append(f"langchain fallback failed: {langchain_error}")
    detail_text = "; ".join(details)
    return (
        "MeerQat's core LLM review requires the installed LLM dependencies and a local "
        "model runtime. Run `uv sync` to install the full package, then ensure "
        "your local model is available. If you intend to use the preferred local "
        "server path, pass `--llm-provider instructor`. "
        f"{detail_text}"
    )


def _is_connection_failure(error: BaseException) -> bool:
    """Return whether an exception looks like a local connection failure."""
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return True
    name = type(error).__name__
    if name in {"APIConnectionError", "ConnectError"}:
        return True
    return "connection error" in str(error).lower()


def _is_local_server_startup_failure(error: BaseException) -> bool:
    """Return whether an exception looks like local server bootstrap failure."""
    message = str(error).lower()
    return isinstance(error, RuntimeError) and (
        "llama.cpp server" in message
        or "timed out waiting" in message
        or "startup failed" in message
        or "server dependencies are missing" in message
    )


def _attempt_instructor_review(
    report: ValidationReport,
    config: LLMConfig,
) -> tuple[LLMReviewResult | None, BaseException | None]:
    """Run the preferred Instructor path and normalize recoverable failures."""
    primary_error: BaseException | None = None
    try:
        _ensure_local_instructor_server(config)
        return _invoke_instructor(report, config), None
    except Exception as error:
        primary_error = error
        if _is_connection_failure(error):
            try:
                _ensure_local_instructor_server(config)
                return _invoke_instructor(report, config), None
            except Exception as retry_error:
                if _is_connection_failure(retry_error):
                    return None, retry_error
                return None, retry_error
        if isinstance(
            error,
            (
                ImportError,
                AttributeError,
                ModuleNotFoundError,
                OSError,
                ValueError,
            ),
        ) or _is_local_server_startup_failure(error):
            return None, primary_error
        return None, primary_error


def _attempt_langchain_review(
    report: ValidationReport,
    config: LLMConfig,
) -> tuple[LLMReviewResult | None, BaseException | None]:
    """Run the fallback LangChain path and normalize import/runtime failures."""
    try:
        return _invoke_langchain(report, config), None
    except Exception as error:
        return None, error


def run_ready_checks(config: LLMConfig) -> ReadyReport:
    """Exercise the configured local LLM runtime and return readiness results."""
    checks: list[ReadyCheck] = []
    spec = config.resolved_model()

    try:
        model_path = get_cached_model_path(
            spec,
            cache_dir=config.cache_dir,
            offline=config.offline,
        )
        checks.append(
            ReadyCheck(
                name="model_path",
                status="pass",
                detail=f"Resolved model at {model_path}.",
            )
        )
    except Exception as error:
        checks.append(
            ReadyCheck(
                name="model_path",
                status="fail",
                detail=f"Could not resolve model: {error}",
            )
        )
        return ReadyReport(
            status="fail",
            provider=config.provider,
            model=config.model_alias,
            checks=tuple(checks),
        )

    if config.provider == "instructor":
        try:
            _ensure_local_instructor_server(config)
            checks.append(
                ReadyCheck(
                    name="local_server",
                    status="pass",
                    detail=f"Local server is reachable at {config.base_url}.",
                )
            )
        except Exception as error:
            checks.append(
                ReadyCheck(
                    name="local_server",
                    status="fail",
                    detail=f"Could not prepare local server: {error}",
                )
            )
            return ReadyReport(
                status="fail",
                provider=config.provider,
                model=config.model_alias,
                checks=tuple(checks),
            )

        try:
            OpenAI = importlib.import_module("openai").OpenAI
            client = OpenAI(base_url=config.base_url, api_key="meerqat-local")
            model_name = _resolve_instructor_model_name(
                config.base_url,
                config.model_alias,
            )
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "Reply with READY."}],
                temperature=0.0,
                max_tokens=4,
            )
            content = response.choices[0].message.content or ""
            checks.append(
                ReadyCheck(
                    name="inference",
                    status="pass",
                    detail=(
                        f"Received a response from model '{model_name}': "
                        f"{content.strip() or '[empty content]'}"
                    ),
                )
            )
        except Exception as error:
            checks.append(
                ReadyCheck(
                    name="inference",
                    status="fail",
                    detail=f"Inference probe failed: {error}",
                )
            )
            return ReadyReport(
                status="fail",
                provider=config.provider,
                model=config.model_alias,
                checks=tuple(checks),
            )
    else:
        try:
            llm = _build_langchain_llm(model_path, config)
            response = llm.invoke("Reply with READY.")
            checks.append(
                ReadyCheck(
                    name="inference",
                    status="pass",
                    detail=f"Received a response from the local model: {response!s}",
                )
            )
        except Exception as error:
            checks.append(
                ReadyCheck(
                    name="inference",
                    status="fail",
                    detail=f"Inference probe failed: {error}",
                )
            )
            return ReadyReport(
                status="fail",
                provider=config.provider,
                model=config.model_alias,
                checks=tuple(checks),
            )

    return ReadyReport(
        status="pass",
        provider=config.provider,
        model=config.model_alias,
        checks=tuple(checks),
    )


def generate_llm_review(
    report: ValidationReport,
    config: LLMConfig,
) -> LLMReviewResult:
    """Generate the core model review for a validation report."""

    def unavailable_result(
        *,
        provider: str,
        error_message: str,
    ) -> LLMReviewResult:
        """Build a structured unavailable-review result."""
        return LLMReviewResult(
            hints=(
                LLMHint(
                    title="LLM review unavailable",
                    detail=error_message,
                    confidence="low",
                ),
            ),
            provider=provider,
            model=config.model_alias,
            status="failed",
            error=error_message,
        )

    result: LLMReviewResult | None = None

    if not config.enabled:
        result = LLMReviewResult(status="disabled")
    elif config.provider == "instructor":
        review, instructor_error = _attempt_instructor_review(report, config)
        if review is not None:
            result = review
        else:
            review, fallback_error = _attempt_langchain_review(report, config)
            if review is not None:
                result = review
            elif fallback_error is not None:
                message = _format_dependency_error(instructor_error, fallback_error)
                result = unavailable_result(
                    provider="instructor",
                    error_message=message,
                )
    else:
        review, error = _attempt_langchain_review(report, config)
        if review is not None:
            result = review
        elif error is not None:
            message = _format_dependency_error(langchain_error=error)
            result = unavailable_result(provider="langchain", error_message=message)

    if result is None:
        provider = "instructor" if config.provider == "instructor" else config.provider
        result = unavailable_result(
            provider=provider,
            error_message="LLM review did not produce a result.",
        )

    return result
