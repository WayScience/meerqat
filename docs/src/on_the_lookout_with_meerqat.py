# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.17.3
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# ruff: noqa: E402, E501

# # On the Lookout with MeerQat
#
# This notebook shows the basic MeerQat workflow.

# ## Where the LLM Helps
#
# - **Deterministic validation** decides the real pass, warn, or fail result.
# - **LLM review** runs afterward and adds interpretation plus suspected hidden issues.
#
# MeerQat prefers **Instructor** for its core review path and falls back to **LangChain** if needed.

# ## Configure the Local Model
#
# MeerQat uses the LLM on every run. In this notebook we make that explicit up front.

# +
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (
            candidate / "src" / "meerqat"
        ).exists():
            return candidate
    raise RuntimeError("Could not locate the MeerQat repository root.")


repo_root = _find_repo_root(Path.cwd().resolve())
src_root = repo_root / "src"
if str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))

from meerqat import LLMConfig, ValidationConfig, validate_dataset, write_reports

llm_config = LLMConfig(
    provider="instructor",
    model_alias="tinyllama",
    base_url="http://127.0.0.1:8000/v1",
    n_ctx=2048,
    max_tokens=256,
)
validation_config = ValidationConfig(llm=llm_config)

{
    "repo_root": str(repo_root),
    "provider": llm_config.provider,
    "model": llm_config.model_alias,
    "base_url": llm_config.base_url,
    "n_ctx": llm_config.resolved_n_ctx(),
}

# -

# ## Validate a Known-Good Dataset
#
# The repository includes small sample datasets under `tests/data`. We can use the valid fixture first.

# +
data_root = repo_root / "tests" / "data" / "valid_minimal"
report = validate_dataset(
    data_root / "dataset",
    metadata_paths=[data_root / "metadata.csv"],
    config=validation_config,
)

report.summary.status

# -

# The expected result is `"pass"`.

report.summary.to_dict()


# ## Inspect a Broken Dataset
#
# Now switch to a sample dataset where the XML plate identifier does not match the folder name.

# +
broken_root = repo_root / "tests" / "data" / "xml_mismatch"
broken_report = validate_dataset(
    broken_root / "dataset",
    metadata_paths=[broken_root / "metadata.csv"],
    config=validation_config,
)

broken_report.summary.status

# -

# The expected result is `"fail"`. That fail status comes from deterministic rules, not from the LLM.

[
    {
        "code": issue.code,
        "severity": issue.severity,
        "message": issue.message,
    }
    for issue in broken_report.issues
]


# After the issue list is known, the LLM can help explain it, for example by suggesting a likely root cause or a useful config setting. The validator still owns the actual outcome.

# ## Inspect Filetree Risks
#
# MeerQat also checks for broader filetree problems inspired by the same class of checks used in `nViz`: empty directories, extension inventory, and confusingly similar directory names.

# +
filetree_root = repo_root / "tmp_notebook_filetree_demo"
if filetree_root.exists():
    import shutil

    shutil.rmtree(filetree_root)

plate_dir = filetree_root / "Plate_Z09"
plate_dir.mkdir(parents=True)
(plate_dir / "Index.xml").write_text('<Plate PlateID="Plate_Z09"></Plate>')
(plate_dir / "image_001.tiff").write_bytes(b"pixels")
(filetree_root / "empty_dir").mkdir()
(filetree_root / "segment_A").mkdir()
(filetree_root / "segment_B").mkdir()

filetree_report = validate_dataset(filetree_root, config=validation_config)

{
    "status": filetree_report.summary.status,
    "filetree_summary": filetree_report.dataset.filetree_summary.to_dict(),
    "filetree_issues": [
        issue.to_dict()
        for issue in filetree_report.issues
        if issue.code.startswith("dataset.")
    ],
}

# -

# The deterministic issues above come from the filetree scan, and the LLM can then add higher-level interpretation on top of that structure.

# ## Use the CLI from a Notebook
#
# In a notebook, a leading `!` runs a shell command. MeerQat installs a `meerqat` entrypoint, so the CLI stays simple.
#
# `!meerqat validate {repo_root / "tests" / "data" / "xml_mismatch" / "dataset"} --metadata {repo_root / "tests" / "data" / "xml_mismatch" / "metadata.csv"}`

# ## LLM Review
#
# MeerQat runs the same deterministic validation first and then adds LLM review output. The same happens through the CLI.

# +
#
# !meerqat validate {repo_root / "tests" / "data" / "xml_mismatch" / "dataset"} --metadata {repo_root / "tests" / "data" / "xml_mismatch" / "metadata.csv"}

# -

# If the local model is running, the report includes `advisory_hints`, `llm_findings`, and `llm_review` alongside the deterministic issues. If the model runtime is unavailable, MeerQat still records that LLM review failure in the report instead of silently skipping it.

# ## Write Reports
#
# MeerQat can also emit machine-readable and human-readable reports.

# +
from tempfile import TemporaryDirectory

with TemporaryDirectory() as tmpdir:
    output_dir = Path(tmpdir)
    write_reports(
        broken_report,
        json_path=output_dir / "report.json",
        markdown_path=output_dir / "report.md",
        html_path=output_dir / "report.html",
    )
    generated_files = sorted(path.name for path in output_dir.iterdir())

generated_files
