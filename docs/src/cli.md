# CLI

## Validate One Dataset

```bash
meerqat validate /data/run_001 \
  --metadata metadata.csv \
  --report-json report.json \
  --report-markdown report.md \
  --report-html report.html
```

## Batch Validation

```bash
meerqat batch-validate /data/run_001 /data/run_002 --report-json batch.json
```

## Advisory Mode

Use the built-in lightweight local preset:

```bash
meerqat validate /data/run_001 --advisory --offline
```

Use an Instructor-compatible local `llama.cpp` server:

```bash
meerqat validate /data/run_001 \
  --advisory \
  --llm-provider instructor \
  --llm-base-url http://127.0.0.1:8000/v1
```
