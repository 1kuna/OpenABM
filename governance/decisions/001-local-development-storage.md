# DR-001: Local Development Storage Backend

Status: provisional

Date: 2026-05-12

## Context

OpenABM needs one runnable local reference storage path for contributors while
preserving replaceable storage contracts.

## Contract

The storage layer must support schema migrations, idempotent trace/span ingest,
trace lookup, time-range search, payload metadata, derived views, retention
cleanup hooks, and fixture seeding.

## Candidates

- SQLite with local filesystem payload objects.
- External relational database plus object store.

## Decision

Use SQLite plus local filesystem payload storage as the initial local reference
implementation.

## Evidence

Initial scaffold evidence is pending. The first acceptance gate is clean schema
initialization, fixture ingest, trace lookup, reconstruction, and local reset.

## Known Limitations

- Not the production scale target.
- Similarity search and high-volume analytics will require separate evidence
  before adoption.

## Revisit Triggers

- Fixture expansion exceeds local performance targets.
- Local contributors hit setup or migration friction.
- Retention/backfill behavior cannot be made reliable.

