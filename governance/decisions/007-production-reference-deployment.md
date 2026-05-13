# DR-007: Production Reference Deployment

Status: provisional-reference-contract

Date: 2026-05-13

## Context

OpenABM needs a self-hostable deployment path that proves the reference stack can
run outside a developer shell without turning the local reference implementation
into a claim of production-scale managed-service readiness.

## Contract

The deployment reference must provide:

- API, web, and worker services;
- persistent database and payload storage;
- explicit environment configuration for API keys, secret encryption, CORS, and
  local model endpoints;
- health, readiness, metrics, and smoke-check paths;
- retention worker execution against the same store;
- no hidden hosted dependency in default local/self-hosted mode;
- clear adapter boundaries for external IdP, invite delivery, secret managers,
  observability exporters, and notification transports.

## Candidates

- Local process-only development stack.
- Docker Compose reference stack.
- Kubernetes or Helm reference deployment.
- Managed cloud-specific deployment recipes.

## Workloads

- Build API and web images in CI.
- Validate Docker Compose configuration in CI.
- Run local API/web/worker health and readiness smoke checks.
- Preserve SQLite/payload state across container restarts.
- Configure LM Studio local model access from containers.

## Decision

Use Docker Compose as the production-reference deployment contract for the
current local reference implementation. The reference stack includes:

- FastAPI API container;
- retention worker container;
- static web container served through nginx;
- persistent Docker volume for SQLite and payload objects;
- configurable CORS origins;
- health/readiness checks and `scripts/deployment_smoke.py`.

Keep Kubernetes, external database/object-store topologies, external IdP, SMTP,
production secret managers, and observability exporters as adapter work until
pilot deployments produce concrete requirements.

## Evidence

- `.github/workflows/ci.yml` runs a deployment-contract job that validates
  `deploy/compose.yaml` and builds API/web images.
- `make deploy-config-check` validates the Compose contract locally.
- `docs/deployment.md` documents bringup, smoke check, secret/CORS settings, and
  LM Studio local model configuration.
- `IMPLEMENTATION_PROGRESS.md` records repeated local and GitHub deployment
  contract passes after implementation slices.

## Known Limitations

- The reference stack is not a multi-node production topology.
- SQLite remains the local reference storage path, not a high-scale storage
  commitment.
- External deployment supervision and managed observability exporters remain
  integration work.

## Revisit Triggers

- A pilot deployment needs managed database/object storage or multi-node
  availability.
- Operator smoke checks reveal container lifecycle or volume issues.
- External identity, email, secret-manager, observability, or notification
  requirements become concrete enough to implement and test.
- A Kubernetes/Helm or cloud-specific deployment can satisfy the same contracts
  with lower operator friction.
