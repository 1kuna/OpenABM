PYTHON ?= 3.12
UV ?= uv
PYTHONPATH_DIRS := apps/api/src:apps/worker/src:apps/mcp-server/src:packages/python-sdk/src:packages/cli/src
PY := PYTHONPATH=$(PYTHONPATH_DIRS) $(UV) run --python $(PYTHON) --extra dev

.PHONY: test contracts lint format api worker web mcp init-db seed-fixtures demo-eval reset-local openapi-check docs-link-check web-build ci

test:
	$(PY) pytest

contracts:
	$(PY) pytest tests/contracts

lint:
	$(PY) ruff check .

format:
	$(PY) ruff format .

openapi-check:
	$(PY) python -m json.tool packages/shared-types/openapi/openapi.json >/dev/null

docs-link-check:
	$(PY) python scripts/check_docs_links.py

web-build:
	npm --prefix apps/web run build

ci: lint test openapi-check docs-link-check web-build

api:
	$(PY) uvicorn openabm_api.main:app --reload --host 127.0.0.1 --port 8787

worker:
	$(PY) python -m openabm_worker.main

mcp:
	$(PY) python -m openabm_mcp.server

web:
	npm --prefix apps/web run dev -- --host 127.0.0.1

init-db:
	$(PY) python -m openabm_cli.main init-db

seed-fixtures:
	$(PY) python -m openabm_cli.main seed-fixtures

demo-eval:
	$(PY) python -m openabm_cli.main demo-eval

reset-local:
	rm -rf .openabm
	$(MAKE) init-db
