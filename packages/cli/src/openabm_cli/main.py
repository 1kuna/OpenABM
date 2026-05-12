from __future__ import annotations

import json
from pathlib import Path

import typer
from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore, ingest_fixture
from openabm_worker.offline_eval import run_deterministic_eval
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


@app.command("demo-eval")
def demo_eval() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    corpus = json.loads(FIXTURE_PATH.read_text())
    ingest_fixture(store, corpus["fixtures"])
    dataset = store.create_dataset("proj_demo", "Demo refund eval")
    store.add_trace_to_dataset(
        "proj_demo",
        dataset["dataset_id"],
        "trace_wrong_tool",
        labels=["wrong_tool_for_refund"],
        created_from="eval",
    )
    run = run_deterministic_eval(
        store,
        project_id="proj_demo",
        dataset_version_id=dataset["latest_version_id"],
        judges=[wrong_tool_demo_judge()],
    )
    console.print(
        {
            "eval_run_id": run["eval_run_id"],
            "dataset_version_id": run["dataset_version_id"],
            "summary": run["summary"],
        }
    )


def wrong_tool_demo_judge() -> dict[str, object]:
    return {
        "judge_id": "judge_wrong_tool_for_refund",
        "judge_type": "deterministic_rule",
        "name": "Wrong refund tool detector",
        "rule": {
            "match_semantics": "any_match_is_fail",
            "failure_mode": "wrong_tool_for_refund",
            "conditions": {
                "combine": "all",
                "items": [
                    {"field": "attributes.tool.name", "op": "eq", "value": "order_lookup"}
                ],
            },
        },
    }


if __name__ == "__main__":
    app()
