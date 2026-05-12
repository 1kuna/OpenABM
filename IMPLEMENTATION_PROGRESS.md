# OpenABM Implementation Progress

This document tracks implementation work against the local implementation spec
without editing the spec itself. It is intentionally phase-oriented so future
work can resume from concrete state instead of memory.

## Guardrails

- `openabm_implementation_spec.md` is the read-only SSOT.
- Local LLM calls are now allowed through LM Studio when semantic judgment is
  required.
- The current local model lane is `qwen3.5-9b-mlx`, loaded through LM Studio as
  `openabm-qwen35-9b` for this implementation pass.
- Do not disable reasoning, do not apply generation timeouts, and do not use
  less than 32k context for model-backed work.
- Defer to heavier models only after prompt/runtime tinkering shows an obvious
  model capability gap.
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

- Embedding-index search remains configurable future work; current semantic
  trace similarity uses the configured local chat model with cited candidate
  span evidence.

Done:

- Added deterministic trace reconstruction for roots, nested spans, missing
  parents, incomplete spans, payload states, timeline ordering, and clock-skew
  warnings.
- Added reconstruction unit tests for missing-parent and clock-skew fixtures.
- Added React/Vite trace explorer UI with API connection controls, trace table,
  status filtering, full-text search trigger, trace detail, timeline, payload
  state summary, span inspector, and scaffolded actions.
- Replaced the old fail-closed similar-trace stub with model-backed semantic
  similarity ranking over candidate traces, preserving cited candidate span
  evidence and model metadata.
- Verified a live LM Studio similarity canary with `openabm-qwen35-9b`; the
  model returned a cited candidate match, unrepaired structured output, and
  reasoning-token usage.
- Verified the web app with `npm --prefix apps/web run build` and headless
  Chrome screenshots at desktop and mobile widths.

## Phase 4: Model Runtime And Judge Runtime

Status: in progress

Target for this pass:

- Provider adapter interfaces.
- Local-only model mode that fails closed when calls are disabled.
- Structured-output validators.
- Deterministic rule judges.
- Development-only code judge sandbox scaffold where isolation limits are
  explicit.

LLM-dependent deferrals:

- Trace summarization by model.
- Embeddings and reranking.
- Judge calibration against model outputs.

Done:

- Added disabled chat/structured/embedding provider adapters that fail closed.
- Added OpenAI-compatible local model provider with strict JSON parsing,
  bounded repair, no generation timeout, and a minimum 32k context guard.
- Added judge output validation for verdicts and span citations.
- Added model-backed rubric judge execution with context packets, preserved-span
  citation validation, provider/model metadata, score persistence, and `/v1`
  API coverage.
- Verified a live LM Studio structured-output canary against
  `openabm-qwen35-9b`; output was valid JSON, unrepaired, and reported
  reasoning-token usage.
- Added deterministic rule judge scaffold.
- Added development-only code judge sandbox with scrubbed environment,
  temporary inputs/outputs, timeout handling, stdout/stderr capture, and explicit
  `dev_only` isolation status.
- Added tests for disabled model mode, citation validation, deterministic rule
  judge execution, and code judge environment scrubbing.

## Phase 5: Datasets And Offline Evals

Status: in progress

Target for this pass:

- Dataset definitions, examples, versions, and provenance links.
- In-process, command, and HTTP runner contracts.
- Baseline comparison data structures and deterministic comparison logic.

LLM-dependent deferrals:

- Model-backed judge scoring during evals.

Done:

- Added dataset creation API and storage support.
- Added trace-to-dataset example API preserving source trace/root-span
  provenance and labels.
- Added OpenAPI contract entries and integration coverage for the trace-to-
  dataset path.
- Added persisted local offline eval runs/results and `make demo-eval`, which
  seeds fixtures, creates a dataset from a trace, runs one deterministic judge,
  and records the eval artifact without LLM calls.

## Phase 6: Behaviors And Automations

Status: in progress

Target for this pass:

- Manual labels, rule detectors, behavior backtest scaffold.
- Automation condition grammar, idempotency, cooldowns, retries, and audit logs.

LLM-dependent deferrals:

- Cluster/embedding behavior discovery.
- Judge-backed behavior detector execution when the judge requires a model.

Done:

- Added deterministic condition grammar evaluator for automation/rule-detector
  style conditions with nested groups and the spec's core operators.
- Added trajectory assertion evaluator coverage for required/forbidden tools,
  retrieval sources, behavior IDs, span types, cost, duration, retry count, and
  grounding evidence counts.

## Phase 7: Prompt Registry, MCP, And Investigation Agent

Status: in progress

Target for this pass:

- Prompt versions, deterministic commit IDs, tags, rendering, and diffs.
- MCP tool schemas and deterministic read/draft tool handlers.

LLM-dependent deferrals:

- Investigation chat agent.
- Drafting judges from natural-language user requests.

Done:

- Added prompt commit hashing, deterministic variable rendering, secret
  interpolation rejection, and text diff helper.
- Added MCP tool contract registry covering all required tool names, including
  side-effect and confirmation metadata.
- Added agent context pack generation and persistence with model-backed
  summaries, citation validation, deterministic fallback when a model provider is
  unavailable, and `/v1/context-packs` API coverage.
- Added model-assisted investigation drafts for cited root-cause hypotheses,
  candidate behaviors, rubric drafts, uncertainty, and next actions, with
  citation filtering before model output becomes canonical.
- Verified a live LM Studio investigation canary with `openabm-qwen35-9b`; the
  prompt revision produced a cited root cause, behavior draft, and rubric draft
  as valid unrepaired JSON with reasoning-token usage.
- Added web UI sections for judge runtime, behavior monitoring, datasets/evals,
  prompt registry, MCP, and ops status so unfinished surfaces are visible
  without pretending LLM-dependent capabilities exist.

## Phase 8: Security, Privacy, And Operations Hardening

Status: in progress

Target for this pass:

- API key scopes, role matrix helpers, audit log model, retention/delete/export
  scaffolds, health/readiness/metrics endpoints, and admin status data.
- Data classification policy and deterministic redaction helpers for payload
  handling.

LLM-dependent deferrals:

- None expected for deterministic hardening scaffolds.

Done:

- Added data classification policy storage/API, deterministic payload
  classification, and redaction when payload classification exceeds caller
  allowance.

## Phase 9: Real-World Pilot And Revisit Decisions

Status: not started

Blocked:

- Requires real pilot usage and owner direction after the scaffold is runnable.

## Running Notes

- Use `SPEC_EDIT_SUGGESTIONS.md` for any recommended spec changes.
- Keep the spec itself unmodified.

## Spec V2 Delta Incorporated

Status: in progress

Compared with the original spec, the temporary v2 spec revision added these
implementation targets. The v2 contents have since replaced
`openabm_implementation_spec.md`, and the spec remains ignored:

- Public API prefix convention: stable external APIs move to `/v1/...`; web-only
  unstable APIs belong under `/api/internal/...`.
- Business-facing trace dimensions for filtering/grouping impact by account,
  customer tier, task type, workflow, region, plan, ticket/case, and other
  generic dimensions.
- Deployment and code context entities so traces can preserve service version,
  revision, branch, build/deploy IDs, function/file/line, source links, and
  stack-frame hashes.
- Saved searches as reusable product objects for behaviors, automations,
  impact reports, datasets, and investigation inputs.
- Human review queue for judge outputs, behavior candidates, grounding checks,
  affected entities, and root-cause candidates.
- Notification/workflow target registry using secret refs instead of hardcoded
  vendor destinations.
- Trajectory-level eval assertions over tool calls, retrieval sources,
  behaviors, span patterns, cost, latency, retries, and grounding evidence.
- Agent runtime configuration registry for immutable prompt/tool/retrieval/
  memory/guardrail/routing/workflow/runtime versions.
- Issue-led investigation workflow, issue entity, screenshot intake, auditable
  investigation runs, impact reports, differential root-cause analysis, context
  packs, passive novelty detection, ChatOps surface, grounding/fabrication
  checks, and affected-entity remediation tracking.
- Trace detail UI modes for conversation/thread, tool sequence, and code/error
  views, plus issue/investigation and impact-report pages.
- Data classification policy covering payloads, dimensions, business context,
  code snippets, screenshots, context packs, exports, MCP, and ChatOps.
- First runnable slice acceptance gate: local stack, SDK manual span, batch
  ingest, trace list/detail, one rubric judge, one dataset from trace, and one
  offline eval.

Immediate deterministic implementation response:

- Add `/v1` public API routes while keeping any temporary `/api` compatibility
  only as non-contract local convenience.
- Add schemas and storage tables for v2 metadata and investigation entities.
- Implement saved searches, dimensions, issue intake, deterministic
  investigation scaffolding, impact report scaffolding, data classification, and
  trajectory assertion evaluation without using LLMs.
- Keep model-backed screenshot extraction, semantic similarity, passive novelty,
  ChatOps answer generation, rubric judge generation, and claim extraction
  deferred until LLM/model work is explicitly enabled.

Implemented in this pass:

- Replaced the original ignored spec file with the v2 contents and kept it out
  of git.
- Switched public API contracts, SDK export, web client, and integration tests
  to `/v1/...`.
- Added v2 storage tables and JSON schemas for dimensions, saved searches,
  review/notification/classification/config entities, issues, investigations,
  impact reports, context packs, grounding checks, and novelty runs.
- Added saved search, trace dimension, issue, investigation, impact report, and
  data classification API/storage scaffolds.
- Added deterministic impact report generation from trace search results and
  trace dimensions, with LLM-only narrative/root-cause work explicitly marked as
  deferred in the run result.
- Added model-assisted investigation output for cited root-cause hypotheses,
  behavior drafts, rubric drafts, uncertainty, and recommended next actions;
  citation filters prevent invented trace/span IDs from becoming canonical, and
  the live 9B prompt was tightened after the first canary skipped behavior
  drafts.
- Added an Issues/Investigations scaffold view in the web app so the v2 surface
  is visible without pretending the LLM-backed pieces are ready.
