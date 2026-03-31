# Meerqat 🐾

**Meerqat** is a Python package and CLI for validating bioimaging datasets before pipeline execution. It scans filesystem structure, parses XML and tabular metadata, checks cross-source consistency, and emits reports for both humans and automation.

> A sentinel for bioimaging data.

## What It Validates

- Missing required files such as `Index.xml`
- Plate naming inconsistencies
- Folder/XML identity mismatches
- Missing or orphan metadata rows
- Partial image sets and zero-byte image files
- Mixed image modalities within a single plate

Validation is deterministic. Optional LLM output is advisory only.

## Features

- Deterministic validation engine for structure, XML, metadata, and count checks
- Python API and CLI for single-dataset or batch validation
- JSON, Markdown, and HTML reporting
- Assay templates for Phenix Harmony and generic microscopy layouts
- OME-Zarr, TIFF, OME-TIFF, PNG, and JPEG inventory support
- Optional local LLM advisory mode using a GGUF model or a local OpenAI-compatible `llama.cpp` server
- CI-friendly exit codes: `0` pass, `1` warning, `2` failure, `3` system error

## Install

```bash
uv sync
```

To enable local advisory mode as well:

```bash
uv sync --extra llm
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

Batch validation:

```bash
meerqat batch-validate /data/run1 /data/run2 --report-json batch-report.json
```

List built-in local model presets:

```bash
meerqat models
```

Enable advisory mode with the default lightweight model preset:

```bash
meerqat validate /data/CHP-134 --advisory --offline
```

Use an OpenAI-compatible local `llama.cpp` server with Instructor:

```bash
meerqat validate /data/CHP-134 \
  --advisory \
  --llm-provider instructor \
  --llm-model qwen2.5-3b-instruct \
  --llm-base-url http://127.0.0.1:8000/v1
```

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

Meerqat accepts a YAML config file:

```yaml
dataset_id: assay_2026_03_30
assay_template: phenix_harmony
expected_images_per_plate: 384
expected_plate_count: 8
metadata_plate_column: plate_id
fail_on_warning: false
llm:
  enabled: false
  provider: langchain
  model_alias: qwen2.5-3b-instruct
  offline: true
```

## Roadmap Coverage

The current package covers the roadmap with lightweight implementations:

- Phase 1: dataset scanning, XML/metadata parsing, core rules, CLI and JSON reporting
- Phase 2: optional local LLM advisory integration, structured outputs, pattern hints, config suggestions
- Phase 3: assay templates, richer Markdown/HTML reporting
- Phase 4: OME-Zarr and TIFF inventory support plus basic image-file QC
- Phase 5: CI-friendly behavior and batch validation support

## Local Model Choice

The default advisory preset is `qwen2.5-3b-instruct`, which is a more capable lightweight default than the TinyLlama example in `local_llm_reference.py`. You can override the model alias, repository, and GGUF filename from either the Python API or the CLI.
