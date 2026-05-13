# DR-001: Local Development Storage Backend

Status: accepted-local-reference

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

Use SQLite plus local filesystem payload storage as the local reference
implementation.

## Evidence

- `SQLiteStore.init_db()` applies migrations and creates the local reference
  schema under the configured `sqlite:///` path.
- `make ci` passes integration coverage for batch ingest, trace lookup,
  reconstruction, payload metadata, retention/export/delete, eval provenance,
  investigation flows, and MCP trace/context-pack access.
- `./scripts/openabm init-db`, `./scripts/openabm seed-fixtures`,
  `make demo-eval`, and `make reset-local` provide the local setup, fixture,
  deterministic eval, and reset paths.
- `make deploy-config-check` validates the Docker Compose reference contract
  that mounts the same SQLite/payload storage model into API and worker
  containers.

## Known Limitations

- Not the production scale target.
- Similarity search and high-volume analytics will require separate evidence
  before adoption.

## Revisit Triggers

- Fixture expansion exceeds local performance targets.
- Local contributors hit setup or migration friction.
- Retention/backfill behavior cannot be made reliable.
