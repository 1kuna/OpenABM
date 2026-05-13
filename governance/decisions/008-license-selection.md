# DR-008: License Selection

Status: owner-review-required

Date: 2026-05-13

## Context

OpenABM is intended to be a public open-source project, but adding a license is
a legal/product choice that should be made by the repository owner rather than
silently selected by the implementation agent.

## Contract

The repository should not imply an open-source license until a `LICENSE` file is
committed. Public code, docs, schemas, examples, and assets must remain original
OpenABM work regardless of license choice.

## Candidates

- Apache-2.0 for permissive use with explicit patent grant.
- MIT for a short permissive license.
- AGPL-3.0-only or AGPL-3.0-or-later for stronger network-copyleft behavior.
- Dual license if a future commercial/open-core strategy needs it.
- No license until owner approval.

## Workloads

- Public GitHub repository discovery.
- Contributor expectations.
- Downstream self-hosted usage.
- Future commercial or hosted-service positioning.
- Dependency license review.

## Decision

Do not add a `LICENSE` file yet. Keep this decision record as the explicit
placeholder until Zach chooses the license.

## Evidence

- The implementation spec requires owner-safe legal/IP boundaries and original
  public artifacts.
- `IMPLEMENTATION_PROGRESS.md` records the final license file as deferred until
  owner confirmation.
- The repository includes governance docs for contribution, conduct, security,
  and decision records without asserting a license grant.

## Revisit Triggers

- Zach chooses a license.
- A first external contributor needs clear contribution/license terms.
- Packaging, publication, or downstream use requires a concrete license.
