# OpenABM

OpenABM is a self-hostable, open-source platform for monitoring, evaluating,
debugging, and improving production AI agents from trace data.

The implementation spec is intentionally kept local-only and is not committed to
the public repository. Public contracts, examples, and implementation decisions
live in this repo as original OpenABM artifacts.

## Current Local Reference

- Contract-first schemas and OpenAPI documents.
- Python tracing SDK with offline JSONL and HTTP export modes.
- Local API, SQLite/filesystem storage, retention worker, CLI, and MCP server.
- Operational trace explorer and review UI for the local reference workflow.
- Governance and decision-record workflow for implementation choices.
- Docker Compose production-reference deployment contract.

## Non-Goals

- OpenABM is not a vendor clone.
- OpenABM is not a generic final-answer-only eval dashboard.
- OpenABM does not require cloud model calls in local development.

## Development

The local reference implementation can run without local or hosted LLMs, and it
also supports explicitly configured OpenAI-compatible local providers for
model-backed judges, summarization, embeddings, behavior discovery, grounding,
and investigation assistance.

See `IMPLEMENTATION_PROGRESS.md` for the current build status and deferred
LLM-dependent work.

For self-hosted reference deployment, see `docs/deployment.md`.
