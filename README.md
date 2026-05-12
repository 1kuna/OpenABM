# OpenABM

OpenABM is a self-hostable, open-source platform for monitoring, evaluating,
debugging, and improving production AI agents from trace data.

The implementation spec is intentionally kept local-only and is not committed to
the public repository. Public contracts, examples, and implementation decisions
live in this repo as original OpenABM artifacts.

## Current Scaffold

- Contract-first schemas and OpenAPI documents.
- Python tracing SDK with offline JSONL and HTTP export modes.
- Local API, storage, worker, CLI, and MCP scaffolds.
- Operational trace explorer UI scaffold.
- Governance and decision-record workflow for implementation choices.

## Non-Goals

- OpenABM is not a vendor clone.
- OpenABM is not a generic final-answer-only eval dashboard.
- OpenABM does not require cloud model calls in local development.

## Development

The local reference implementation is designed to run without local or hosted
LLMs unless model-backed judges, summarization, embeddings, behavior discovery,
or investigation chat are explicitly enabled later.

See `IMPLEMENTATION_PROGRESS.md` for the current build status and deferred
LLM-dependent work.
