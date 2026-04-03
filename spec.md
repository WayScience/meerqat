# MeerQat Specification 🐾

## Overview

**MeerQat** is a Python package and CLI tool designed to validate bioimaging datasets by detecting structural inconsistencies, metadata gaps, and cross-source mismatches before downstream analysis.

MeerQat acts as a *sentinel* — identifying issues early, reducing friction between imaging and computational workflows, and improving reproducibility.

______________________________________________________________________

## Problem Statement

Bioimaging datasets often suffer from:

- Missing required files (e.g., `Index.xml`) from the Phenix Harmony microscope
- Inconsistent plate naming conventions
- Metadata mismatches or missing entries with provided platemap files
- Metadata/platemap files not provided
- Folder-to-XML identity mismatches
- Partial or incomplete image sets
- Silent failures in downstream pipelines

These issues are frequently discovered late, leading to:

- wasted computational time
- manual debugging cycles
- ambiguity between data producers and analysts

MeerQat aims to detect these issues **early and systematically**.

______________________________________________________________________

## Goals

### Primary Goals

- Validate dataset **structure, completeness, and consistency**
- Detect issues **before pipeline execution**
- Provide **clear, actionable feedback**
- Bridge the gap between imaging and computational teams

### Secondary Goals

- Infer dataset patterns using local LLMs
- Suggest configuration and naming conventions
- Provide structured outputs for automation

______________________________________________________________________

## Non-Goals (MVP)

- Biological quality assessment (e.g., phenotype validity)
- Deep image-level QC (e.g., focus, segmentation quality)
- Replacement of downstream pipelines

______________________________________________________________________

## Core Concepts

### Dataset

A collection of plates, files, and metadata representing an imaging experiment.

### Plate

A logical unit containing:

- image files
- XML metadata
- associated metadata entries
- Phenix Harmony is an initial focus but we will later expand to many other microscope and image output types (so keep abstractions in mind)

### Metadata Record

A row from an external metadata file (CSV/XLSX). The analysts would prefer to already be in CSV format over XLSX. LLM should convert if possible.

### Validation Rule

A deterministic check applied to the dataset.

### Validation Issue

A structured record of a detected problem.

### Pattern Hint

An LLM-derived suggestion or interpretation.

______________________________________________________________________

## System Architecture

MeerQat consists of two validation layers:

### 1. Deterministic Validation (Source of Truth)

- Rule-based checks
- Fully reproducible
- Required for pass/fail decisions

### 2. LLM-Assisted Pattern Inference (Advisory)

- Prefers Instructor with a local OpenAI-compatible `llama.cpp` server
- Falls back to direct local GGUF execution when Instructor is unavailable
- Provides:
  - pattern inference
  - anomaly explanations
  - config suggestions

This layer does not make pass/fail decisions. It operates on the completed
deterministic report and adds interpretation for human operators.

**Principle:** Validation is deterministic. Interpretation is advisory.

______________________________________________________________________

## Functional Requirements

### Input

- Dataset directory
- Optional metadata file(s)
- Optional configuration file (YAML)

______________________________________________________________________

### Dataset Ingestion

The system must:

- Scan filesystem structure
- Identify plate directories
- Parse XML files
- Load metadata tables
- Count files and image sets

______________________________________________________________________

### Normalization

The system must:

- Normalize identifiers (plate IDs, filenames)
- Map relationships between:
  - folders
  - XML contents
  - metadata entries

______________________________________________________________________

### Validation Rules

#### Structure Checks

- Required folders exist
- Required files present (e.g., `Index.xml`)

#### Naming Checks

- Plate names follow expected patterns
- Nonstandard names flagged

#### XML Consistency

- XML is parseable
- XML plate ID matches folder

#### Metadata Coverage

- Every plate has metadata
- Metadata entries map to real plates

#### Count Validation

- Plate count matches expectation
- Image set counts match expected values

#### Pipeline Readiness

- Dataset can be safely processed
- Partial execution risks are flagged

______________________________________________________________________

### Output

#### Human-readable report

- Summary (pass/warn/fail)
- Issues grouped by severity and plate
- Suggested remediation
- LLM hints for likely causes, hidden risks, and config suggestions

#### Machine-readable report (JSON)

- Structured issues
- Dataset summary
- Rule results
- Batch validation summary

#### Exit codes

- `0`: pass
- `1`: warnings
- `2`: failure
- `3`: system error

## Implemented Scope

The package implementation in this repository currently includes:

- Deterministic validation for structure, XML parseability, folder/XML mismatches, metadata coverage, orphan metadata, image counts, zero-byte image checks, and mixed modality checks
- Assay templates for `phenix_harmony` and `generic_microscopy`
- Support for CSV and XLSX metadata inputs
- Image inventory support for TIFF, OME-TIFF, OME-Zarr, PNG, and JPEG assets
- Single-dataset and batch validation through both API and CLI
- JSON, Markdown, and HTML outputs
- Built-in local LLM review with configurable model selection

______________________________________________________________________

## Domain Model

### Dataset

```python
class Dataset:
    dataset_id: str | None
    plates: list[Plate]
    metadata_records: list[MetadataRecord]
```

### Plate

```python
class Plate:
    folder_name: str
    normalized_plate_id: str | None
    xml_plate_id: str | None
    metadata_plate_id: str | None
```

### ValidationIssue

```python
class ValidationIssue:
    rule_id: str
    severity: str
    message: str
    entity_id: str | None
```

______________________________________________________________________

## Configuration

Example YAML:

```yaml
dataset:
  dataset_id: CHP-134

plate_naming:
  regex: "^BR[0-9]+$"

required_files:
  - "Images/Index.xml"

expectations:
  expected_plate_count: 27
  expected_image_sets_per_plate: 3456

metadata:
  plate_id_column: PlateID
```

______________________________________________________________________

## CLI Interface

### Validate dataset

meerqat validate /data/CHP-134 --metadata metadata.xlsx --config assay.yaml

### Suggest config

meerqat suggest-config /data

### Explain anomalies

meerqat explain /data

______________________________________________________________________

## LLM Integration

### Backend

- `llama.cpp` (local models)
- GGUF models from Hugging Face

### Structured Output

- `instructor`
- `pydantic` schemas

### Tasks

- Naming pattern inference
- Alias detection
- Anomaly explanation
- Config suggestion

______________________________________________________________________

## Design Principles

### 1. Early Detection

Catch issues before pipelines run.

### 2. Transparency

Show evidence for every issue.

### 3. Non-Judgmental

Avoid blame; focus on clarity.

### 4. Configurable

Support diverse assay types.

### 5. Extensible

Modular rules and LLM components.

______________________________________________________________________

## MVP Scope

- Dataset scanning
- XML + metadata parsing
- Core validation rules
- JSON + CLI reporting

______________________________________________________________________

## Future Work

- Image-level QC
- Visualization dashboards
- CI integration
- Batch validation workflows

______________________________________________________________________

## Success Criteria

MeerQat successfully identifies:

- Missing required files
- Naming inconsistencies
- Metadata gaps
- Folder/XML mismatches
- Partial datasets

And provides actionable guidance before analysis begins.

______________________________________________________________________

## Positioning

**MeerQat** is a sentinel for bioimaging datasets —
detecting issues early so your analysis can proceed with confidence.
