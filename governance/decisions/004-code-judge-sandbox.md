# DR-004: Code Judge Sandbox

Status: provisional-dev-only

Date: 2026-05-12

## Context

Code judges are useful without LLMs, but production sandboxing is
security-sensitive.

## Contract

Code judge runs need isolation, no secrets by default, network disabled by
default, read-only inputs, temporary artifacts, resource limits, timeout,
stdout/stderr capture, structured result serialization, artifact cleanup, and
audit records.

## Decision

Implement only a development sandbox scaffold with strict timeouts, scrubbed
environment, temporary directories, structured result validation, and loud
warnings that hardened network/filesystem isolation is not adopted yet.

## Evidence

Pending tests should cover happy path, timeout, invalid result, stdout/stderr,
and secret non-inheritance.

## Revisit Triggers

- Production code judges are enabled.
- Sandbox escape tests fail.
- A stronger local isolation primitive is chosen.

