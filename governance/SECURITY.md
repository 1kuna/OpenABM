# Security Policy

OpenABM handles sensitive agent traces, prompts, outputs, tool calls, retrieval
results, and user feedback. Security work is product work, not an afterthought.

## Current Status

This repository is in initial scaffold state. Do not use it for production
secrets or sensitive production telemetry yet.

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

