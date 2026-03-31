# MeerQat Architecture

## Overview

MeerQat combines:

1. Deterministic validation (source of truth)
1. LLM-assisted pattern inference (built in)

The boundary matters:

- Deterministic validation owns issue detection, severity assignment, report status, and exit codes.
- The LLM layer consumes the completed deterministic report and adds interpretation only.

## Core Components

- CLI / API layer
- Ingestion layer
  - Plate discovery
  - XML parsing
  - CSV/XLSX metadata loading
  - Image inventory across TIFF, OME-TIFF, OME-Zarr, PNG, and JPEG
- Normalization layer
  - Identifier normalization across folders, XML, and metadata
- Validation engine
  - Structural checks
  - Naming checks
  - XML consistency checks
  - Metadata coverage checks
  - Count and image-file QC checks
- Core LLM review engine
  - Preferred Instructor mode against an OpenAI-compatible local `llama.cpp` server
  - LangChain + local GGUF fallback via `langchain-community` + `llama.cpp`
- Reporting system
  - JSON
  - Markdown
  - HTML
  - CI-friendly exit codes

## Principle

**Validation is deterministic. Interpretation is advisory.**
