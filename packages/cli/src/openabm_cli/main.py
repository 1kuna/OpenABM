from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer
from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore, ingest_fixture
from openabm_worker.agent_flow_smoke import (
    DEFAULT_AGENT_FLOW_INCIDENT,
    run_agent_flow_tool_smoke,
)
from openabm_worker.model_benchmark import (
    compare_model_runtime_benchmarks,
    run_model_runtime_benchmark,
)
from openabm_worker.model_runtime import model_provider_from_settings
from openabm_worker.novelty import run_novelty_clustering_benchmark
from openabm_worker.offline_eval import run_deterministic_eval
from openabm_worker.retention import run_retention_once
from openabm_worker.synthetic_pilot import (
    DEFAULT_PROJECT_ID,
    DEFAULT_SEED,
    DEFAULT_TRACE_COUNT,
    SyntheticPilotConfig,
    run_synthetic_pilot,
)
from rich.console import Console

ROOT = Path(__file__).resolve().parents[4]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"

app = typer.Typer(no_args_is_help=True)
bench_app = typer.Typer(no_args_is_help=True)
worker_app = typer.Typer(no_args_is_help=True)
console = Console()
app.add_typer(bench_app, name="bench")
app.add_typer(worker_app, name="worker")


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


@app.command("synthetic-pilot")
def synthetic_pilot(
    project_id: Annotated[
        str,
        typer.Option(help="Project id to populate with synthetic pilot data."),
    ] = DEFAULT_PROJECT_ID,
    trace_count: Annotated[
        int,
        typer.Option(help="Number of synthetic real-world-style traces to generate."),
    ] = DEFAULT_TRACE_COUNT,
    seed: Annotated[
        int,
        typer.Option(help="Deterministic synthetic data seed."),
    ] = DEFAULT_SEED,
    output: Annotated[
        Path,
        typer.Option(help="Directory for report.json, fixtures.json, and summary.md."),
    ] = Path(".openabm/synthetic-pilot/latest"),
    use_model: Annotated[
        bool,
        typer.Option("--use-model/--no-use-model", help="Run optional local model semantic lanes."),
    ] = False,
    chat_model: Annotated[
        str | None,
        typer.Option(help="Optional chat model override for local LM Studio runs."),
    ] = None,
    model_base_url: Annotated[
        str,
        typer.Option(help="OpenAI-compatible model base URL."),
    ] = "http://127.0.0.1:1234/v1",
    max_model_cases: Annotated[
        int,
        typer.Option(help="Maximum failure traces used in optional model lanes."),
    ] = 4,
) -> None:
    settings = Settings.from_env()
    if use_model and chat_model:
        settings = replace(
            settings,
            model_mode="local",
            model_base_url=model_base_url,
            chat_model=chat_model,
            model_context_length=max(32768, settings.model_context_length),
            max_trace_tokens_for_judge=max(32768, settings.max_trace_tokens_for_judge),
        )
    store = SQLiteStore(settings.sqlite_path)
    provider = None
    if use_model:
        try:
            provider = model_provider_from_settings(settings)
        except Exception as exc:  # The report records this as a blocked model lane.
            console.print(
                {
                    "model_lane": "blocked",
                    "reason": str(exc),
                    "hint": (
                        "Set OPENABM_MODEL_MODE=local and OPENABM_CHAT_MODEL, "
                        "or pass --chat-model."
                    ),
                }
            )
    report = asyncio.run(
        run_synthetic_pilot(
            store,
            settings=settings,
            config=SyntheticPilotConfig(
                project_id=project_id,
                trace_count=trace_count,
                seed=seed,
                use_model=use_model,
                max_model_cases=max_model_cases,
                output_dir=output,
            ),
            model_provider=provider,
        )
    )
    console.print_json(json.dumps(report, sort_keys=True))


@bench_app.command("model-runtime")
def bench_model_runtime(
    fixtures: Annotated[str, typer.Option(help="Fixture set to benchmark.")] = "golden",
    provider: Annotated[str, typer.Option(help="Provider selection.")] = "configured-provider",
    output: Annotated[Path | None, typer.Option(help="Optional JSON output path.")] = None,
    compare_to: Annotated[
        Path | None,
        typer.Option(help="Existing benchmark JSON to compare."),
    ] = None,
    min_accuracy: Annotated[
        float,
        typer.Option(help="Minimum judge accuracy for promotion."),
    ] = 0.8,
    max_invalid_output_rate: Annotated[
        float,
        typer.Option(help="Maximum invalid-output rate before promotion is blocked."),
    ] = 0.0,
    max_citation_failure_rate: Annotated[
        float,
        typer.Option(help="Maximum citation-failure rate before promotion is blocked."),
    ] = 0.0,
) -> None:
    if fixtures != "golden":
        raise typer.BadParameter("Only the golden fixture set is available in the reference repo.")
    if provider != "configured-provider":
        raise typer.BadParameter("Only configured-provider is available in the reference CLI.")

    settings = Settings.from_env()
    corpus = json.loads(FIXTURE_PATH.read_text())
    model_config = {
        "provider": provider,
        "model_mode": settings.model_mode,
        "model_base_url": settings.model_base_url,
        "chat_model": settings.chat_model,
        "model_context_length": settings.model_context_length,
        "max_trace_tokens_for_judge": settings.max_trace_tokens_for_judge,
    }
    model_provider = model_provider_from_settings(settings)
    result = asyncio.run(
        run_model_runtime_benchmark(
            model_provider,
            fixtures=corpus["fixtures"],
            fixture_version=corpus["fixture_version"],
            model_config=model_config,
            token_budget=settings.max_trace_tokens_for_judge,
            min_accuracy=min_accuracy,
            max_invalid_output_rate=max_invalid_output_rate,
            max_citation_failure_rate=max_citation_failure_rate,
        )
    )
    if compare_to is not None:
        baseline = json.loads(compare_to.read_text())
        result["comparison"] = compare_model_runtime_benchmarks(baseline, result)
    text = json.dumps(result, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n")
    console.print_json(text)


@bench_app.command("agent-flow-smoke")
def bench_agent_flow_smoke(
    incident: Annotated[
        str,
        typer.Option(help="Agent incident prompt for the tool-call smoke."),
    ] = DEFAULT_AGENT_FLOW_INCIDENT,
    output: Annotated[Path | None, typer.Option(help="Optional JSON output path.")] = None,
) -> None:
    settings = Settings.from_env()
    model_provider = model_provider_from_settings(settings)
    result = asyncio.run(run_agent_flow_tool_smoke(model_provider, incident=incident))
    text = json.dumps(result, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n")
    console.print_json(text)


@bench_app.command("novelty-clustering")
def bench_novelty_clustering(
    fixtures: Annotated[str, typer.Option(help="Fixture set to benchmark.")] = "golden",
    output: Annotated[Path | None, typer.Option(help="Optional JSON output path.")] = None,
    min_labeled_recall: Annotated[
        float,
        typer.Option(help="Minimum recall over fixture-labeled behavior traces."),
    ] = 1.0,
) -> None:
    if fixtures != "golden":
        raise typer.BadParameter("Only the golden fixture set is available in the reference repo.")
    corpus = json.loads(FIXTURE_PATH.read_text())
    result = run_novelty_clustering_benchmark(
        corpus["fixtures"],
        min_labeled_recall=min_labeled_recall,
    )
    result["fixture_version"] = corpus["fixture_version"]
    text = json.dumps(result, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n")
    console.print_json(text)


@worker_app.command("retention-once")
def worker_retention_once(
    project_id: Annotated[
        str | None,
        typer.Option(help="Optional project id. Defaults to all projects."),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Apply active policies instead of dry-running."),
    ] = False,
    worker_id: Annotated[
        str,
        typer.Option(help="Worker heartbeat identifier."),
    ] = "local-retention-worker",
) -> None:
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    result = run_retention_once(
        store,
        project_id=project_id,
        dry_run=not apply,
        worker_id=worker_id,
    )
    console.print_json(json.dumps(result, sort_keys=True))


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
