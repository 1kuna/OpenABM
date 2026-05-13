# OpenABM Implementation Progress

This document tracks implementation work against the local implementation spec
without editing the spec itself. It is intentionally phase-oriented so future
work can resume from concrete state instead of memory.

## Guardrails

- `openabm_implementation_spec.md` is the read-only SSOT.
- Local LLM calls are now allowed through LM Studio when semantic judgment is
  required.
- The current local model lane is `qwen3.5-9b-mlx` through LM Studio for this
  implementation pass.
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
- Add an agent orchestration direction record that favors OpenABM-owned tool
  contracts first, then evaluating LangGraph/Deep Agents or Pi-style cores
  instead of reinventing a deep-agent runtime.
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
- Verified a live LM Studio similarity canary with `qwen3.5-9b-mlx`; the
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
- Larger calibration studies against model outputs.

Done:

- Added disabled chat/structured/embedding provider adapters that fail closed.
- Added OpenAI-compatible local model provider with strict JSON parsing,
  bounded repair, no generation timeout, and a minimum 32k context guard.
- Added optional structured-output token caps for small JSON tasks to prevent
  runaway completions without adding a timeout or reducing model context.
- Added OpenAI-compatible tool-call parsing to the local provider so semantic
  workers can prefer typed tool requests over prose-shaped JSON.
- Added judge output validation for verdicts and span citations.
- Added model-backed rubric judge execution with context packets, preserved-span
  citation validation, provider/model metadata, score persistence, and `/v1`
  API coverage.
- Added judge registry storage/API for draft judges and immutable judge
  versions, including explicit-definition drafts and local-model natural
  language judge drafting that always creates human review work before use.
- Verified a live LM Studio structured-output canary against
  `qwen3.5-9b-mlx`; output was valid JSON, unrepaired, and reported
  reasoning-token usage.
- Verified a live LM Studio judge-draft canary against `qwen3.5-9b-mlx`;
  after adding structured-output length control, the model returned a draft
  rubric judge as valid unrepaired JSON with 4,605 total tokens and 4,120
  reasoning tokens.
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

- Command and HTTP runner execution beyond the local in-process runner.
- Large-scale eval calibration and trend analysis beyond per-run comparison.

Done:

- Added dataset creation API and storage support.
- Added trace-to-dataset example API preserving source trace/root-span
  provenance and labels.
- Added OpenAPI contract entries and integration coverage for the trace-to-
  dataset path.
- Added persisted local offline eval runs/results and `make demo-eval`, which
  seeds fixtures, creates a dataset from a trace, runs one deterministic judge,
  and records the eval artifact without LLM calls.
- Added `/v1/evals/run`, `/v1/evals/{eval_run_id}`, and `/v1/evals/compare`.
  The local runner can execute deterministic rule judges and rubric judges via
  the configured local model provider, then compare pass-rate, average-score,
  failure set, invalid-output, latency, and token deltas.

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
- Added automation definitions, automation run records, idempotency-key replay
  protection, deterministic condition evaluation over trace context, and action
  execution for dataset additions, review-task creation, and preview-only
  notifications.
- Added notification/workflow target registry storage/API using secret refs
  instead of hardcoded destinations.
- Added trajectory assertion evaluator coverage for required/forbidden tools,
  retrieval sources, behavior IDs, span types, cost, duration, retry count, and
  grounding evidence counts.
- Added draft behavior creation, deterministic rule/manual-label/judge detector
  backtesting, persisted backtest-positive behavior matches, and review-task
  creation for candidate positives.

## Phase 7: Prompt Registry, MCP, And Investigation Agent

Status: in progress

Target for this pass:

- Prompt versions, deterministic commit IDs, tags, rendering, and diffs.
- MCP tool schemas and deterministic read/draft tool handlers.

LLM-dependent deferrals:

- Full vendor-specific ChatOps connectors.
- Rich semantic documentation search beyond the deterministic public-docs
  search endpoint.

Done:

- Added prompt commit hashing, deterministic variable rendering, secret
  interpolation rejection, and text diff helper.
- Added prompt registry storage/API lifecycle: prompt definitions, immutable
  prompt versions, content-addressed commit IDs, mutable tag pointers with tag
  events, deterministic render, and version diff.
- Added agent runtime configuration registry storage/API lifecycle: config
  records, immutable config versions, content-addressed commit IDs, and
  deterministic config diffs.
- Added MCP tool contract registry covering all required tool names, including
  side-effect and confirmation metadata.
- Added agent context pack generation and persistence with model-backed
  summaries, citation validation, deterministic fallback when a model provider is
  unavailable, and `/v1/context-packs` API coverage.
- Added model-assisted investigation drafts for cited root-cause hypotheses,
  candidate behaviors, rubric drafts, uncertainty, and next actions, with
  citation filtering before model output becomes canonical.
- Added grounding check storage/API for explicit claims, deterministic trace-span
  evidence matching, unsupported-claim review task creation, and export coverage.
- Added optional local-model grounding claim extraction through model tool
  calls; deterministic exact-evidence matching still decides support status, and
  model extraction metadata persists with the grounding check.
- Verified a live LM Studio grounding canary against `qwen3.5-9b-mlx`: the
  model emitted a tool call with `delivered` and `refund policy approved`, the
  API persisted the extraction, and deterministic validation marked `delivered`
  supported while keeping the policy claim in review. A richer contradiction
  extraction prompt caused the 9B model to spend 8,191 reasoning tokens without
  emitting a tool call, so semantic contradiction adjudication remains a later,
  separately scoped tool.
- Added passive novelty detection runs that group unknown error/tool signatures,
  persist candidate outputs, and create review tasks for behavior candidates.
- Added optional local-model semantic grouping for novelty runs through tool
  calls. The model can name and merge deterministic signature candidates, but
  trace membership is validated against source candidates before persistence.
- Verified a live LM Studio novelty canary against `qwen3.5-9b-mlx`: the model
  emitted a tool call, named the fixture candidate `Tool Selection Error`, and
  OpenABM persisted validated membership back to `error_wrong_tool` /
  `trace_wrong_tool` with model metadata.
- Added screenshot issue intake endpoint that stores screenshot-origin issues and
  returns candidate seed traces with explicit match reasons.
- Added ChatOps-style investigation endpoint that creates canonical issue and
  investigation artifacts without binding the product to a chat vendor.
- Verified a live LM Studio investigation canary with `qwen3.5-9b-mlx`; the
  prompt revision produced a cited root cause, behavior draft, and rubric draft
  as valid unrepaired JSON with reasoning-token usage.
- Added human review task APIs and connected investigation root-cause/behavior
  candidates to the review queue instead of treating model drafts as active
  product decisions.
- Added a live Judge workspace in the web app with judge listing, immutable
  version inspection, calibration summaries, configurable promotion gates, and
  promotion results wired to `/v1/judges`.
- Expanded the MCP tool contract registry to match the v2 required tool list,
  added resource templates, and added API-backed deterministic handlers for the
  implemented read/draft paths with explicit unsupported responses for gaps.
- Connected MCP handlers for prompt list/get/commit and agent config
  list/get/compare now that those APIs exist.
- Connected MCP handlers for automation list/get now that automation APIs exist.
- Connected the remaining MCP placeholders for judge list/get/draft, eval run
  and compare, and docs search to API-backed routes.
- Added deterministic `/v1/docs/search` over committed public docs and schemas;
  the ignored implementation spec is intentionally excluded from search results.
- Added web UI sections for judge runtime, behavior monitoring, datasets/evals,
  prompt registry, MCP, and ops status so unfinished surfaces are visible
  without pretending LLM-dependent capabilities exist.
- Updated the web scaffold statuses and module summaries so judge registry,
  local model-backed rubric drafting, eval run/compare, MCP routing, and
  retention/export/delete state reflect current implementation instead of stale
  deferred labels.
- Added a live Review Queue workspace in the web app with status/type filters,
  task selection, evidence IDs, notes, and accept / needs-evidence / reject
  decision actions wired to `/v1/review-tasks`.

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
- Added retention policy records, project export bundles with per-section SHA256
  manifests, included-classification summaries, and trace tombstone/delete flow
  that removes spans/scores/behavior matches/search rows while preserving an
  audit-friendly trace tombstone.
- Added retention policy dry-run/apply execution for trace TTL rules so cleanup
  candidates can be reviewed before tombstoning, with audit records for planned
  or applied runs.

## Phase 9: Real-World Pilot And Revisit Decisions

Status: not started

Blocked:

- Requires real pilot usage and owner direction after the scaffold is runnable.

## Running Notes

- Use `SPEC_EDIT_SUGGESTIONS.md` for any recommended spec changes.
- Keep the spec itself unmodified.

## Acceptance Pass: 2026-05-12

Verified after the latest implementation slices:

- `make lint && make test`: passed, 39 tests after the judge/eval/docs MCP
  slice.
- `npm --prefix apps/web run build`: passed.
- Browser QA captured desktop Judges and mobile MCP screenshots under
  `artifacts/ui-qa/`; the updated status text fits at both checked widths.
- `make demo-eval`: passed with one deterministic eval result, zero LLM calls,
  and one expected fail verdict for the wrong-tool fixture.
- MCP stdio smoke: `tools/list` returned 35 tools and
  `resources/templates/list` returned 14 resource templates.
- Live LM Studio canaries completed for structured rubric output, semantic trace
  similarity, and investigation drafting with `openabm-qwen35-9b`.
- Git status after final validation was clean against `origin/main`.

Known remaining gaps before calling the whole spec complete:

- Prompt registry and agent runtime configuration registry now have storage/API
  and MCP-backed lifecycle flows, but the web UI still needs full version
  history, tag movement, and eval-linked comparison views.
- Judge registry, model-backed judge drafting, local eval launch, eval
  comparison, judge calibration reporting, promotion gates, and the judge
  lifecycle workspace now exist; richer eval-linked comparison screens are still
  pending.
- Automation definitions and local run execution include deterministic
  conditions, idempotency, preview notifications, review-task actions, and
  cooldown skips, bounded retries, and dead-letter action visibility; real
  external notification delivery and compensation handlers still need
  implementation beyond preview/audit mode.
- Passive novelty detection has deterministic exact-signature grouping plus
  optional model semantic grouping/naming with validated membership; larger
  clustering and embedding-backed discovery remain future work.
- Grounding/fabricated-value checks support explicit, deterministically split,
  and model-extracted claims with exact evidence matching; broader semantic
  contradiction adjudication remains review-gated rather than automatic.
- Screenshot issue intake and ChatOps-style issue/investigation creation exist;
  real OCR, attachment text extraction, and vendor-specific chat connectors are
  still future integration work.
- UI pages are useful scaffolds rather than full spec-complete workspaces for
  behavior detail, automation builder, impact report, prompt registry, and agent
  configuration history.
- Production-grade auth/session/API-key management, secret vault integration,
  and scheduled retention workers remain beyond the local reference scaffold.

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
- Added `/v1/behaviors` create/get/backtest paths plus `/v1/review-tasks`
  list/create/update paths so behavior candidates and root-cause candidates have
  auditable review gates.
- Added stable `/v1` get/list paths for sessions, datasets, issues,
  investigations, impact reports, and context packs so MCP and UI clients can
  link back to canonical artifacts.
- Added retention/export/delete scaffolds: retention policies, project export
  manifests with hashes, and trace tombstones with derived-data cleanup.
- Added `/v1/retention-policies/{retention_policy_id}/apply` for retention
  dry-runs and trace TTL cleanup application.
- Added `/v1/prompts` and `/v1/agent-configs` lifecycle paths with immutable
  version commits and diff/render/compare helpers.
- Added `/v1/notification-targets` and `/v1/automations` lifecycle/run paths
  with deterministic condition evaluation, idempotency, review-task actions, and
  preview-only notification action audits.
- Notification target creation now rejects plaintext config blobs and validates
  `config_secret_refs`; active targets require at least one secret ref, while
  paused placeholders can be created without mounting secrets.
- Added persisted automation cooldown checks keyed by configured scope so
  repeated matching runs can be skipped before action execution without losing
  the condition/cooldown audit record.
- Added bounded retry attempts and visible dead-letter action results for
  automation actions, including configured `on_failure: continue` behavior for
  partial-failure runs.
- Added `/v1/grounding-checks` and `/v1/novelty-runs` paths for reviewable
  fabricated-value checks and passive behavior candidate discovery.
- Added model-assisted `/v1/grounding-checks` claim extraction with persisted
  model metadata and deterministic support validation.
- Captured a proposed long-term orchestration direction in
  `docs/decisions/0006-agent-orchestration-framework.md`: evaluate LangGraph /
  Deep Agents or Pi-style cores after OpenABM's primitive local tool-call
  boundary is proven.
- Added `/v1/issues/from-screenshot` and `/v1/chatops/investigate` entrypoints
  for weak human reports and chat-originated investigations.
- Added `/v1/judges`, `/v1/judges/drafts`, `/v1/evals/run`,
  `/v1/evals/compare`, and `/v1/docs/search`, then wired the corresponding MCP
  tool handlers so the agent surface no longer reports those paths as
  unsupported.
- Added `/v1/judges/{judge_id}/calibration-report` so judge readiness can be
  inspected from eval score history, invalid-output rate, latency/token
  summaries, drift-by-eval-run, and human review labels. The report resolves
  registry judge IDs and immutable-version definition IDs as aliases.
- Added `/v1/judges/{judge_id}/promote` so judges move from draft to active
  only after calibration score, invalid-output, open-review, and accepted-review
  gates pass.
- Added an Issues/Investigations scaffold view in the web app so the v2 surface
  is visible without pretending the LLM-backed pieces are ready.
