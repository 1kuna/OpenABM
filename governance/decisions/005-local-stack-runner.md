# DR-005: Local Stack Runner

Status: provisional

Date: 2026-05-12

## Context

Contributors need one command path for local development that does not require
LLMs or hosted infrastructure.

## Contract

The local stack must initialize stores, run the API, run the web app, seed
fixtures, expose health checks, and allow reset/restart.

## Decision

Use `make` targets over Python and Node package scripts for the first scaffold,
with SQLite and local filesystem state under `.openabm/`.

## Evidence

Pending tests should prove clean initialization, fixture ingest, API health,
web build, and reset behavior.

## Revisit Triggers

- More services make process supervision fragile.
- Containerized development becomes simpler than local processes.
- Production deployment manifests require a different layout.

