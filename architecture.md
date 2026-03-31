
# Meerqat Architecture

## Overview

Meerqat combines:

1. Deterministic validation (source of truth)
2. LLM-assisted pattern inference (advisory)

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
- LLM advisory engine
  - Direct local GGUF execution via `langchain-community` + `llama.cpp`
  - Optional Instructor mode against an OpenAI-compatible local `llama.cpp` server
- Reporting system
  - JSON
  - Markdown
  - HTML
  - CI-friendly exit codes

## Principle

**Validation is deterministic. Interpretation is advisory.**
