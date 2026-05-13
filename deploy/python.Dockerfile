FROM python:3.12-slim

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="apps/api/src:apps/worker/src:apps/mcp-server/src:packages/python-sdk/src:packages/cli/src"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN python -m pip install --no-cache-dir uv \
  && uv sync --frozen --no-dev

COPY apps ./apps
COPY evals ./evals
COPY governance ./governance
COPY infra ./infra
COPY packages ./packages
COPY scripts ./scripts

EXPOSE 8787

CMD ["uvicorn", "openabm_api.main:app", "--host", "0.0.0.0", "--port", "8787"]
