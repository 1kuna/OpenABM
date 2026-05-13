# 0006 Agent Orchestration Framework Direction

Date: 2026-05-12

## Status

Proposed

## Context

OpenABM needs deep-agent workflows to investigate, evaluate, and improve other
deep agents. Building that entire orchestration stack from scratch would risk
spending effort on generic agent-loop mechanics instead of OpenABM's core
product contracts: trace provenance, judge evidence, eval reproducibility,
review gates, and audit trails.

## Direction

Use OpenABM-owned deterministic contracts for trace search, context packs,
judges, evals, review tasks, datasets, and audit persistence. Expose those
contracts as tool-callable capabilities through the model provider and MCP/API
surface.

For long-running agent orchestration, prefer evaluating an existing open-source
framework before implementing a custom runner:

- LangGraph for durable, stateful orchestration, human-in-the-loop control, and
  explicit graph-shaped workflows.
- LangChain Deep Agents as a higher-level harness for planning, subagents,
  filesystem-like workspaces, permissions, and skills if it fits OpenABM's
  investigation workflows.
- Pi/pi-agent-core as a lighter-weight candidate for provider-agnostic tool
  loops and streaming if LangGraph is too heavy for the local reference stack.

## Near-Term Implementation Rule

Do not add a framework dependency until the OpenABM primitive contracts are
proven with local model tool calls. The first integration target is native
OpenAI-compatible tool-call support in the local model provider. Agent
frameworks should orchestrate OpenABM tools; they should not become the source
of truth for product decisions or provenance.

The first proven primitive is model-assisted grounding claim extraction through
LM Studio tool calls. The claim extractor is intentionally narrow: the model
extracts claim strings, while OpenABM code performs exact evidence validation
and persists model metadata. Broader contradiction adjudication should be a
separate tool only after a prompt/runtime contract is proven with local
canaries.

## Acceptance Gate Before Adoption

- Tool calls work through LM Studio with the configured local model.
- Tool requests and tool results can be persisted as trace spans/events.
- Human review gates can interrupt sensitive actions.
- The framework can run locally without requiring cloud-hosted model calls.
- The framework does not hide prompts, tool payloads, citations, or model
  outputs from OpenABM audit storage.
