# DR-002: Model Runtime Adapter Strategy

Status: deferred-no-llm

Date: 2026-05-12

## Context

The model runtime powers rubric judges, summarization, embeddings, behavior
suggestions, and investigation chat. This scaffold pass is explicitly not using
local or hosted LLMs.

## Contract

The implementation must expose provider adapters, health checks, structured
output validation, local-only mode, and fail-closed behavior when model calls
are disabled.

## Decision

Implement adapter interfaces and a disabled provider that fails closed. Defer
any real local or external provider until Zach opts into LLM usage.

## Evidence

Pending tests should prove disabled mode rejects model-backed work without
network calls and records the blocked status visibly.

## Revisit Triggers

- Zach enables local or cloud model execution.
- Rubric judge, summarization, embedding, or investigation-agent acceptance
  tests need real model outputs.

