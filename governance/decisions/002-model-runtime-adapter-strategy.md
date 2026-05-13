# DR-002: Model Runtime Adapter Strategy

Status: accepted-local-reference

Date: 2026-05-12
Updated: 2026-05-13

## Context

The model runtime powers rubric judges, summarization, embeddings, behavior
suggestions, grounding checks, passive discovery, and investigation assistance.
The first scaffold pass avoided LLM calls, but Zach enabled local model
execution on 2026-05-13 with LM Studio as the initial runtime lane.

## Contract

The implementation must expose provider adapters, health checks, structured
output validation, local-only mode, and fail-closed behavior when model calls
are disabled.

## Decision

Use provider adapters as the stable contract. Keep the disabled provider as the
fail-closed local-only mode, and use OpenAI-compatible local providers as the
first runnable reference implementation for:

- chat and structured/tool-call completions through LM Studio or another
  OpenAI-compatible local server;
- embedding generation through an OpenAI-compatible `/embeddings` endpoint;
- visible provider health, usage metadata, validation failures, and repair
  attempts.

The reference implementation must not make the model the source of truth for
mechanical guarantees. Model calls may perform semantic extraction,
classification, grouping, ranking, summarization, and draft generation, while
OpenABM code validates schemas, citations, provenance, review gates, and audit
records.

For the active local lane, prefer correctness over speed: do not disable model
reasoning, do not impose generation timeouts, and do not reduce model context
below 32k for model-backed tasks unless the specific use case is explicitly
low-context.

## Evidence

- Unit tests prove disabled mode rejects model-backed work without network
  calls and exposes blocked status.
- Unit tests cover OpenAI-compatible structured output repair, tool calls, and
  embedding response parsing.
- Integration tests cover model-assisted investigation drafts, grounding claim
  extraction, contradiction adjudication, semantic similarity, embedding-index
  search, and novelty grouping with deterministic validation around model
  output.
- Live local canaries recorded in `IMPLEMENTATION_PROGRESS.md` verified
  `qwen3.5-9b-mlx` for structured/tool-call workflows and LM Studio embedding
  support for vector representations.

## Revisit Triggers

- Rubric judge, summarization, embedding, or investigation-agent acceptance
- tests fail because the local model cannot perform the semantic task after
  prompt/runtime tuning.
- A hosted or larger local model becomes necessary for quality-sensitive tasks.
- OpenAI-compatible local serving stops preserving tool-call, structured-output,
  context, or usage metadata required by OpenABM audit contracts.
