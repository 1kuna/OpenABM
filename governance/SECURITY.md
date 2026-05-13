# Security Policy

OpenABM handles sensitive agent traces, prompts, outputs, tool calls, retrieval
results, and user feedback. Security work is product work, not an afterthought.

## Current Status

This repository contains a local reference implementation with API-key auth,
scoped permissions, local secret encryption, audit logs, retention/delete/export
paths, and a Docker Compose reference contract. It is not yet a hardened
multi-tenant production service; do not expose it to production secrets or
sensitive production telemetry until the deployment, identity, observability,
and incident-response adapters have been reviewed for that environment.

## Reporting

Until a public disclosure process is finalized, report suspected
vulnerabilities privately to the repository owner.

## Security Expectations

- API keys and service accounts are scoped by org/project.
- Secrets are referenced by secret refs, not copied into configs.
- Payload capture and redaction happen before export where configured.
- Code judges receive no secrets by default.
- Delete/export/retention operations preserve auditability without retaining
  disallowed payload content.
