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

Implement only a development-only sandbox with strict timeouts, scrubbed
environment, temporary directories, structured result validation, and loud
warnings that hardened network/filesystem isolation is not adopted yet.

## Evidence

- `tests/unit/test_non_llm_runtime.py` covers secret non-inheritance, disabled
  network imports, timeout/resource-exceeded status mapping, invalid structured
  results, stdout/stderr capture, and filesystem access constrained to the
  temporary input/artifact bundle.
- The sandbox policy metadata reports `dev_only`, network-disabled,
  secrets-unmounted, timeout, CPU, and memory limit settings for every run.
- `make ci` exercises the sandbox alongside the other local runtime contracts.

## Revisit Triggers

- Production code judges are enabled.
- Sandbox escape tests fail.
- A stronger local isolation primitive is chosen.
