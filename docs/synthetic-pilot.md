# Synthetic Pilot Lab

The synthetic pilot lab is Phase 9A validation. It exercises real local
OpenABM surfaces with generated, real-world-style traces while clearly avoiding
claims of real user validation.

Run the deterministic pilot:

```bash
./scripts/openabm synthetic-pilot
```

Run optional local model semantic lanes against LM Studio:

```bash
lms load qwen3.5-9b-mlx --context-length 32768 --identifier qwen3.5-9b-mlx -y
lms ps
./scripts/openabm synthetic-pilot --use-model --chat-model qwen3.5-9b-mlx
```

Run model-generated fake conversations through the pilot:

```bash
lms load qwen3.6-35b-a3b --context-length 32768 --identifier qwen3.6-35b-a3b --parallel 1 -y
lms ps
./scripts/openabm synthetic-pilot \
  --generate-conversations \
  --generated-conversation-count 2 \
  --chat-model qwen3.6-35b-a3b \
  --output .openabm/synthetic-pilot/agentgen-35b
```

`lms ps` should show `CONTEXT` of at least `32768` before running the model
lanes. OpenABM does not set generation timeouts on local model calls.
If a different local model is used, keep the same 32k-or-higher context rule
and record the resulting report path in `IMPLEMENTATION_PROGRESS.md`.

The command writes `report.json`, `fixtures.json`, and `summary.md` under
`.openabm/synthetic-pilot/latest` by default. `.openabm/` is ignored, so these
local reports do not get committed accidentally.

## What It Exercises

- Synthetic commerce-support traces for refund, escalation, fulfillment,
  checkout, prompt-injection, PII, and tool-replay cases.
- Runtime provenance across prompt versions, agent config versions, deployment
  contexts, and tool versions.
- Auth users, invites, local secret refs, preview notification targets, and
  worker heartbeat/ops status.
- Trace ingest, business dimensions, code context, payload metadata, datasets,
  deterministic evals, eval comparison, behavior backtests, novelty detection,
  grounding checks, issues, investigations, impact reports, context packs,
  review tasks, automation runs, retention dry-runs, and export manifests.
- Optional model-generated customer-agent conversations submitted through a
  tool call, converted into OpenABM traces/spans, dataset labels, and behavior
  feedback actions. The generator validates raw tool data separately from
  evaluator feedback so synthetic traces do not smuggle labels into evidence.
- Optional Qwen/LM Studio semantic lanes for context-pack summary, investigation
  assistance, novelty grouping, grounding extraction/adjudication, and a small
  rubric-judge eval subset.

## Boundaries

This is synthetic validation. It can catch integration, provenance, workflow,
and model-contract failures before real users arrive, but it does not replace:

- real pilot usage,
- real usability feedback,
- vendor-specific production integration proof,
- production deployment confidence,
- or future legal/commercial strategy decisions.
