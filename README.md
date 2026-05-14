# OpenABM

OpenABM is a self-hostable, open-source platform for monitoring, evaluating,
debugging, and improving production AI agents from trace data.

The implementation spec is intentionally kept local-only and is not committed to
the public repository. Public contracts, examples, and implementation decisions
live in this repo as original OpenABM artifacts.

## Current Local Reference

- Contract-first schemas and OpenAPI documents.
- Python tracing SDK with offline JSONL, HTTP export, baggage propagation,
  integration wrapper contracts, and a default generic method/callable wrapper.
- Local API, SQLite/filesystem storage, retention worker, CLI, and MCP server.
- Operational trace explorer and review UI for the local reference workflow.
- Governance and decision-record workflow for implementation choices.
- Docker Compose production-reference deployment contract.
- Synthetic pilot lab for real-world-style local pressure testing.

## Non-Goals

- OpenABM is not a vendor clone.
- OpenABM is not a generic final-answer-only eval dashboard.
- OpenABM does not require cloud model calls in local development.

## License

OpenABM is released under the MIT License. See `LICENSE`.

## Development

The local reference implementation can run without local or hosted LLMs, and it
also supports explicitly configured OpenAI-compatible local providers for
model-backed judges, summarization, embeddings, behavior discovery, grounding,
and investigation assistance.

See `IMPLEMENTATION_PROGRESS.md` for the current build status and deferred
LLM-dependent work.

To deliberately test the local tool-calling lane against the configured model:

```bash
./scripts/openabm bench agent-flow-smoke
```

To run a synthetic real-world-style pilot across the local reference surfaces:

```bash
./scripts/openabm synthetic-pilot
```

To scale that into a synthetic company run across multiple workflows,
departments, days, healthy flows, and expected failure modes:

```bash
./scripts/openabm synthetic-pilot --company-simulation --company-trace-count 240
```

To run the larger deterministic battle-test profile with a spec evidence matrix:

```bash
./scripts/openabm synthetic-pilot --battle-test-profile
```

To have a local model generate fake customer-agent conversations and feed those
back through the same pilot surfaces alongside the company simulator:

```bash
./scripts/openabm synthetic-pilot \
  --company-simulation \
  --company-trace-count 120 \
  --generate-conversations \
  --generated-conversation-count 4 \
  --use-model \
  --max-model-cases 2 \
  --chat-model qwen3.6-35b-a3b
```

See `docs/synthetic-pilot.md` for the synthetic/real-pilot boundary and the
optional LM Studio/Qwen command, including the required 32k+ loaded context
check.

For self-hosted reference deployment, see `docs/deployment.md`.
