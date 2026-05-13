import asyncio
import json
import sys
from pathlib import Path

from openabm_api.storage import SQLiteStore, ingest_fixture
from openabm_worker.offline_eval import run_deterministic_eval, run_eval

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"


def test_deterministic_offline_eval_persists_run_and_results(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "openabm.sqlite3")
    store.init_db()
    corpus = json.loads(FIXTURE_PATH.read_text())
    ingest_fixture(store, corpus["fixtures"])
    dataset = store.create_dataset("proj_demo", "Refund eval")
    example = store.add_trace_to_dataset(
        "proj_demo",
        dataset["dataset_id"],
        "trace_wrong_tool",
        labels=["wrong_tool_for_refund"],
    )

    run = run_deterministic_eval(
        store,
        project_id="proj_demo",
        dataset_version_id=dataset["latest_version_id"],
        judges=[
            {
                "judge_id": "judge_wrong_tool_for_refund",
                "judge_type": "deterministic_rule",
                "rule": {
                    "match_semantics": "any_match_is_fail",
                    "failure_mode": "wrong_tool_for_refund",
                    "conditions": {
                        "combine": "all",
                        "items": [
                            {
                                "field": "attributes.tool.name",
                                "op": "eq",
                                "value": "order_lookup",
                            }
                        ],
                    },
                },
            }
        ],
    )

    assert run["status"] == "completed"
    assert run["summary"]["total_examples"] == 1
    assert run["summary"]["score_verdict_counts"] == {"fail": 1}
    assert run["results"][0]["dataset_example_id"] == example["dataset_example_id"]
    assert store.list_eval_runs("proj_demo")[0]["eval_run_id"] == run["eval_run_id"]
    assert store.list_eval_results("proj_demo", run["eval_run_id"])[0]["scores"][0][
        "failure_mode"
    ] == "wrong_tool_for_refund"


def test_command_runner_ingests_offline_trace_before_scoring(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "openabm.sqlite3")
    store.init_db()
    corpus = json.loads(FIXTURE_PATH.read_text())
    ingest_fixture(store, [corpus["fixtures"][1]])
    dataset = store.create_dataset("proj_demo", "Command runner eval")
    store.add_trace_to_dataset(
        "proj_demo",
        dataset["dataset_id"],
        "trace_wrong_tool",
        labels=["wrong_tool_for_refund"],
    )
    script = """
import json
import sys

packet = json.loads(sys.stdin.read())
trace = packet["source_trace"]
spans = packet["source_spans"]
span_map = {
    "span_wrong_tool_root": "span_command_runner_root",
    "span_wrong_tool_order_lookup": "span_command_runner_order_lookup",
}
trace["trace_id"] = "trace_command_runner"
trace["root_span_id"] = "span_command_runner_root"
for span in spans:
    span["trace_id"] = "trace_command_runner"
    span["span_id"] = span_map.get(span["span_id"], span["span_id"])
    if span.get("parent_span_id") in span_map:
        span["parent_span_id"] = span_map[span["parent_span_id"]]
print(json.dumps({"trace": trace, "spans": spans}))
"""

    run = asyncio.run(
        run_eval(
            store,
            project_id="proj_demo",
            dataset_version_id=dataset["latest_version_id"],
            runner={
                "type": "command",
                "command": [sys.executable, "-c", script],
                "input_format": "json",
                "output_format": "json",
            },
            judges=[
                {
                    "judge_id": "judge_wrong_tool_for_refund",
                    "judge_type": "deterministic_rule",
                    "rule": {
                        "match_semantics": "any_match_is_fail",
                        "failure_mode": "wrong_tool_for_refund",
                        "conditions": {
                            "combine": "all",
                            "items": [
                                {
                                    "field": "attributes.tool.name",
                                    "op": "eq",
                                    "value": "order_lookup",
                                }
                            ],
                        },
                    },
                }
            ],
        )
    )

    assert run["status"] == "completed"
    assert run["results"][0]["offline_trace_id"] == "trace_command_runner"
    assert run["summary"]["score_verdict_counts"] == {"fail": 1}
    assert store.get_trace("proj_demo", "trace_command_runner")["root_span_id"] == (
        "span_command_runner_root"
    )
    spans = store.list_spans("proj_demo", "trace_command_runner")
    assert {span["span_id"] for span in spans} >= {
        "span_command_runner_root",
        "span_command_runner_order_lookup",
    }
