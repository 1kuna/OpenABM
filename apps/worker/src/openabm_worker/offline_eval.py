from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from typing import Any

import httpx
from openabm_api.storage import SQLiteStore

from openabm_worker.eval_assertions import evaluate_trace_assertions
from openabm_worker.judges import run_deterministic_rule_judge, run_rubric_judge


def run_deterministic_eval(
    store: SQLiteStore,
    *,
    project_id: str,
    dataset_version_id: str,
    judges: list[dict[str, Any]],
    runner: dict[str, Any] | None = None,
    prompt_version_id: str | None = None,
    agent_config_version_id: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = runner or {"type": "in_process_function", "mode": "deterministic"}
    run = store.create_eval_run(
        project_id,
        dataset_version_id,
        runner=runner,
        judges=judges,
        prompt_version_id=prompt_version_id,
        agent_config_version_id=agent_config_version_id,
        runtime_context=runtime_context,
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
        assertion_results = _evaluate_example_assertions(example, spans)
        result_status = "failed" if _assertions_failed(assertion_results) else (
            "succeeded" if scores or assertion_results else "skipped"
        )

        results.append(
            store.record_eval_result(
                project_id,
                run["eval_run_id"],
                example["dataset_example_id"],
                status=result_status,
                scores=scores,
                offline_trace_id=trace_id,
                latency_ms=sum(score.get("latency_ms") or 0 for score in scores),
                assertion_results=assertion_results,
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
    agent_config_version_id: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = runner or {"type": "in_process_function", "mode": "mixed"}
    run = store.create_eval_run(
        project_id,
        dataset_version_id,
        runner=runner,
        judges=judges,
        baseline_eval_run_id=baseline_eval_run_id,
        prompt_version_id=prompt_version_id,
        agent_config_version_id=agent_config_version_id,
        runtime_context=runtime_context,
    )
    results = []
    unsupported_judge_ids = []
    llm_calls = 0

    for example in store.list_dataset_examples_by_version(project_id, dataset_version_id):
        resolved = await _resolve_offline_trace(store, project_id, example, runner)
        if resolved["status"] != "succeeded":
            results.append(
                store.record_eval_result(
                    project_id,
                    run["eval_run_id"],
                    example["dataset_example_id"],
                    status=resolved["status"],
                    scores=[],
                    offline_trace_id=resolved.get("offline_trace_id"),
                    latency_ms=resolved.get("latency_ms"),
                    cost={"runner_error": resolved.get("error")} if resolved.get("error") else None,
                )
            )
            continue
        trace_id = resolved["offline_trace_id"]

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
                    cost={"runner_error": "offline trace was not found after runner execution"},
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
        assertion_results = _evaluate_example_assertions(example, spans)
        result_status = "failed" if _assertions_failed(assertion_results) else (
            "succeeded" if scores or assertion_results else "skipped"
        )

        results.append(
            store.record_eval_result(
                project_id,
                run["eval_run_id"],
                example["dataset_example_id"],
                status=result_status,
                scores=scores,
                offline_trace_id=trace_id,
                latency_ms=(resolved.get("latency_ms") or 0)
                + sum(score.get("latency_ms") or 0 for score in scores),
                assertion_results=assertion_results,
            )
        )

    summary = _summarize_results(results, unsupported_judge_ids)
    summary["llm_calls"] = llm_calls
    completed = store.complete_eval_run(project_id, run["eval_run_id"], summary)
    return {**completed, "results": results}


async def _resolve_offline_trace(
    store: SQLiteStore,
    project_id: str,
    example: dict[str, Any],
    runner: dict[str, Any],
) -> dict[str, Any]:
    trace_id = example.get("source_trace_id")
    if not trace_id:
        return {"status": "skipped", "offline_trace_id": None}
    source_trace = store.get_trace(project_id, trace_id)
    if source_trace is None:
        return {"status": "failed", "offline_trace_id": trace_id, "error": "source trace not found"}
    source_spans = store.list_spans(project_id, trace_id)
    runner_type = runner.get("type", "in_process_function")
    if runner_type == "in_process_function":
        return {"status": "succeeded", "offline_trace_id": trace_id, "latency_ms": 0}
    packet = {
        "project_id": project_id,
        "dataset_example": example,
        "source_trace": source_trace,
        "source_spans": source_spans,
    }
    started = time.perf_counter()
    if runner_type == "command":
        resolved = _run_command_runner(runner, packet)
    elif runner_type == "http_endpoint":
        resolved = await _run_http_runner(runner, packet)
    else:
        return {
            "status": "skipped",
            "offline_trace_id": trace_id,
            "error": f"unsupported runner type: {runner_type}",
        }
    latency_ms = int((time.perf_counter() - started) * 1000)
    if resolved["status"] != "succeeded":
        return {**resolved, "latency_ms": latency_ms}
    return _ingest_runner_output(store, project_id, resolved["output"], latency_ms=latency_ms)


def _run_command_runner(runner: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    command = runner.get("command")
    if not command:
        return {"status": "failed", "error": "command runner requires command"}
    args = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in (runner.get("environment") or {}).items()})
    try:
        completed = subprocess.run(
            args,
            input=json.dumps(packet, sort_keys=True) + "\n",
            text=True,
            capture_output=True,
            timeout=runner.get("timeout_seconds"),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "failed", "error": f"command runner timed out: {exc}"}
    if completed.returncode != 0:
        return {
            "status": "failed",
            "error": "command runner exited non-zero",
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        }
    try:
        return {"status": "succeeded", "output": _parse_runner_output(completed.stdout, runner)}
    except ValueError as exc:
        return {"status": "failed", "error": str(exc), "stdout": completed.stdout}


async def _run_http_runner(runner: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    endpoint = runner.get("url") or runner.get("endpoint")
    if not endpoint:
        return {"status": "failed", "error": "http_endpoint runner requires url"}
    try:
        async with httpx.AsyncClient(timeout=runner.get("timeout_seconds")) as client:
            response = await client.post(str(endpoint), json=packet)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"status": "failed", "error": str(exc)}
    try:
        return {"status": "succeeded", "output": response.json()}
    except ValueError as exc:
        return {"status": "failed", "error": f"http runner returned invalid JSON: {exc}"}


def _parse_runner_output(stdout: str, runner: dict[str, Any]) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("runner produced no output")
    output_format = runner.get("output_format", "json")
    if output_format == "jsonl":
        text = [line for line in text.splitlines() if line.strip()][-1]
    if output_format not in {"json", "jsonl"}:
        raise ValueError(f"unsupported runner output_format: {output_format}")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("runner output must be a JSON object")
    return parsed


def _ingest_runner_output(
    store: SQLiteStore,
    project_id: str,
    output: dict[str, Any],
    *,
    latency_ms: int,
) -> dict[str, Any]:
    if isinstance(output.get("offline_trace_id"), str):
        return {
            "status": "succeeded",
            "offline_trace_id": output["offline_trace_id"],
            "latency_ms": latency_ms,
        }
    trace = output.get("trace")
    spans = output.get("spans") or []
    if not isinstance(trace, dict) or not isinstance(spans, list):
        return {
            "status": "failed",
            "offline_trace_id": None,
            "latency_ms": latency_ms,
            "error": "runner output must include offline_trace_id or trace plus spans",
        }
    trace = {**trace, "project_id": project_id}
    store.upsert_trace(trace)
    for span in spans:
        if not isinstance(span, dict):
            return {
                "status": "failed",
                "offline_trace_id": trace["trace_id"],
                "latency_ms": latency_ms,
                "error": "runner spans must be JSON objects",
            }
        store.upsert_span({**span, "project_id": project_id, "trace_id": trace["trace_id"]})
    return {
        "status": "succeeded",
        "offline_trace_id": trace["trace_id"],
        "latency_ms": latency_ms,
    }


def _summarize_results(
    results: list[dict[str, Any]],
    unsupported_judge_ids: list[str],
) -> dict[str, Any]:
    result_status_counts: dict[str, int] = {}
    verdict_counts: dict[str, int] = {}
    assertion_status_counts: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        result_status_counts[status] = result_status_counts.get(status, 0) + 1
        assertion_status = (result.get("assertion_results") or {}).get("status")
        if assertion_status:
            assertion_status_counts[str(assertion_status)] = (
                assertion_status_counts.get(str(assertion_status), 0) + 1
            )
        for score in result["scores"]:
            verdict = str((score.get("value") or {}).get("verdict", "unknown"))
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

    return {
        "total_examples": len(results),
        "result_status_counts": result_status_counts,
        "score_verdict_counts": verdict_counts,
        "assertion_status_counts": assertion_status_counts,
        "unsupported_judge_ids": sorted(set(unsupported_judge_ids)),
        "llm_calls": 0,
    }


def _evaluate_example_assertions(
    example: dict[str, Any],
    spans: list[dict[str, Any]],
) -> dict[str, Any]:
    assertions = example.get("expected_trace_assertions") or {}
    if not assertions:
        return {}
    return evaluate_trace_assertions(spans, assertions)


def _assertions_failed(assertion_results: dict[str, Any]) -> bool:
    return bool(assertion_results) and assertion_results.get("status") == "failed"
