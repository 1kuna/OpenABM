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
        expected_trace_assertions={
            "required_tools": ["order_lookup"],
            "forbidden_grounding_failures": ["unsupported"],
        },
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
    assert run["summary"]["assertion_status_counts"] == {"passed": 1}
    assert run["results"][0]["dataset_example_id"] == example["dataset_example_id"]
    assert run["results"][0]["assertion_results"]["status"] == "passed"
    assert store.list_eval_runs("proj_demo")[0]["eval_run_id"] == run["eval_run_id"]
    persisted_result = store.list_eval_results("proj_demo", run["eval_run_id"])[0]
    assert persisted_result["assertion_results"]["observed"]["tool_names"] == ["order_lookup"]
    assert persisted_result["scores"][0][
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


def test_eval_comparison_reports_assertion_and_behavior_distribution_changes(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "openabm.sqlite3")
    store.init_db()
    corpus = json.loads(FIXTURE_PATH.read_text())
    ingest_fixture(store, [corpus["fixtures"][0], corpus["fixtures"][1]])
    dataset = store.create_dataset("proj_demo", "Assertion comparison eval")
    happy_example = store.add_trace_to_dataset(
        "proj_demo",
        dataset["dataset_id"],
        "trace_happy_support",
    )
    wrong_tool_example = store.add_trace_to_dataset(
        "proj_demo",
        dataset["dataset_id"],
        "trace_wrong_tool",
        expected_trace_assertions={"forbidden_tools": ["order_lookup"]},
    )
    behavior = store.create_behavior(
        {
            "project_id": "proj_demo",
            "behavior_id": "behavior_wrong_tool",
            "name": "wrong_tool_for_refund",
            "description": "Refund workflow uses order lookup.",
            "severity": "high",
            "detector": {"type": "manual_label"},
            "status": "active",
        }
    )
    store.label_trace_behavior(
        "proj_demo",
        "trace_wrong_tool",
        behavior["behavior_id"],
        span_id="span_wrong_tool_order_lookup",
    )
    baseline = store.create_eval_run(
        "proj_demo",
        dataset["latest_version_id"],
        runner={"type": "in_process_function"},
        judges=[],
    )
    candidate = store.create_eval_run(
        "proj_demo",
        dataset["latest_version_id"],
        runner={"type": "in_process_function"},
        judges=[],
        baseline_eval_run_id=baseline["eval_run_id"],
    )
    store.record_eval_result(
        "proj_demo",
        baseline["eval_run_id"],
        happy_example["dataset_example_id"],
        status="succeeded",
        scores=[],
        offline_trace_id="trace_happy_support",
        assertion_results={"status": "passed", "failures": []},
    )
    store.record_eval_result(
        "proj_demo",
        candidate["eval_run_id"],
        wrong_tool_example["dataset_example_id"],
        status="failed",
        scores=[],
        offline_trace_id="trace_wrong_tool",
        assertion_results={"status": "failed", "failures": [{"type": "forbidden_tool_used"}]},
    )
    store.complete_eval_run("proj_demo", baseline["eval_run_id"], {"total_examples": 1})
    store.complete_eval_run("proj_demo", candidate["eval_run_id"], {"total_examples": 1})

    comparison = store.compare_eval_runs(
        "proj_demo",
        baseline["eval_run_id"],
        candidate["eval_run_id"],
    )

    assert comparison["new_assertion_failures"] == [wrong_tool_example["dataset_example_id"]]
    assert comparison["fixed_assertion_failures"] == []
    shift = comparison["behavior_distribution_shift"]
    assert shift["baseline"] == {}
    assert shift["candidate"]["behavior_wrong_tool"]["match_count"] == 1
    assert shift["candidate"]["behavior_wrong_tool"]["trace_ids"] == ["trace_wrong_tool"]
    assert shift["deltas"] == [
        {
            "behavior_id": "behavior_wrong_tool",
            "name": "wrong_tool_for_refund",
            "severity": "high",
            "baseline_match_count": 0,
            "candidate_match_count": 1,
            "match_count_delta": 1,
            "baseline_trace_ids": [],
            "candidate_trace_ids": ["trace_wrong_tool"],
            "status_count_delta": {"confirmed": 1},
        }
    ]
