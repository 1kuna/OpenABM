# 0006 Agent Orchestration Framework Direction

Date: 2026-05-12

## Status

Accepted for a thin local adapter prototype

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

## Current OSS Read

As of 2026-05-12, primary project sources support keeping these candidates in
the evaluation lane:

- LangGraph positions itself as the low-level orchestration runtime for
  long-running, stateful agents with durable execution, persistence, streaming,
  memory, and human-in-the-loop control:
  <https://docs.langchain.com/oss/python/langgraph/overview>.
- LangChain Deep Agents positions itself as an open-source agent harness built
  on LangChain and LangGraph, with planning, subagents, filesystem-backed
  context, skills, memory, and MCP support:
  <https://docs.langchain.com/oss/python/deepagents/overview> and
  <https://github.com/langchain-ai/deepagents>.
- Pi has both a Python `pi-agent-core` package and the TypeScript Pi mono repo.
  The Python package is a minimal, LLM-agnostic stateful loop with tool
  execution, event streaming, steering/follow-up queues, cancellation, and proxy
  transport: <https://pypi.org/project/pi-agent-core/>. The Pi mono repo
  exposes the broader coding-agent, agent-core, unified-provider, TUI, and web
  UI package family: <https://github.com/earendil-works/pi>.

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

## Adoption Sequence

1. Keep implementing OpenABM primitives as deterministic API/MCP/tool-call
   contracts with durable audit storage.
2. Add a small orchestration adapter layer that can call those contracts without
   making a framework the source of truth for traces, review tasks, judges,
   evals, or decisions.
3. Prototype LangGraph first for durable issue/investigation workflows where
   explicit state transitions and human interrupts matter.
4. Prototype Deep Agents for multi-step investigation/coding-agent style flows
   that need planning, subagents, file/context management, or skills.
5. Prototype Pi/pi-agent-core only if the local reference stack needs a thinner
   streaming/tool-loop harness than LangGraph/Deep Agents, or if Pi's provider
   and UI packages become a better fit for local-first use.

## Acceptance Gate Before Adoption

- Tool calls work through LM Studio with the configured local model.
- Tool requests and tool results can be persisted as trace spans/events.
- Human review gates can interrupt sensitive actions.
- The framework can run locally without requiring cloud-hosted model calls.
- The framework does not hide prompts, tool payloads, citations, or model
  outputs from OpenABM audit storage.

## Implementation Update: 2026-05-13

OpenABM now includes a first LangGraph-backed investigation workflow adapter.
The adapter is intentionally thin: LangGraph sequences candidate query planning,
structured trace search, full-text search, and persisted investigation creation,
while OpenABM storage remains the source of truth for traces, impact reports,
review tasks, model assistance, and audit records.

Each investigation run stores an `orchestration` record with the framework name,
graph version, generated search queries, candidate trace IDs, and tool-call
inputs/outputs. This keeps framework execution inspectable and preserves the
option to evaluate Deep Agents or Pi/pi-agent-core later without changing the
product data contracts.
