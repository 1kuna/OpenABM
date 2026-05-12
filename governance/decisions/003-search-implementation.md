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
implementation. Semantic search remains deferred until embeddings are enabled.

## Evidence

Pending tests should cover common filters, error search, full-text search,
pagination, and fixture reconstruction paths.

## Revisit Triggers

- Fixture search misses local performance targets.
- FTS behavior cannot satisfy required ranking/filter semantics.
- Semantic search is enabled with real embeddings and requires a vector index.

