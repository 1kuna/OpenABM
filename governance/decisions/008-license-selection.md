# DR-008: License Selection

Status: accepted

Date: 2026-05-13

Updated: 2026-05-14

## Context

OpenABM is intended to be a public open-source project, but adding a license is
a legal/product choice that should be made by the repository owner rather than
silently selected by the implementation agent.

On 2026-05-14, Zach delegated the choice and said he did not have a strong
preference. The default should therefore optimize for low-friction public
reuse rather than a stronger commercial or network-copyleft strategy.

## Contract

The repository license must be explicit in a committed `LICENSE` file. Public
code, docs, schemas, examples, and assets must remain original OpenABM work.

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

Use MIT as the initial project license.

MIT is the shortest permissive option in the candidate set and fits Zach's
"I don't really care" direction without creating network-copyleft obligations
or a more detailed patent posture.

## Evidence

- The implementation spec requires owner-safe legal/IP boundaries and original
  public artifacts.
- Zach delegated the license choice on 2026-05-14.
- `LICENSE` now contains the MIT license text.
- The repository includes governance docs for contribution, conduct, security,
  and decision records without asserting a license grant.

## Revisit Triggers

- A contributor, downstream user, hosted-service plan, or patent posture requires
  Apache-2.0, AGPL, or dual-license reconsideration.
- A first external contributor needs clear contribution/license terms.
- Packaging, publication, or downstream use requires a concrete license.
