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
- Commit coherent slices as the implementation evolves.
- Public artifacts must use original OpenABM language, schemas, examples, and UI.
- Prefer mature open-source orchestration where it fits. LangGraph/Deep Agents
  are the likely long-term lane for deep-agent orchestration; Pi/pi-agent-core
  stays a candidate for thinner local-first tool-loop/streaming pieces. OpenABM
  contracts, evidence, provenance, and review gates remain the source of truth.

## Completion Audit: 2026-05-13

Scaffold-complete local surfaces:

- Core local product loop: SDK ingest, trace reconstruction/search/detail,
  judges, behaviors, datasets, evals, prompt/config provenance, issue-led
  investigation, impact reports, review tasks, MCP, and export/delete/retention
  paths are implemented with tests.
- Local model lane: LM Studio/OpenAI-compatible chat, structured/tool-call, and
  embedding providers are wired with disabled-mode fail-closed behavior,
  deterministic validation, live canary notes for `qwen3.5-9b-mlx`, and a
  configurable available-memory preflight guard for new local model calls.
- Agent orchestration lane: OpenABM owns the contracts/provenance/review gates;
  LangGraph is used as a thin investigation adapter, and MCP resources/tools now
  expose trace/eval/investigation context for deep-agent runners.
- Operations lane: API scopes/RBAC, local API keys, local sessions, invite
  outbox, encrypted secret refs, audit logs, retention worker, worker
  heartbeats, MCP observability, Docker Compose reference deployment, and admin
  status surfaces are in place.
- Decision-record lane: license selection, storage, search, model runtime,
  sandbox, local stack, orchestration, similarity experiments, and
  production-reference deployment now have explicit governance records with
  revisit triggers.

Remaining blockers or explicit non-local-reference work:

- Final license text still needs owner choice before adding a `LICENSE` file.
- Phase 9 real-world pilots, usability feedback, performance reports, and
  revisit decisions require real users/workloads.
- External IdP/OAuth, SMTP/vendor invite delivery, production secret-manager
  adapters, vendor-specific ChatOps connectors, production observability
  exporters, and external deployment supervision remain integration work beyond
  the local reference implementation.
- Real OCR/binary attachment parsing, production vector-store/ANN choices,
  broader clustering experiments, and deeper UI drilldowns remain future
  hardening.
- Any semantic task that the local 9B model cannot handle after prompt/runtime
  tuning should be deferred for a heavier model rather than replaced with
  brittle deterministic heuristics.

Current validation gate:

- Latest local gates: `make ci` and `make deploy-config-check` passed after the
  most recent implementation/doc slices.
- Latest pushed commits are being validated by GitHub Actions as each slice is
  pushed.

Prompt-to-artifact checklist:

| Requirement | Evidence | Status |
| --- | --- | --- |
| Preserve ignored implementation spec as SSOT | `.gitignore` excludes `openabm_implementation_spec.md`; progress doc records the guardrail; no spec file is staged or committed. | Complete |
| Make coherent commits as progress lands | `git log` shows focused slices for MCP confirmations/resources, LangGraph event provenance, root-cause comparison, model runtime ADR, completion audit, and decision records. | Complete |
| Document progress and blockers | This `IMPLEMENTATION_PROGRESS.md` tracks phases, completed slices, validation, blockers, and deferrals. | Complete |
| Use local LM Studio/qwen lane for semantic work | Model runtime ADR accepts OpenAI-compatible local providers; live canary notes cover `qwen3.5-9b-mlx`; settings/docs preserve no-timeout/high-context rules and `OPENABM_MODEL_MIN_AVAILABLE_MEMORY_MB`. | Complete for local reference |
| Prefer OSS orchestration over reinvention | `docs/decisions/0006-agent-orchestration-framework.md`; LangGraph investigation adapter in `apps/worker/src/openabm_worker/investigation_workflow.py`; MCP remains the audited tool boundary. | Complete for current local reference |
| Keep semantic judgment in model/runtime, mechanical guarantees in code | Grounding, investigation, novelty, and similarity flows persist model metadata while deterministic code validates schemas, citations, membership, review gates, and provenance. | Complete for implemented flows |
| Public API/data contracts exist | JSON Schemas in `packages/shared-types/schemas/`; OpenAPI in `packages/shared-types/openapi/openapi.json`; contract tests under `tests/contracts/`. | Complete |
| Adapter interfaces from spec section 41 exist | `apps/worker/src/openabm_worker/adapters.py` defines typed protocols for every listed adapter; unit tests assert the expected contract names and local provider conformance. | Complete |
| Core loop works end to end | Integration tests cover trace ingest/detail, judges, behavior/dataset/eval loop, MCP trace/context-pack access, and reported incident investigation acceptance. | Complete for local fixtures |
| Security/privacy/ops local reference exists | RBAC/API keys, sessions, invite outbox, encrypted secrets, retention/export/delete, worker heartbeats, MCP observability, ops status, and deployment contract are implemented. | Complete for local reference |
| Required decision records exist | Governance records now cover license boundary, storage, search, model runtime, sandbox, local stack, similarity experiments, production deployment, and orchestration. | Complete |
| Final license file | `governance/decisions/008-license-selection.md` records owner-review-required status. | Blocked on owner choice |
| Real-world pilot and revisit decisions | Phase 9 requires 5-10 pilots, performance/quality reports, and post-pilot revisits. | Blocked on real users/workloads |
| External integrations beyond local reference | External IdP/OAuth, SMTP/vendor invite delivery, production secret managers, vendor ChatOps, production observability exporters, and deployment supervision are adapter boundaries. | Deferred until concrete integration target |

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
- Add similarity-experiment and production-reference deployment decision
  records so the spec's required revisit/evidence gates are represented
  directly instead of only through adjacent search/local-stack records.
- Add a license-selection decision record that keeps the final `LICENSE` file
  owner-gated without leaving the legal decision untracked.
- Source-check the current LangGraph, Deep Agents, and Pi/pi-agent-core project
  surfaces before adding any orchestration dependency; refreshed this read on
  2026-05-13 after Zach clarified the OSS-first preference.
- Add GitHub CI scaffolding for Python contracts/runtime tests, web build,
  dependency review, and Dependabot update tracking, plus a local `make ci`
  target that runs lint, tests, OpenAPI JSON validation, docs link checks, and
  the web build.
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
- Expanded the golden fixture corpus to cover all section 38 minimum fixture
  names with synthetic, schema-valid traces, including escalation, looping,
  retrieval, hallucination, fabricated-value, unsupported numeric claim,
  partial/late/duplicate ingest, payload/privacy, offline eval, external
  feedback, issue/investigation/impact, and multi-root cases.
- Added contract tests and verified them with `make contracts`.
- Added a worker adapter contract module that turns the spec's conceptual
  adapter signatures for model, embedding, stores, indexes, queues, sandbox,
  eval, notification, SDK integration, investigation, impact, root-cause,
  context-pack, and grounding adapters into typed Python protocols.

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
- Tightened the Python SDK OpenTelemetry-compatible attribute mapping so every
  exported span carries `openabm.span_type` in addition to the top-level
  `span_type` field.
- Added explicit OpenTelemetry-style span `resource` preservation across the
  span envelope schema, Python SDK export, SQLite storage, and trace-detail
  reconstruction path.
- Added safe Python SDK baggage propagation helpers for cross-process
  trace/span continuation, preserving trace/span/session/user/project/
  environment/sampling/redaction handles without propagating prompts, outputs,
  or secrets.
- Added SDK partial span flush support; partial snapshots emit an
  `openabm.partial_flush` event that records whether the span was still open.
- Added Python SDK integration wrapper contracts and a registry so future
  package-specific instrumentation plugins must declare supported versions,
  hooks, captured metadata, payload/redaction behavior, known limitations,
  example code, and acceptance checks before registration.
- Added a default generic method/callable SDK integration plugin that wraps
  object methods or standalone callables with OpenABM spans while preserving the
  tracer's payload capture and redaction settings.
- Added SDK and API backpressure/sampling controls: deterministic SDK trace
  sampling metadata, SDK payload and model-stream event sampling with visible
  omission markers, bounded HTTP exporter buffering, server-side inline payload
  and event sampling, retryable low-priority batch backpressure, and always-keep
  preservation for error/high-priority/feedback/behavior/dataset-linked traces.
- Added SDK and ingest/storage support for top-level runtime provenance on
  traces: `prompt_version_id`, `agent_config_version_id`,
  `deployment_context_id`, and `tool_version_ids`. Trace detail and search now
  expose those identifiers explicitly instead of requiring clients to dig
  through opaque attributes.
- Expanded batch ingest so events, feedback, and payload metadata are processed
  through the same partial-success response contract as traces and spans.
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

- Persisted embedding-index search remains configurable future work; current
  semantic trace similarity can use either the configured local chat model with
  cited candidate span evidence or an OpenAI-compatible embedding model with
  deterministic cosine ranking.

Done:

- Added deterministic trace reconstruction for roots, nested spans, missing
  parents, incomplete spans, payload states, timeline ordering, and clock-skew
  warnings.
- Added reconstruction unit tests for missing-parent and clock-skew fixtures.
- Added React/Vite trace explorer UI with API connection controls, trace table,
  status filtering, full-text search trigger, trace detail, timeline, payload
  state summary, span inspector, and scaffolded actions.
- Added trace detail modes for span tree, timeline/waterfall, conversation/
  thread payloads, tool sequence, and code/error context views. These are
  derived from reconstructed spans, payload redaction states, events, and
  captured attributes without hardcoding semantic decisions.
- Added selectable spans across trace detail modes. The inspector now follows
  the selected span and shows span identity, parent/status/latency, input/output
  payloads with redaction state, events, and raw captured attributes.
- Added trace detail evidence panels for persisted scores, behavior matches, and
  dataset membership, plus an action that adds the selected trace to the
  currently selected or newly created dataset.
- Added `/v1/traces/{trace_id}/behavior-labels` and a trace-detail behavior
  labeling action. The action updates explicit trace behavior attributes and
  persists a confirmed behavior match with selected-span evidence.
- Added `/v1/traces/{trace_id}/assertions/check` and a trace-detail
  deterministic assertion action that evaluates captured spans without model
  calls, displays failures/observed values, and audits the check outcome.
- Wired trace-detail similar trace results and rubric judge execution into the
  UI. Similarity now renders model-ranked matches with evidence span IDs, and
  rubric runs append persisted score results back into the evidence panel.
- Updated `.env.example` so local model configuration names
  `OPENABM_CHAT_MODEL=qwen3.5-9b-mlx` and keeps model and judge context at the
  262k default instead of advertising a sub-32k token cap.
- Added trace-list saved search controls and a bulk dataset action that saves
  the current trace query, reapplies saved searches, creates datasets, and adds
  the visible trace result set as provenance-linked dataset examples.
- Added trace-list latency, token, cost, score-badge, and behavior-badge
  columns. Latency is derived from trace timestamps or explicit duration
  attributes; token/cost values come only from captured trace metadata or
  persisted score usage/cost records; behavior badges come from explicit trace
  behavior attributes or persisted behavior matches.
- Added `/v1/behavior-matches` so persisted behavior matches can be listed by
  project, trace, or behavior, and included behavior matches in project exports.
- Replaced the old fail-closed similar-trace stub with model-backed semantic
  similarity ranking over candidate traces, preserving cited candidate span
  evidence and model metadata.
- Added an OpenAI-compatible embedding provider plus an embedding-backed
  similar-trace representation. When `OPENABM_EMBEDDING_MODEL` is configured,
  `/v1/search/similar` can embed the source trace, candidate traces, and
  candidate spans, then rank candidates deterministically by cosine similarity
  while disclosing `embedding_similarity_v1`.
- Added a local SQLite-backed similarity index candidate with
  `/v1/similarity-index`, `/v1/similarity-index/rebuild`, representation
  version tracking, provider/model/dimension/source-hash metadata, trace/span
  vector persistence, and `embedding_index` search over stored vectors. This is
  a transparent local reference path, not a production vector-store choice.
- Added Operations UI coverage for similarity-index inspection and rebuild, plus
  trace-detail display of the representation version used for similar-trace
  results.
- Added optional similarity-index grouping for passive novelty runs. Deterministic
  exact-signature candidates can now be merged when their stored trace embeddings
  clear a configured cosine threshold, while promotion still flows through human
  behavior-candidate review.
- Verified a live LM Studio embedding canary with
  `text-embedding-nomic-embed-text-v1.5`: the local OpenAI-compatible
  `/embeddings` endpoint returned two 768-dimensional vectors through the new
  provider adapter with status `succeeded`.
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

- Richer model-authored trace summaries beyond cited context packs and
  deterministic context-packet summaries.
- Cross-encoder/reranking beyond the new embedding representation path.
- Larger calibration studies against model outputs.

Done:

- Added disabled chat/structured/embedding provider adapters that fail closed.
- Added OpenAI-compatible local model provider with strict JSON parsing,
  bounded repair, no generation timeout, and a minimum 32k context guard.
- Added a configurable available-memory preflight guard for OpenAI-compatible
  chat and embedding calls so local LM Studio/qwen work skips new generations
  when the host is already under memory pressure, without reducing context or
  adding generation timeouts.
- Added OpenAI-compatible embedding provider support for local/self-hosted
  `/embeddings` endpoints, with no generation timeout, provider metadata, usage
  passthrough, dimension validation, and fail-closed disabled mode when no
  embedding model is configured.
- Added optional structured-output token caps for small JSON tasks to prevent
  runaway completions without adding a timeout or reducing model context.
- Added OpenAI-compatible tool-call parsing to the local provider so semantic
  workers can prefer typed tool requests over prose-shaped JSON.
- Added `./scripts/openabm bench agent-flow-smoke`, a lightweight local-provider
  tool-call smoke that asks the configured model to call a typed investigation
  planning tool, validates the returned arguments, and reports context length,
  memory guard status, available memory, provider/model, usage, and timeout
  behavior.
- Expanded the agent-flow smoke's allowed OpenABM tool set beyond investigation
  search to include eval comparison plus prompt and agent-config registry
  inspection/commit tools, so local tool-call canaries can cover the
  improve-and-regress loop without executing side effects.
- Verified a live LM Studio agent-flow tool-call smoke against
  `qwen3.5-9b-mlx`; the model emitted one valid `record_agent_flow_plan` tool
  call using real OpenABM MCP tool names including `search_traces`,
  `start_investigation_run`, `run_judge`, `run_eval`, `compare_agent_configs`,
  `list_prompts`, and `get_prompt`, with 262144 context, memory guard `ready`,
  no generation timeout, 1297 total tokens, and 485 reasoning tokens. The ignored
  machine-readable result is under
  `artifacts/model-canaries/agent-flow-smoke-qwen35-9b-20260513.json`.
- Added judge output validation for verdicts and span citations.
- Aligned the `ScoreResult` JSON Schema with the spec's failure-reason
  contract, including validation that succeeded scores cannot carry a
  non-null failure reason.
- Persisted score `failure_reason` through the SQLite schema, migration
  compatibility path, judge outputs, rubric API responses, score list API, and
  eval result reads; invalid judge output now records `invalid_result`.
- Added model-backed rubric judge execution with context packets, preserved-span
  citation validation, provider/model metadata, score persistence, and `/v1`
  API coverage.
- Upgraded judge trace context packets to deterministic `ctx_2` packets with
  reproducible hashes, estimated token counts, payload/event summaries,
  truncation notes, omitted-span IDs, and provider metadata that records the
  packet hash and summary/truncation surface for audit.
- Added judge registry storage/API for draft judges and immutable judge
  versions, including explicit-definition drafts and local-model natural
  language judge drafting that always creates human review work before use.
- Added a web Judge Editor surface for metadata, rubric JSON editing,
  output-schema preview, test trace selection, persisted golden-example
  metadata, explicit draft creation, immutable version commits, and test-result
  display.
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
- Tightened the development code judge sandbox with standard-library import
  allowlisting, blocked network/process APIs, guarded temporary filesystem
  access, POSIX resource-limit attempts for CPU/memory, spec-shaped
  `status`/`failure_reason` outputs, and visible sandbox policy metadata.
- Added a reproducible local model runtime benchmark harness exposed as
  `./scripts/openabm bench model-runtime --fixtures golden --provider configured-provider`;
  it records provider/model/config hash, fixture version, structured-output
  validity, citation validity, judge accuracy, unsure/invalid/context-failure
  rates, latency, throughput, memory, token usage, and a promotion gate that
  blocks high invalid-output or citation-failure rates.
- Tightened the benchmark rubric contract after the expanded fixture corpus
  exposed prompt mismatches: the wrong-refund-tool judge now explicitly treats
  unrelated well-formed failure modes as pass cases for this narrow benchmark,
  uses `unsure` only for `incomplete` / `malformed` traces, and does not treat
  `error`, `timeout`, `unknown`, empty spans, or missing refund evidence as
  automatic uncertainty.
- Added tests for disabled model mode, citation validation, deterministic rule
  judge execution, benchmark quality/promotion gating, and code judge
  environment scrubbing.

## Phase 5: Datasets And Offline Evals

Status: in progress

Target for this pass:

- Dataset definitions, examples, versions, and provenance links.
- In-process, command, and HTTP runner contracts.
- Baseline comparison data structures and deterministic comparison logic.

LLM-dependent deferrals:

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
- Dataset examples now persist `expected_trace_assertions`; offline eval results
  store deterministic assertion results, summarize assertion pass/fail counts,
  and eval comparison reports new/fixed/unchanged assertion failures.
- Added `/v1/evals/run`, `/v1/evals/{eval_run_id}`, and `/v1/evals/compare`.
  The local runner can execute deterministic rule judges and rubric judges via
  the configured local model provider, then compare pass-rate, average-score,
  failure set, invalid-output, latency, and token deltas.
- Added command and HTTP endpoint eval runner execution contracts. Runners
  receive a JSON packet containing the dataset example plus source trace/spans,
  may return either an existing `offline_trace_id` or a new trace/span bundle,
  and OpenABM ingests returned offline traces before applying deterministic or
  rubric judges.
- Expanded the Eval Comparison UI with baseline/candidate selectors, pass and
  score deltas, invalid-output/cost/latency/token deltas, new/fixed/unchanged
  failure lists, and trace links back to source examples.
- Added eval-run runtime provenance: eval runs can store
  `prompt_version_id`, `agent_config_version_id`, and opaque runtime context for
  deployment/tool/retrieval/memory/guardrail/routing identifiers. Eval
  comparison output now includes deterministic provenance deltas so prompt/config
  changes can be linked to regression comparisons.
- Expanded the Datasets/Evals workspace so eval launches can select immutable
  prompt versions, immutable agent runtime config versions, deployment context,
  and tool-version identifiers, then inspect those links on the selected eval
  run and comparison output.

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
- Extended trajectory assertions with spec-named aliases for latency and tool
  retry caps, expected span-pattern matching, required grounding evidence IDs,
  and forbidden grounding-failure citations.
- Added draft behavior creation, deterministic rule/manual-label/judge detector
  backtesting, persisted backtest-positive behavior matches, and review-task
  creation for candidate positives.
- Expanded the Behavior Detail workspace with persisted match lists, trace links,
  match/review trend counts, false-positive review label display, backtest
  positive/negative examples, persisted-match summaries, and linked review/
  automation actions.
- Added a live Automations workspace in the web app with notification-target
  creation, automation definition creation, run-once execution, idempotency-key
  input, cooldown/action result inspection, and target listing wired to
  `/v1/notification-targets` and `/v1/automations`.
- Added automation preview and run-history APIs, then expanded the Automation
  Builder with trigger selection, condition fields/operators, action-list
  preview, cooldown key/seconds controls, matching-trace preview, test runs, run
  history, and dead-lettered action inspection.
- Added opt-in live webhook notification delivery for automations. Preview mode
  remains the default; live delivery requires
  `OPENABM_ENABLE_EXTERNAL_NOTIFICATIONS=true`, an active webhook target, and an
  encrypted secret ref for the endpoint URL. Delivery records audit IDs,
  grouping keys, HTTP status, transport failures, and retry/dead-letter state
  without rendering plaintext secrets.
- Added a local adapter-outbox delivery path for non-webhook notification target
  types (`chat`, `email`, `issue_tracker`, and `custom`). Live non-webhook
  deliveries now record a queued adapter audit envelope instead of failing as an
  unsupported target type, while vendor-specific transports remain outside the
  local reference implementation.
- Added explicit automation compensation actions. If an action fails with
  `on_failure: compensate`, OpenABM executes configured `compensation_actions`
  from the failed action and prior successful actions in reverse order, records
  each compensation result, and keeps the original dead-lettered failure visible.
- Added a typed automation rollback helper for created review tasks:
  `rollback_review_task` resolves the review task produced by the compensated
  action, marks it resolved with a rollback decision, and records the rollback
  target in the compensation result.

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

- Added prompt commit hashing, deterministic variable rendering, explicit
  audited secret-ref interpolation, and text diff helper.
- Added prompt registry storage/API lifecycle: prompt definitions, immutable
  prompt versions, content-addressed commit IDs, mutable tag pointers with tag
  events, deterministic render, version diff, and prompt diff tag-movement
  history, message-level diff for JSON chat-message templates, and linked eval
  result summaries surfaced through API, OpenAPI, tests, and UI.
- Added agent runtime configuration registry storage/API lifecycle: config
  records, immutable config versions, content-addressed commit IDs, mutable tag
  pointers with tag events, deterministic config diffs, and tag-movement history
  surfaced through API, OpenAPI, tests, and UI.
- Added MCP tool contract registry covering all required tool names, including
  side-effect and confirmation metadata, prompt and agent-config commit tools,
  and readable resources for trace/span/session/behavior/judge/dataset/prompt/
  agent-config/eval/automation/search/issue/investigation/impact/context-pack
  records.
- Added agent context pack generation and persistence with model-backed
  summaries, citation validation, deterministic fallback when a model provider is
  unavailable, and `/v1/context-packs` API coverage.
- Expanded the Issue/Investigation workspace with seed trace/session selectors,
  candidate query/filter/cohort display, context-pack creation/preview, and
  confirmation-gated behavior, judge, and dataset actions from investigation
  drafts.
- Expanded the Impact Report panel with recurrence, affected entities, business
  dimensions, task/workflow distribution, deployment/code context, suspected
  root causes, recommended next actions, remediation status, representative
  trace navigation, and JSON export.
- Persisted impact-report affected entities into canonical remediation records,
  linked them back to their source issue, and added `/v1/affected-entities`
  list/update APIs so entity status can move through needs-review, contacted,
  fixed, ignored, or false-positive states.
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
  emitting a tool call, so contradiction adjudication was split into a separate
  review-gated tool-call step instead of overloading claim extraction.
- Added model-backed grounding contradiction adjudication through a dedicated
  tool call. The model may identify direct contradictions and cite span IDs, but
  OpenABM validates claim membership and span citations before marking any claim
  `contradicted`, persists the adjudication metadata, and still routes the check
  through human review.
- Added passive novelty detection runs that group unknown error/tool signatures,
  persist candidate outputs, and create review tasks for behavior candidates.
- Added deterministic baseline negative-example selection for novelty runs so
  behavior candidates carry reviewable positive and negative trace examples.
  Similarity-index and model semantic grouping now preserve those negative
  examples when deterministic signature candidates are merged.
- Added a deterministic novelty clustering benchmark over the golden fixture
  corpus and surfaced it through `openabm bench novelty-clustering`. The
  benchmark now checks recall over fixture-labeled behavior traces, records
  unlabeled review workload separately from missed labels, and caught/closed the
  timeout-tool-loop gap by making timeout traces novelty-eligible.
- Added optional local-model semantic grouping for novelty runs through tool
  calls. The model can name and merge deterministic signature candidates, but
  trace membership is validated against source candidates before persistence.
- Verified a live LM Studio novelty canary against `qwen3.5-9b-mlx`: the model
  emitted a tool call, named the fixture candidate `Tool Selection Error`, and
  OpenABM persisted validated membership back to `error_wrong_tool` /
  `trace_wrong_tool` with model metadata.
- Added screenshot issue intake endpoint that stores screenshot-origin issues,
  normalizes screenshot plus attachment evidence, links source payload objects,
  and returns candidate seed traces with explicit match reasons.
- Added local text-like attachment parsing for screenshot intake: raw text,
  UTF-8 base64 text, and flattened JSON are normalized into auditable search
  evidence, while non-text/binary payloads remain explicit skipped/failed parse
  results rather than guessed OCR.
- Hardened trace full-text search normalization so filenames, JSON snippets, and
  other punctuation-heavy intake evidence cannot crash SQLite FTS candidate
  lookup.
- Added ChatOps-style investigation endpoint that creates canonical issue and
  investigation artifacts without binding the product to a chat vendor.
- Added canonical issue artifact links so issues can stay connected to
  investigations, impact reports, behaviors, judges, datasets, dataset
  examples, eval runs, and other follow-up artifacts. The API exposes
  `/v1/issues/{issue_id}/links`, creation flows can auto-link issue-derived
  artifacts, exports include issue links, and trace deletion scrubs linked
  trace/span evidence.
- Verified a live LM Studio investigation canary with `qwen3.5-9b-mlx`; the
  prompt revision produced a cited root cause, behavior draft, and rubric draft
  as valid unrepaired JSON with reasoning-token usage.
- Updated the model-runtime decision record from no-LLM deferral to the accepted
  local OpenAI-compatible provider strategy now that LM Studio chat/tool-call
  and embedding paths are implemented and covered by tests/canaries.
- Added human review task APIs and connected investigation root-cause/behavior
  candidates to the review queue instead of treating model drafts as active
  product decisions.
- Added a thin LangGraph-backed investigation workflow adapter that sequences
  candidate query planning, structured search, full-text search, and persisted
  investigation creation while keeping OpenABM storage/API records as the source
  of truth. Investigation results now persist an `orchestration` record with
  graph version, framework name, candidate queries, trace candidates, and
  tool-call inputs/outputs for replay/audit.
- Extended the LangGraph investigation workflow with stored embedding-index
  semantic similarity when available. Runs now persist semantic match details,
  cite similar trace/span evidence through orchestration events, and record
  skipped reasons when no seed trace or index is available.
- Normalized LangGraph investigation orchestration events with status,
  citation IDs, and MCP-readable resource URIs so deep-agent runners can follow
  an investigation event directly to its trace/span/issue/report evidence.
- Added a live Judge workspace in the web app with judge listing, immutable
  version inspection, calibration summaries, configurable promotion gates, and
  promotion results wired to `/v1/judges`.
- Added a live Datasets/Evals workspace in the web app with dataset creation,
  trace-to-dataset examples, registered-judge eval launch, result inspection,
  and eval comparison wired to `/v1/datasets` and `/v1/evals`.
- Added a live Behavior Monitoring workspace in the web app with manual/rule
  detector creation and deterministic backtesting wired to `/v1/behaviors`.
- Added a live Prompt Registry workspace in the web app with prompt creation,
  immutable version commits, tag movement, render, and diff wired to
  `/v1/prompts`.
- Added a live Agent Configs workspace in the web app with config creation,
  immutable version commits, content/metadata inspection, and version comparison
  wired to `/v1/agent-configs`.
- Added a live Issues/Investigations workspace in the web app with manual issue
  intake, screenshot-origin issue intake, ChatOps-origin issue/investigation
  creation, investigation run listing, and impact report inspection wired to
  `/v1/issues`, `/v1/chatops/investigate`, `/v1/investigations`, and
  `/v1/impact-reports`.
- Expanded the MCP tool contract registry to match the v2 required tool list,
  added resource templates, and added API-backed deterministic handlers for the
  implemented read/draft paths with explicit unsupported responses for gaps.
- Connected MCP handlers for prompt list/get/commit and agent config
  list/get/compare now that those APIs exist.
- Connected MCP handlers for automation list/get now that automation APIs exist.
- Connected the remaining MCP placeholders for judge list/get/draft, eval run
  and compare, and docs search to API-backed routes.
- Hardened the MCP tool manifest from placeholder contracts into concrete input
  schemas, required scopes, side-effect flags, confirmation metadata, and
  examples for every required tool so LangGraph/Deep Agents/Pi-style runners
  have a real tool surface to consume.
- Expanded the MCP tool surface with context-pack creation, review-task
  list/decision tools, and affected-entity remediation tools so investigation
  agents can act through audited review/remediation APIs instead of only reading
  trace evidence.
- Added concrete MCP `search_spans` support backed by `/v1/search/spans`, and
  added coverage that the local agent-flow smoke only advertises real MCP tools.
- Corrected the MCP prompt-commit contract to use `template_text` and
  `variables_schema`, and added a prompt-render MCP tool so prompt lifecycle
  work is executable through tool calls.
- Expanded MCP tool observability from latency/status rows to bounded
  request/response capture, citation IDs, and confirmation metadata so deep
  agent tool use is replayable enough for audit without changing tool results.
- Enforced MCP confirmation gates for high-impact write tools: schemas now
  expose `confirmed`, unconfirmed calls return `confirmation_required` before
  touching API routes, confirmed calls strip the execution guard from domain
  payloads, and observations record the gated status.
- Upgraded the MCP stdio server resource surface from string-only template
  discovery to protocol-shaped resource templates plus `resources/read` support
  for trace, span, session, behavior, judge, dataset, prompt, eval-run,
  automation, saved-search, issue, investigation-run, impact-report, and
  agent-context-pack URIs.
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
- Added a live Operations workspace in the web app with health/readiness,
  metrics text, project export manifests, retention policy creation and dry-run
  / tombstone actions, plus data classification policy creation and payload
  classification checks wired to the local API.
- Added local reference auth storage and API coverage for the section 31 auth
  contract: role-to-scope enforcement, local owner bootstrap, hashed API-key
  creation/revocation, service accounts, users, memberships, invites, session
  records, cookie/CSRF policy metadata, passwordless decision records, and an
  external IdP adapter boundary. Expanded the Operations workspace with auth
  mode/role visibility plus API-key, user, invite, and session controls.
- Added queued local invite delivery records for auth invites, including a
  local outbox payload, audit entry, list endpoint, invite-list attachment, and
  Operations workspace visibility so invites no longer exist only as inert rows.
- Added local encrypted secret management using `cryptography` Fernet envelope
  encryption, scoped secret refs, redacted list/get responses, audited
  create/resolve/rotate access, rotation versions, an external secret-manager
  adapter boundary, and Operations workspace controls that create/rotate refs
  without rendering plaintext values.
- Expanded privacy/export/delete coverage: project exports now include metadata,
  trace/span JSONL, dataset examples, eval results, prompts, affected entities,
  redacted secret refs, and an audit summary with per-section hashes; trace
  tombstones now scrub or remove trace references from dimensions, dataset
  examples, eval results, review evidence, investigations, context packs,
  impact reports, affected entities, search documents, payload bodies, scores,
  spans, and behavior matches.
- Added local observability coverage: API route/status/error/schema-invalid
  counters, request latency summaries, model-provider latency/error/invalid
  output counters, judge/eval/investigation/impact/comparison latency metrics,
  storage and payload growth gauges, queue-depth gauges, worker heartbeats, and
  dead-letter run inspection.
- Added `/v1/ops/status`, `/v1/ops/worker-heartbeats`, and
  `/v1/ops/dead-letter`, backed by a worker heartbeat migration and surfaced in
  the Operations workspace as an admin status panel with storage, payload,
  queue, retention, automation failure, heartbeat, and dead-letter visibility.
- Added a Docker Compose production-reference deployment contract covering API,
  web, retention worker, persistent SQLite/payload storage, configurable CORS
  origins, health/readiness checks, and a smoke-check script.
- Added a local retention worker path: `openabm worker retention-once` can
  dry-run or apply active trace-retention policies, the worker process now loops
  over the same deterministic runner, and each run records heartbeats plus
  `apply_retention_policy` audit entries so `/v1/ops/status` reflects retention
  job status.
- Added worker deployment supervision signals: ops status now classifies worker
  heartbeats as healthy, stale, or unhealthy, counts stale/unhealthy workers, and
  the Operations workspace shows worker risk next to heartbeat rows.
- Added MCP tool observability: the MCP handler records best-effort tool
  latency/status observations through `/v1/ops/mcp-tool-observations`, ops
  status summarizes MCP call and error counts by tool, metrics expose MCP tool
  latency/call/error counters, exports include the observation rows, and the
  Operations workspace surfaces MCP call health.

## Phase 9: Real-World Pilot And Revisit Decisions

Status: not started

Blocked:

- Requires real pilot usage and owner direction after the scaffold is runnable.

## Running Notes

- Use `SPEC_EDIT_SUGGESTIONS.md` for any recommended spec changes.
- Keep the spec itself unmodified.

## Acceptance Pass: 2026-05-12

Verified after the latest implementation slices:

- `make lint`: passed.
- `make test`: passed, 91 tests after the model-benchmark, LangGraph
  investigation-adapter, core-loop acceptance, reported-incident acceptance,
  retention-worker, MCP observability, command-runner eval, expanded fixture,
  assertion-result persistence, and benchmark-rubric calibration slices.
- `npm --prefix apps/web run build`: passed.
- Browser QA captured desktop and mobile Trace Detail, Operations, Issues, and
  Automations workspace screenshots under `artifacts/ui-qa/`; trace detail mode
  switching, saved search creation/application, trace-list dataset bulk add,
  trace-list latency/token/cost columns, score and behavior badges, selected
  span inspection, payload/evidence panels, trace-detail add-to-dataset,
  trace-detail behavior labeling, deterministic assertion checks, similar trace
  result rendering, and local qwen-backed rubric judge execution, retention
  dry-run, export manifest, classification, issue intake, screenshot intake,
  ChatOps investigation, Judge Editor draft creation/version commit, Behavior
  Detail backtest/match/review/action rendering, matched-trace navigation,
  Eval Comparison baseline/candidate selection, delta/failure-list rendering,
  eval-failure trace navigation, notification target creation, Automation
  Builder trigger/condition/action/cooldown controls, matching-trace preview,
  run history, dead-letter display, automation creation, and automation run-once
  flows completed against the live local API with no console errors or failing
  API responses.
- Issue/Investigation QA covered seed trace/session selection, candidate
  query/filter/cohort display, context-pack preview, model-assisted rubric draft
  display, and confirmation-gated dataset/judge action controls against the live
  local API with no console errors.
- Impact Report QA covered recurrence, business dimensions, task/workflow,
  deployment/code context, affected entities, recommended actions, representative
  trace navigation, and report JSON export visibility with no console errors.
- Auth/Ops QA covered auth contract rendering, local role matrix visibility,
  API-key creation with one-time secret reveal, user and invite creation,
  session creation, and zero console errors against the live API.
- Secret/Ops QA covered local encryption status, external-provider boundary,
  secret-ref creation, rotation to version 2, access-log rendering, and verified
  plaintext secret values did not appear in rendered UI text.
- Ops Observability QA covered the admin status panel, storage/payload/queue
  metrics, worker heartbeat creation, and dead-letter visibility on desktop and
  mobile with no console errors or failing API responses. Screenshots:
  `artifacts/ui-qa/openabm-ops-observability-desktop.png` and
  `artifacts/ui-qa/openabm-ops-observability-mobile.png`.
- `make demo-eval`: passed with one deterministic eval result, zero LLM calls,
  and one expected fail verdict for the wrong-tool fixture.
- MCP manifest/stdio smoke: the current tool surface exposes 43 tools and
  `resources/templates/list` returns 15 protocol-shaped JSON resource
  templates.
- Live LM Studio canaries completed for structured rubric output, semantic trace
  similarity, and investigation drafting with `openabm-qwen35-9b`.
- Live LM Studio model-runtime benchmark completed with `qwen3.5-9b-mlx` against
  the expanded 22-fixture golden corpus at 262,144 context and no OpenABM
  generation timeout. The first expanded run exposed a narrow-rubric prompt
  mismatch and blocked promotion at 10/22 accuracy while preserving structured
  output validity 1.0, citation validity 1.0, invalid-output rate 0.0, and
  context-failure rate 0.0. Prompt/runtime calibration then improved the same
  9B model through 18/22 and 20/22 promotion-eligible runs before the final
  decision-order rubric reached 22/22 accuracy with structured-output validity
  1.0, citation validity 1.0, invalid-output rate 0.0, context-failure rate
  0.0, unsure rate 0.2273, 120,910 total tokens, and 1,687.5s total latency.
  Machine-readable local artifacts are under
  `artifacts/model-benchmarks/qwen3.5-9b-golden-expanded.json`,
  `artifacts/model-benchmarks/qwen3.5-9b-golden-expanded-prompt-v2.json`,
  `artifacts/model-benchmarks/qwen3.5-9b-golden-expanded-decision-order.json`,
  and
  `artifacts/model-benchmarks/qwen3.5-9b-golden-expanded-decision-order-v2.json`.
  The final artifact is the current best local qwen benchmark result.
- LangGraph investigation adapter regression passed: investigation runs now
  persist framework, graph version, candidate search queries, trace candidates,
  and tool-call inputs/outputs before model assistance and review tasks are
  layered on top.
- Core loop acceptance regression passed: fixture ingest, explicit judge draft
  and versioning, rubric judge execution, behavior creation/backtest, dataset
  example creation, baseline/candidate eval runs, eval comparison, and MCP trace
  retrieval all preserve trace/span/score/dataset/eval provenance.
- Reported incident acceptance regression passed: manual issue creation,
  business-dimension annotation, LangGraph-backed investigation, impact report
  recurrence/entity/task scoping, cited model-assisted root cause and behavior
  draft, behavior backtest, judge draft link, dataset/eval creation, eval
  comparison, and issue-to-artifact link retrieval all preserve canonical
  provenance.
- Retention worker regression passed: active trace-retention policies can be
  dry-run or applied by the worker runner, trace tombstoning is performed by the
  same storage contract as the API, and worker heartbeat plus ops retention
  status are updated.
- MCP observability regression passed: MCP tool calls record latency/status,
  bounded request/response payloads, citations, and confirmation metadata
  without changing tool results; `/v1/ops/status` summarizes those observations,
  and the observation list endpoint returns the recorded rows.
- Command eval runner regression passed: a command runner received the dataset
  example plus source trace/spans, returned an offline trace/span bundle, OpenABM
  ingested that offline trace, and the deterministic judge scored the returned
  offline trace rather than the original source trace.
- Affected-entity remediation regression passed inside the reported-incident
  acceptance flow: impact scoping persisted the affected account, issue links
  included the remediation record, and the API updated the entity status to
  fixed with owner/notes.
- Backpressure/sampling regression passed: oversized inline payloads and sampled
  model-stream events are persisted as explicit omission markers, low-priority
  oversized batches receive retryable 429 backpressure responses, high-priority
  traces still ingest under pressure, batch ingest accepts events/feedback/
  payload metadata, and SDK buffering remains bounded while preserving
  high-priority items.
- Context-packet regression passed: judge context packets now summarize long
  payloads, preserve high-priority evidence spans before low-signal spans under
  budget pressure, record omitted spans/truncation notes, and persist a
  reproducible context-packet hash in score provider metadata.
- Contributor workflow regression passed locally: `make ci` covers lint, tests,
  OpenAPI JSON validation, docs link checks, and web build; GitHub Actions
  mirrors those gates and adds PR dependency review. Dependency review is
  non-blocking until GitHub dependency graph is enabled for the repository.
- Live-notification regression passed with a monkeypatched webhook transport:
  automation delivery resolves an encrypted secret ref, sends a grouped webhook
  payload only when external notifications are explicitly enabled, records an
  audit-backed delivery result, and keeps plaintext endpoint values out of the
  action result.
- Automation compensation regression passed: a failed notification action with
  `on_failure: compensate` ran an explicit notification compensation action for
  a prior review-task action, preserved the original dead-lettered action, and
  reported the compensation status/result on the failed action.
- Runtime-provenance regression passed: SDK traces export prompt/config/
  deployment/tool version identifiers, ingest and trace detail preserve them,
  eval run comparison reports prompt/config/context deltas, and impact/root-cause
  output surfaces correlated runtime provenance distributions.
- Differential root-cause regression passed: impact reports now compare the
  failing cohort against a baseline cohort across status, dimensions, runtime
  provenance, tool usage, span status, and error types, with failing/baseline
  metrics, deltas, and representative trace/span IDs on each candidate.
- Impact reports now include behavior-match drilldowns for the investigated
  trace cohort: matched behavior names, severities, match counts, status counts,
  trace IDs, and evidence span IDs are persisted as deterministic report
  evidence and surfaced as a root-cause candidate when present.
- The impact-report UI now renders known behavior-label distribution alongside
  recurrence, affected entities, dimensions, deployment context, and suspected
  root causes.
- Code-sandbox conformance regression passed: the dev sandbox scrubs secrets,
  denies blocked network imports, restricts file reads/writes to the input/output
  bundle and temporary artifact directory, maps timeouts and invalid results to
  shared score statuses, and exposes policy metadata for audit.
- Eval provenance UI build passed: the Datasets/Evals workspace now hydrates
  prompt/config version options, sends selected provenance with eval runs, and
  renders selected-run runtime context plus comparison provenance changes.
- Added eval runtime analytics over historical runs: `/v1/evals/analytics`
  groups pass/invalid-output trends by prompt version, agent config version, and
  deployment context, with a compact Datasets/Evals UI summary.
- Worker supervision regression passed: ops status reports healthy worker
  heartbeats, marks stale heartbeats after the local freshness threshold, counts
  worker risk, and the Operations workspace renders that risk next to heartbeat
  rows.
- Git status after final validation was clean against `origin/main`.

Known remaining gaps before calling the whole spec complete:

- Prompt registry and agent runtime configuration registry now have storage/API,
  MCP-backed lifecycle flows, and live UI coverage for prompt version history,
  tag movement, render, diff, plus agent config history/comparison. Prompt and
  agent config diffs now return tag-movement history; prompt diff also returns
  message-level diff when templates are JSON chat-message arrays and linked eval
  summaries for the compared commits.
- Judge registry, model-backed judge drafting, local eval launch, eval
  comparison, judge calibration reporting, promotion gates, and the judge
  lifecycle workspace now exist. Prompt/config-linked eval launch, comparison
  provenance, and runtime-version analytics are now wired; deeper historical
  drilldowns remain future polish.
- Automation definitions and local run execution include deterministic
  conditions, idempotency, preview notifications, opt-in live webhook delivery,
  review-task actions, cooldown skips, bounded retries, and dead-letter action
  visibility, plus explicit compensation actions and a typed review-task
  rollback helper; rollback adapters for external ticketing/workflow systems
  remain future work.
- Passive novelty detection has deterministic exact-signature grouping,
  deterministic baseline negative examples for review, optional model semantic
  grouping/naming with validated membership, and optional similarity-index
  grouping over stored trace vectors. A golden-fixture clustering benchmark now
  protects labeled-behavior recall; broader pilot-scale clustering benchmarks
  and production vector-store choices remain future work.
- Grounding/fabricated-value checks support explicit, deterministically split,
  and model-extracted claims with exact evidence matching, plus review-gated
  model contradiction adjudication with validated span citations; broad
  automatic contradiction decisions across arbitrary evidence types remain out
  of scope.
- Screenshot issue intake and ChatOps-style issue/investigation creation exist;
  screenshot/attachment metadata, extracted text, local text-like attachment
  parsing, base64 text decoding, and JSON flattening are preserved as evidence,
  while real OCR, binary/deep document parsing, and vendor-specific chat
  connectors are still future integration work.
- UI pages are useful scaffolds rather than full spec-complete workspaces for
  behavior detail, deeper impact-report UI drilldowns, and deeper
  prompt/configuration history.
- External IdP/OAuth login, vendor email/SMTP invite delivery, and production
  secret-manager provider adapters remain beyond the local reference scaffold.
- Production-grade observability exporters, log aggregation, external
  deployment supervision, and vendor-specific non-webhook transports are still
  future hardening beyond the local reference surfaces; local worker
  stale/unhealthy heartbeat detection and non-webhook adapter outbox records are
  now implemented.

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
- Hid temporary `/api/...` compatibility aliases from the live generated
  OpenAPI schema so runtime API docs expose only stable `/v1/...` contracts.
- Added contract coverage that the committed OpenAPI path/method set matches
  the live app's generated public schema.
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
  preview-by-default notification action audits.
- Added opt-in live webhook notification delivery from encrypted secret refs;
  live sends are disabled unless the local operator explicitly enables external
  notifications.
- Added live non-webhook notification adapter outbox records so email/chat/
  issue-tracker/custom targets have an audited local delivery contract while
  vendor transports remain adapter-specific future work.
- Notification target creation now rejects plaintext config blobs and validates
  `config_secret_refs`; active targets require at least one secret ref, while
  paused placeholders can be created without mounting secrets.
- Added persisted automation cooldown checks keyed by configured scope so
  repeated matching runs can be skipped before action execution without losing
  the condition/cooldown audit record.
- Added bounded retry attempts and visible dead-letter action results for
  automation actions, including configured `on_failure: continue` behavior for
  partial-failure runs.
- Added configured `on_failure: compensate` behavior with explicit
  `compensation_actions` executed in reverse order from failed/prior actions.
- Added `rollback_review_task` as the first typed compensation helper so a
  review task created by an earlier automation action can be resolved if a later
  action fails.
- Added `/v1/grounding-checks` and `/v1/novelty-runs` paths for reviewable
  fabricated-value checks and passive behavior candidate discovery.
- Added model-assisted `/v1/grounding-checks` claim extraction with persisted
  model metadata and deterministic support validation.
- Captured a proposed long-term orchestration direction in
  `docs/decisions/0006-agent-orchestration-framework.md`: evaluate LangGraph /
  Deep Agents or Pi-style cores after OpenABM's primitive local tool-call
  boundary is proven.
- Updated that direction with source-checked current OSS positioning for
  LangGraph, Deep Agents, and Pi/pi-agent-core, plus an adoption sequence that
  keeps OpenABM's audit/provenance contracts authoritative.
- Added `/v1/issues/from-screenshot` and `/v1/chatops/investigate` entrypoints
  for weak human reports and chat-originated investigations; screenshot intake
  now preserves screenshot and attachment payload links plus extracted text,
  decoded text attachments, and flattened JSON evidence for seed trace search.
- Added review-gated model contradiction adjudication for grounding checks:
  requests can opt into a second tool call that cites contradictory spans, and
  OpenABM validates claim/span IDs before persisting contradicted status.
- Added OpenAI-compatible embedding-provider support and an embedding-backed
  `/v1/search/similar` representation, so local deployments with an embedding
  model can use deterministic cosine similarity without waiting for a persisted
  vector index.
- Added a transparent local similarity-index rebuild/search path over stored
  embedding vectors with representation-version metadata, source hashes, and
  trace/span vector counts.
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
- Added a live Operations workspace in the web app so retention/export/privacy
  operations can be exercised from the UI instead of only through integration
  tests.
- Added a live Issues/Investigations workspace in the web app so issue intake,
  screenshot intake, ChatOps artifact creation, investigation run selection,
  and impact report inspection can be exercised from the UI.
