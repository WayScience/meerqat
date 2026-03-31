# MeerQat 🐾

**MeerQat** is a Python package and CLI for validating bioimaging datasets before pipeline execution. It scans filesystem structure, parses XML and tabular metadata, checks cross-source consistency, and emits reports for both humans and automation.

> A sentinel for bioimaging data.

## What It Validates

- Missing required files such as `Index.xml`
- Plate naming inconsistencies
- Folder/XML identity mismatches
- Missing or orphan metadata rows
- Partial image sets and zero-byte image files
- Mixed image modalities within a single plate

Validation is deterministic. The LLM review is built in and adds interpretive output without owning pass/fail.

## Deterministic Vs LLM Review

MeerQat has two separate layers:

- Deterministic validation scans the dataset, parses XML and metadata, applies rules, and produces the real pass, warn, or fail outcome.
- The built-in LLM review runs after that deterministic report exists and adds hints plus suspected hidden issues such as likely root causes, naming-pattern observations, config suggestions, and filetree/content anomalies.

The LLM does not decide issue codes, severity, or exit codes.

## Features

- Deterministic validation engine for structure, XML, metadata, and count checks
- Python API and CLI for single-dataset or batch validation
- JSON, Markdown, and HTML reporting
- Assay templates for Phenix Harmony and generic microscopy layouts
- OME-Zarr, TIFF, OME-TIFF, PNG, and JPEG inventory support
- Built-in local LLM review with Instructor as the preferred path and LangChain as fallback
- CI-friendly exit codes: `0` pass, `1` warning, `2` failure, `3` system error

## Install

```bash
uv sync
```

## CLI

```bash
meerqat validate /data/CHP-134 \
  --metadata metadata.csv \
  --config assay.yaml \
  --report-json report.json \
  --report-markdown report.md \
  --report-html report.html
```

This command runs deterministic validation and then the built-in LLM review.

Batch validation:

```bash
meerqat batch-validate /data/run1 /data/run2 --report-json batch-report.json
```

List built-in local model presets:

```bash
meerqat models
```

Run the built-in LLM review with the default local preset:

```bash
meerqat validate /data/CHP-134 --offline
```

MeerQat runs the same deterministic validation first, then adds `advisory_hints`, `llm_findings`, and `llm_review` metadata to the finished report. It prefers the Instructor path, will try to start a local `llama.cpp` server at the default local endpoint when needed, and falls back to the direct LangChain `llama.cpp` path otherwise.

By default, the LLM base URL is local: `http://127.0.0.1:8000/v1`. The
`--offline` flag is opt-in and defaults to disabled unless you pass it or set
it in config.

Use an OpenAI-compatible local `llama.cpp` server with Instructor:

```bash
meerqat validate /data/CHP-134 \
  --llm-provider instructor \
  --llm-model qwen2.5-3b-instruct \
  --llm-base-url http://127.0.0.1:8000/v1
```

If nothing is already listening on the default local base URL, MeerQat will try
to start a local `llama.cpp` server automatically.

## Python API

```python
from meerqat import ValidationConfig, validate_dataset

report = validate_dataset(
    "/data/CHP-134",
    metadata_paths=["metadata.csv"],
    config=ValidationConfig(expected_images_per_plate=384),
)

print(report.summary.status)
```

The report includes `advisory_hints`, `llm_findings`, and `llm_review`, but `report.summary.status` still comes from deterministic rules.

## Sample Datasets

A small checked-in regression corpus lives under `tests/data`. You can use it
to exercise known failure modes quickly:

```bash
meerqat validate tests/data/xml_mismatch/dataset \
  --metadata tests/data/xml_mismatch/metadata.csv
```

The current scenarios cover:

- missing `Index.xml`
- folder/XML identifier mismatches
- missing metadata coverage
- mixed image modalities

## Configuration

MeerQat accepts a YAML config file:

```yaml
dataset_id: assay_2026_03_30
assay_template: phenix_harmony
expected_images_per_plate: 384
expected_plate_count: 8
metadata_plate_column: plate_id
fail_on_warning: false
llm:
  enabled: true
  provider: instructor
  model_alias: qwen2.5-3b-instruct
  base_url: http://127.0.0.1:8000/v1
  offline: true
```

## Roadmap Coverage

The current package covers the roadmap with lightweight implementations:

- Phase 1: dataset scanning, XML/metadata parsing, core rules, CLI and JSON reporting
- Phase 2: local LLM integration, structured outputs, pattern hints, suspected hidden issues, config suggestions
- Phase 3: assay templates, richer Markdown/HTML reporting
- Phase 4: OME-Zarr and TIFF inventory support plus basic image-file QC
- Phase 5: CI-friendly behavior and batch validation support

## Local Model Choice

The default LLM preset is `qwen2.5-3b-instruct`, which is a lightweight and more capable default than the earlier TinyLlama-based prototype. You can override the model alias, repository, and GGUF filename from either the Python API or the CLI.
