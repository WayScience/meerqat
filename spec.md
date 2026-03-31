# Meerqat Specification 🐾

## Overview

**Meerqat** is a Python package and CLI tool designed to validate bioimaging datasets by detecting structural inconsistencies, metadata gaps, and cross-source mismatches before downstream analysis.

Meerqat acts as a *sentinel* — identifying issues early, reducing friction between imaging and computational workflows, and improving reproducibility.

---

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

Meerqat aims to detect these issues **early and systematically**.

---

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

---

## Non-Goals (MVP)

- Biological quality assessment (e.g., phenotype validity)  
- Deep image-level QC (e.g., focus, segmentation quality)  
- Replacement of downstream pipelines

---

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

---

## System Architecture

Meerqat consists of two validation layers:

### 1\. Deterministic Validation (Source of Truth)

- Rule-based checks  
- Fully reproducible  
- Required for pass/fail decisions

### 2\. LLM-Assisted Pattern Inference (Advisory)

- Uses local `llama.cpp` models  
- Structured via Instructor  
- Provides:  
  - pattern inference  
  - anomaly explanations  
  - config suggestions

**Principle:** Validation is deterministic. Interpretation is advisory.

---

## Functional Requirements

### Input

- Dataset directory  
- Optional metadata file(s)  
- Optional configuration file (YAML)

---

### Dataset Ingestion

The system must:

- Scan filesystem structure  
- Identify plate directories  
- Parse XML files  
- Load metadata tables  
- Count files and image sets

---

### Normalization

The system must:

- Normalize identifiers (plate IDs, filenames)  
- Map relationships between:  
  - folders  
  - XML contents  
  - metadata entries

---

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

---

### Output

#### Human-readable report

- Summary (pass/warn/fail)  
- Issues grouped by severity and plate  
- Suggested remediation
- Optional advisory hints for likely causes and config suggestions

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
- Optional local LLM advisory mode with configurable model selection

---

## Domain Model

### Dataset

class Dataset:

    dataset\_id: str | None

    plates: list\[Plate\]

    metadata\_records: list\[MetadataRecord\]

### Plate

class Plate:

    folder\_name: str

    normalized\_plate\_id: str | None

    xml\_plate\_id: str | None

    metadata\_plate\_id: str | None

### ValidationIssue

class ValidationIssue:

    rule\_id: str

    severity: str

    message: str

    entity\_id: str | None

---

## Configuration

Example YAML:

dataset:

  dataset\_id: CHP-134

plate\_naming:

  regex: "^BR\[0-9\]+$"

required\_files:

  \- "Images/Index.xml"

expectations:

  expected\_plate\_count: 27

  expected\_image\_sets\_per\_plate: 3456

metadata:

  plate\_id\_column: PlateID

---

## CLI Interface

### Validate dataset

meerqat validate /data/CHP-134   \--metadata metadata.xlsx   \--config assay.yaml

### Suggest config

meerqat suggest-config /data

### Explain anomalies

meerqat explain /data

---

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

---

## Design Principles

### 1\. Early Detection

Catch issues before pipelines run.

### 2\. Transparency

Show evidence for every issue.

### 3\. Non-Judgmental

Avoid blame; focus on clarity.

### 4\. Configurable

Support diverse assay types.

### 5\. Extensible

Modular rules and LLM components.

---

## MVP Scope

- Dataset scanning  
- XML \+ metadata parsing  
- Core validation rules  
- JSON \+ CLI reporting

---

## Future Work

- OME-Zarr support  
- Image-level QC  
- Visualization dashboards  
- CI integration  
- Batch validation workflows

---

## Success Criteria

Meerqat successfully identifies:

- Missing required files  
- Naming inconsistencies  
- Metadata gaps  
- Folder/XML mismatches  
- Partial datasets

And provides actionable guidance before analysis begins.

---

## Positioning

**Meerqat** is a sentinel for bioimaging datasets —  
detecting issues early so your analysis can proceed with confidence.  
