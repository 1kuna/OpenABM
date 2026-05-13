from __future__ import annotations

from typing import Any

from openabm_api.storage import SQLiteStore

from openabm_worker.judges import run_deterministic_rule_judge, run_rubric_judge


def run_deterministic_eval(
    store: SQLiteStore,
    *,
    project_id: str,
    dataset_version_id: str,
    judges: list[dict[str, Any]],
    runner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = runner or {"type": "in_process_function", "mode": "deterministic"}
    run = store.create_eval_run(
        project_id,
        dataset_version_id,
        runner=runner,
        judges=judges,
    )
    results = []
    unsupported_judge_ids = []

    for example in store.list_dataset_examples_by_version(project_id, dataset_version_id):
        trace_id = example.get("source_trace_id")
        if not trace_id:
            results.append(
                store.record_eval_result(
                    project_id,
                    run["eval_run_id"],
                    example["dataset_example_id"],
                    status="skipped",
                    scores=[],
                    offline_trace_id=None,
                )
            )
            continue

        trace = store.get_trace(project_id, trace_id)
        if trace is None:
            results.append(
                store.record_eval_result(
                    project_id,
                    run["eval_run_id"],
                    example["dataset_example_id"],
                    status="failed",
                    scores=[],
                    offline_trace_id=trace_id,
                )
            )
            continue

        spans = store.list_spans(project_id, trace_id)
        scores = []
        for judge in judges:
            if judge.get("judge_type") != "deterministic_rule" or "rule" not in judge:
                unsupported_judge_ids.append(judge.get("judge_id", "unknown"))
                continue
            scores.append(run_deterministic_rule_judge(trace, spans, judge))

        results.append(
            store.record_eval_result(
                project_id,
                run["eval_run_id"],
                example["dataset_example_id"],
                status="succeeded" if scores else "skipped",
                scores=scores,
                offline_trace_id=trace_id,
                latency_ms=sum(score.get("latency_ms") or 0 for score in scores),
            )
        )

    summary = _summarize_results(results, unsupported_judge_ids)
    completed = store.complete_eval_run(project_id, run["eval_run_id"], summary)
    return {**completed, "results": results}


async def run_eval(
    store: SQLiteStore,
    *,
    project_id: str,
    dataset_version_id: str,
    judges: list[dict[str, Any]],
    runner: dict[str, Any] | None = None,
    provider: Any | None = None,
    token_budget: int = 262144,
    baseline_eval_run_id: str | None = None,
    prompt_version_id: str | None = None,
) -> dict[str, Any]:
    runner = runner or {"type": "in_process_function", "mode": "mixed"}
    run = store.create_eval_run(
        project_id,
        dataset_version_id,
        runner=runner,
        judges=judges,
        baseline_eval_run_id=baseline_eval_run_id,
        prompt_version_id=prompt_version_id,
    )
    results = []
    unsupported_judge_ids = []
    llm_calls = 0

    for example in store.list_dataset_examples_by_version(project_id, dataset_version_id):
        trace_id = example.get("source_trace_id")
        if not trace_id:
            results.append(
                store.record_eval_result(
                    project_id,
                    run["eval_run_id"],
                    example["dataset_example_id"],
                    status="skipped",
                    scores=[],
                    offline_trace_id=None,
                )
            )
            continue

        trace = store.get_trace(project_id, trace_id)
        if trace is None:
            results.append(
                store.record_eval_result(
                    project_id,
                    run["eval_run_id"],
                    example["dataset_example_id"],
                    status="failed",
                    scores=[],
                    offline_trace_id=trace_id,
                )
            )
            continue

        spans = store.list_spans(project_id, trace_id)
        scores = []
        for judge in judges:
            if judge.get("judge_type") == "deterministic_rule" and "rule" in judge:
                scores.append(run_deterministic_rule_judge(trace, spans, judge))
            elif judge.get("judge_type") == "rubric_judge":
                if provider is None:
                    unsupported_judge_ids.append(judge.get("judge_id", "unknown"))
                    continue
                scores.append(
                    await run_rubric_judge(
                        provider,
                        trace,
                        spans,
                        judge,
                        token_budget=token_budget,
                    )
                )
                llm_calls += 1
            else:
                unsupported_judge_ids.append(judge.get("judge_id", "unknown"))

        results.append(
            store.record_eval_result(
                project_id,
                run["eval_run_id"],
                example["dataset_example_id"],
                status="succeeded" if scores else "skipped",
                scores=scores,
                offline_trace_id=trace_id,
                latency_ms=sum(score.get("latency_ms") or 0 for score in scores),
            )
        )

    summary = _summarize_results(results, unsupported_judge_ids)
    summary["llm_calls"] = llm_calls
    completed = store.complete_eval_run(project_id, run["eval_run_id"], summary)
    return {**completed, "results": results}


def _summarize_results(
    results: list[dict[str, Any]],
    unsupported_judge_ids: list[str],
) -> dict[str, Any]:
    result_status_counts: dict[str, int] = {}
    verdict_counts: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        result_status_counts[status] = result_status_counts.get(status, 0) + 1
        for score in result["scores"]:
            verdict = str((score.get("value") or {}).get("verdict", "unknown"))
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

    return {
        "total_examples": len(results),
        "result_status_counts": result_status_counts,
        "score_verdict_counts": verdict_counts,
        "unsupported_judge_ids": sorted(set(unsupported_judge_ids)),
        "llm_calls": 0,
    }
