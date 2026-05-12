PYTHON ?= 3.12
UV ?= uv
PYTHONPATH_DIRS := apps/api/src:apps/worker/src:apps/mcp-server/src:packages/python-sdk/src:packages/cli/src
PY := PYTHONPATH=$(PYTHONPATH_DIRS) $(UV) run --python $(PYTHON) --extra dev

.PHONY: test contracts lint format api worker web mcp init-db seed-fixtures reset-local

test:
	$(PY) pytest

contracts:
	$(PY) pytest tests/contracts

lint:
	$(PY) ruff check .

format:
	$(PY) ruff format .

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

reset-local:
	rm -rf .openabm
	$(MAKE) init-db
