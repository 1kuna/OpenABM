# Production Reference Deployment

OpenABM's reference deployment is intentionally small: one API container, one
retention worker container, one static web container, and a persistent SQLite
volume for the local reference store and payload objects.

This is a self-hosting contract, not a claim that the reference stack is already
a hardened multi-tenant cloud service. External IdP, vendor email delivery,
external secret managers, and production observability exporters remain adapter
work.

## Services

- `api`: FastAPI service on port `8787`, with `/health`, `/ready`, and
  `/metrics`.
- `worker`: retention worker loop using the same database and payload volume.
- `web`: static Vite build served through nginx on port `8080`.
- `openabm-data`: persistent Docker volume mounted at `/data`.

## Bringup

```bash
cp deploy/production.env.example .env.production
docker compose --env-file .env.production -f deploy/compose.yaml up --build
```

The web UI is available at `http://localhost:8080`; the default API base URL in
the UI should point at `http://127.0.0.1:8787` or `http://localhost:8787`.

Before exposing a deployment beyond localhost, replace `OPENABM_DEV_API_KEY` and
`OPENABM_SECRET_KEY`, keep `OPENABM_AUTH_MODE=local`, and set
`OPENABM_CORS_ORIGINS` to the exact allowed web origins.

## Smoke Check

```bash
OPENABM_API_BASE_URL=http://127.0.0.1:8787 \
OPENABM_API_KEY="$OPENABM_DEV_API_KEY" \
python scripts/deployment_smoke.py
```

The smoke check verifies health, readiness, authenticated project listing, auth
contract visibility, and ops status.

## Local Model Runtime

For LM Studio on macOS, keep:

```text
OPENABM_MODEL_BASE_URL=http://host.docker.internal:1234/v1
OPENABM_CHAT_MODEL=qwen3.5-9b-mlx
OPENABM_MODEL_CONTEXT_LENGTH=262144
OPENABM_MAX_TRACE_TOKENS_FOR_JUDGE=262144
```

Model mode can remain `disabled` until you intentionally enable model-backed
features. When enabling local model features, keep context at or above `32768`
and do not add generation timeouts.
