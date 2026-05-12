# OpenABM Implementation Progress

This document tracks implementation work against the local implementation spec
without editing the spec itself. It is intentionally phase-oriented so future
work can resume from concrete state instead of memory.

## Guardrails

- `openabm_implementation_spec.md` is the read-only SSOT.
- No local or cloud LLM/model calls during this scaffold pass.
- LLM-dependent features are deferred and noted here.
- Commit coherent slices as the scaffold becomes runnable.
- Public artifacts must use original OpenABM language, schemas, examples, and UI.

## Phase 0: Product, Legal, And Decision Infrastructure

Status: in progress

Done:

- Public repo exists at `https://github.com/1kuna/OpenABM`.
- Implementation spec is gitignored and protected by a local pre-commit hook.
- Public README framing matches Open Agent Behavior Monitoring.

In this pass:

- Add contribution/security/code-of-conduct docs.
- Add decision record template.
- Add starter decision records for storage, model runtime, search, code sandbox,
  and local stack runner.
- Leave final license choice pending owner review rather than silently committing
  legal terms.

Skipped or deferred:

- Final license file until Zach confirms the license decision.

## Phase 1: Contracts And Fixtures

Status: in progress

Target for this pass:

- Machine-readable JSON Schemas under `packages/shared-types/schemas/`.
- OpenAPI skeleton under `packages/shared-types/openapi/`.
- Synthetic fixture corpus and reconstruction expectations.
- Contract tests that validate fixtures and schemas.

Done:

- Added required schema files for traces, spans, events, payloads, scores,
  judges, behaviors, automations, datasets, evals, prompts, secrets, and MCP
  request/response envelopes.
- Added operation-level OpenAPI skeleton for health, ingest, query, search,
  scores, and behavior list APIs.
- Added initial synthetic trace fixtures for happy path, wrong tool, missing
  parent, and clock skew cases.
- Added contract tests and verified them with `make contracts`.

LLM-dependent deferrals:

- Model-backed fixture expected prose remains rubric-style, not exact generated
  text.

## Phase 2: SDK, Ingest, And Storage Slice

Status: in progress

Target for this pass:

- Python SDK manual spans, nested spans, decorators, redaction hooks, offline
  JSONL export, and HTTP export.
- Local API ingest endpoints with schema validation and partial-success batch
  handling.
- SQLite reference storage with migrations, idempotent ingest, trace list API,
  payload object metadata, and local reset/seed workflow.

LLM-dependent deferrals:

- None expected for the deterministic SDK/ingest/storage path.

Done:

- Added SQLite migration for projects, API keys, traces, spans, payloads,
  scores, behaviors, datasets, audit logs, ingest diagnostics, and FTS search.
- Added FastAPI reference API with health/readiness/metrics, ingest endpoints,
  partial-success batch ingest, trace/project/session query endpoints, score and
  behavior list endpoints, and fail-closed similarity search.
- Added local dev API-key auth mode using `OPENABM_DEV_API_KEY`.
- Added Python SDK with manual spans, sync/async `observe`, nested context,
  error events, payload capture controls, redaction hooks, offline JSONL export,
  in-memory export, and HTTP batch export.
- Added CLI commands for database initialization, fixture seeding, and status.
- Verified `make test`, `make lint`, `make init-db`, and `make seed-fixtures`.

## Phase 3: Trace Explorer And Reconstruction

Status: in progress

Target for this pass:

- Deterministic reconstruction algorithm and fixtures.
- Trace list and trace detail UI scaffold.
- Payload state, errors/events, score/behavior overlays, and malformed trace
  warnings.

LLM-dependent deferrals:

- Similar-trace semantic search is deferred unless backed by deterministic
  placeholder behavior clearly marked as non-semantic.

Done:

- Added deterministic trace reconstruction for roots, nested spans, missing
  parents, incomplete spans, payload states, timeline ordering, and clock-skew
  warnings.
- Added reconstruction unit tests for missing-parent and clock-skew fixtures.

## Phase 4: Model Runtime And Judge Runtime

Status: planned

Target for this pass:

- Provider adapter interfaces.
- Local-only model mode that fails closed when calls are disabled.
- Structured-output validators.
- Deterministic rule judges.
- Development-only code judge sandbox scaffold where isolation limits are
  explicit.

LLM-dependent deferrals:

- Rubric judges that call a model.
- Trace summarization by model.
- Embeddings and reranking.
- Judge calibration against model outputs.

## Phase 5: Datasets And Offline Evals

Status: planned

Target for this pass:

- Dataset definitions, examples, versions, and provenance links.
- In-process, command, and HTTP runner contracts.
- Baseline comparison data structures and deterministic comparison logic.

LLM-dependent deferrals:

- Model-backed judge scoring during evals.

## Phase 6: Behaviors And Automations

Status: planned

Target for this pass:

- Manual labels, rule detectors, behavior backtest scaffold.
- Automation condition grammar, idempotency, cooldowns, retries, and audit logs.

LLM-dependent deferrals:

- Cluster/embedding behavior discovery.
- Judge-backed behavior detector execution when the judge requires a model.

## Phase 7: Prompt Registry, MCP, And Investigation Agent

Status: planned

Target for this pass:

- Prompt versions, deterministic commit IDs, tags, rendering, and diffs.
- MCP tool schemas and deterministic read/draft tool handlers.

LLM-dependent deferrals:

- Investigation chat agent.
- Drafting judges from natural-language user requests.

## Phase 8: Security, Privacy, And Operations Hardening

Status: planned

Target for this pass:

- API key scopes, role matrix helpers, audit log model, retention/delete/export
  scaffolds, health/readiness/metrics endpoints, and admin status data.

LLM-dependent deferrals:

- None expected for deterministic hardening scaffolds.

## Phase 9: Real-World Pilot And Revisit Decisions

Status: not started

Blocked:

- Requires real pilot usage and owner direction after the scaffold is runnable.

## Running Notes

- Use `SPEC_EDIT_SUGGESTIONS.md` for any recommended spec changes.
- Keep the spec itself unmodified.
