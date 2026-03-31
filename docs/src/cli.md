# CLI

## Deterministic First

Every CLI command runs deterministic validation first. That deterministic pass
produces the real issues, report status, and exit code.

MeerQat runs the LLM review after the deterministic report already exists.
`--advisory` remains as a compatibility alias. MeerQat prefers the Instructor path and falls back to
LangChain when Instructor is unavailable.

The default LLM base URL is local: `http://127.0.0.1:8000/v1`. `--offline`
is off by default and only applies when you pass it or set it in config.
MeerQat will try to start a local `llama.cpp` server at that endpoint when
the LLM review is enabled and nothing is already listening there.

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

## LLM Review

The LLM review does not replace validation. It uses the deterministic report as
input and adds hints plus suspected hidden issues such as likely root causes,
naming-pattern observations, config suggestions, and filetree/content risks.

Use the built-in lightweight local preset with the LangChain fallback path:

```bash
meerqat validate /data/run_001 --offline
```

Use an Instructor-compatible local `llama.cpp` server, which is the preferred path:

```bash
meerqat validate /data/run_001 \
  --llm-provider instructor \
  --llm-base-url http://127.0.0.1:8000/v1
```
