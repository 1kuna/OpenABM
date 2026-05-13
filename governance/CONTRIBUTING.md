# Contributing To OpenABM

OpenABM is contract-first. Contributors should preserve public schemas,
OpenAPI operations, fixture behavior, provenance, and acceptance tests before
swapping implementation details.

## Contributor Flow

1. Identify the contract being implemented or changed.
2. Add or update schemas, OpenAPI operations, fixtures, and tests first.
3. Implement behind the relevant adapter or service boundary.
4. Run the focused checks for that subsystem.
5. Update or add a decision record when an implementation choice becomes
   foundational.

## Product Boundaries

- Do not copy proprietary UI, docs, screenshots, schemas, examples, private
  APIs, or implementation behavior from vendors.
- Use synthetic or explicitly licensed examples and fixtures.
- Preserve provenance for artifacts derived from traces, spans, scores, prompts,
  datasets, evals, behaviors, and feedback.
- Local development must be able to run with external model calls disabled.

## Tests

Run the local reference gates before submitting changes:

```bash
make lint
make test
make contracts
make ci
make deploy-config-check
```
