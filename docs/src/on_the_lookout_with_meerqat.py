# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.17.3
#   kernelspec:
#     display_name: meerqat
#     language: python
#     name: python3
# ---

# # On the Lookout with MeerQat
#
# This notebook shows the basic MeerQat workflow.

# ## Where the LLM Helps
#
# - **Deterministic validation** decides the real pass, warn, or fail result.
# - **LLM review** runs afterward and adds interpretation plus suspected hidden issues.
#
# MeerQat prefers **Instructor** for its core review path and falls back to
# **LangChain** if needed.
#

# ## Configure the Local Model
#
# MeerQat uses the LLM on every run. For the basic walkthrough, the defaults are
# enough.
#

# +
import pathlib
from tempfile import TemporaryDirectory

from meerqat import ValidationConfig, validate_dataset, write_reports


def find_repo_root(start: pathlib.Path) -> pathlib.Path:
    """Walk upward until a repository marker is found."""
    for candidate in (start, *start.parents):
        if any(
            (candidate / marker).exists()
            for marker in (".git", "pyproject.toml", "setup.py")
        ):
            return candidate
    raise RuntimeError("Could not locate the MeerQat repository root.")


if "__file__" in globals():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
else:
    repo_root = find_repo_root(pathlib.Path.cwd().resolve())
# -

# ## Validate a Known-Good Dataset
#
# The repository includes small sample datasets under `tests/data`. We can use
# the valid fixture first. Because the matching `metadata.csv` lives next to the
# dataset folder, MeerQat will discover it automatically.
#

# +
data_root = repo_root / "tests" / "data" / "valid_minimal"
report = validate_dataset(
    data_root / "dataset",
)

report.summary.status
# -

# The expected result is `"pass"`.
#

report.summary.to_dict()

# ## Inspect a Broken Dataset
#
# Now switch to a sample dataset where the XML plate identifier does not match
# the folder name.
#

# +
broken_root = repo_root / "tests" / "data" / "xml_mismatch"
broken_report = validate_dataset(
    broken_root / "dataset",
)

broken_report.summary.status
# -

# The expected result is `"fail"`. That fail status comes from deterministic
# rules, not from the LLM.
#

# After the issue list is known, the LLM can help explain it, for example by
# suggesting a likely root cause or a useful config setting. The validator still
# owns the actual outcome.
#

# ## Inspect Filetree Risks
#
# MeerQat also checks for broader filetree problems inspired by the same class
# of checks used in `nViz`: empty directories, extension inventory, and
# confusingly similar directory names.
#

# +
filetree_root = repo_root / "tests" / "data" / "filetree_risks"
filetree_report = validate_dataset(filetree_root / "dataset")

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

# The deterministic issues above come from the filetree scan, and the LLM can
# then add higher-level interpretation on top of that structure.
#

# ## Customize Validation
#
# If you want to tune the local model or other validation behavior, pass an
# explicit `ValidationConfig(...)`.
#

validation_config = ValidationConfig()
validation_config

# ## Use the CLI from a Notebook
#
# In a notebook, a leading `!` runs a shell command. MeerQat installs a
# `meerqat` entrypoint, so the CLI stays simple.
#
# `!meerqat validate`
# `{repo_root / "tests" / "data" / "xml_mismatch" / "dataset"}`
#

# !meerqat validate \
#   {repo_root / "tests" / "data" / "xml_mismatch" / "dataset"}

# ## LLM Review
#
# MeerQat runs the same deterministic validation first and then adds LLM review
# output. The same happens through the CLI.
#

# If the local model is running, the report includes `llm_hints`,
# `llm_findings`, and `llm_review` alongside the deterministic issues. If the
# model runtime is unavailable, MeerQat still records that LLM review failure in
# the report instead of silently skipping it. LLM summaries can still be wrong,
# so verify them against the underlying dataset before acting on them.
#

# ## Write Reports
#
# MeerQat can also emit machine-readable and human-readable reports.
#

# +
with TemporaryDirectory() as tmpdir:
    output_dir = pathlib.Path(tmpdir)
    write_reports(
        broken_report,
        json_path=output_dir / "report.json",
        markdown_path=output_dir / "report.md",
        html_path=output_dir / "report.html",
    )
    generated_files = sorted(path.name for path in output_dir.iterdir())

generated_files
