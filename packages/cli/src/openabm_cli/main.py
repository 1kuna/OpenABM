from __future__ import annotations

import json
from pathlib import Path

import typer
from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore, ingest_fixture
from rich.console import Console

ROOT = Path(__file__).resolve().parents[4]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("init-db")
def init_db() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    console.print(f"Initialized local OpenABM database at {settings.sqlite_path}")


@app.command("seed-fixtures")
def seed_fixtures() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    corpus = json.loads(FIXTURE_PATH.read_text())
    ingest_fixture(store, corpus["fixtures"])
    console.print(f"Seeded {len(corpus['fixtures'])} trace fixtures into {settings.sqlite_path}")


@app.command("status")
def status() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    projects = store.list_projects()
    console.print({"database": str(settings.sqlite_path), "projects": projects})


if __name__ == "__main__":
    app()

