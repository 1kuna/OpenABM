# DR-005: Local Stack Runner

Status: accepted-local-reference

Date: 2026-05-12

## Context

Contributors need one command path for local development that does not require
LLMs or hosted infrastructure.

## Contract

The local stack must initialize stores, run the API, run the web app, seed
fixtures, expose health checks, and allow reset/restart.

## Decision

Use `make` targets over Python and Node package scripts for the local reference
stack, with SQLite and local filesystem state under `.openabm/`.

## Evidence

- `make ci` runs lint, the full Python contract/runtime test suite, OpenAPI JSON
  validation, docs link checks, and the web build.
- `make deploy-config-check` validates the Compose contract used by the
  production-reference stack.
- `make api`, `make worker`, `make web`, and `make mcp` expose the local API,
  retention worker, Vite app, and MCP server.
- `make init-db`, `make seed-fixtures`, `make demo-eval`, and `make reset-local`
  cover clean initialization, fixture ingest, deterministic eval, and local
  reset.

## Revisit Triggers

- More services make process supervision fragile.
- Containerized development becomes simpler than local processes.
- Production deployment manifests require a different layout.
