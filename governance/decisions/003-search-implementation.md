# DR-003: Search Implementation

Status: accepted-local-reference

Date: 2026-05-12

## Context

OpenABM needs structured and text trace search before semantic search can be
tested honestly.

## Contract

Search must support project/time/status/environment/span-type/model/tool/error
filters, pagination, result provenance, and later replacement behind a search
adapter.

## Decision

Use SQLite structured filters and FTS as the initial local reference search
implementation. For semantic search, keep the local reference implementation in
SQLite as a transparent candidate index: vectors are stored as JSON with an
explicit representation version, provider, model, dimensions, and source hash.
This is suitable for local proof and auditability, but it is not a production
vector-store commitment.

## Evidence

- `make ci` passes integration coverage for trace/span search, saved searches,
  docs search, issue-seeded candidate search, investigation candidate query
  planning, and MCP trace retrieval.
- Local similarity search now has both fail-closed disabled-provider coverage
  and OpenAI-compatible embedding-provider coverage with provider/model,
  representation version, source hash, dimensions, and deterministic candidate
  evidence persisted for audit.
- `docs/decisions/0006-agent-orchestration-framework.md` records LangGraph as
  the current orchestration lane while keeping search and context-pack contracts
  owned by OpenABM.

## Revisit Triggers

- Fixture search misses local performance targets.
- FTS behavior cannot satisfy required ranking/filter semantics.
- Local vector JSON search misses performance or quality targets on pilot trace
  volumes.
- A production deployment needs ANN indexing, vector-store filtering, or
  clustering beyond the local reference contract.
