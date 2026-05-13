# DR-003: Search Implementation

Status: provisional

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

Pending tests should cover common filters, error search, full-text search,
pagination, and fixture reconstruction paths.

## Revisit Triggers

- Fixture search misses local performance targets.
- FTS behavior cannot satisfy required ranking/filter semantics.
- Local vector JSON search misses performance or quality targets on pilot trace
  volumes.
- A production deployment needs ANN indexing, vector-store filtering, or
  clustering beyond the local reference contract.
