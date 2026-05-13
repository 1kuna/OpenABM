from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
from typing import Any

from openabm_api.ids import new_id
from openabm_api.time import utc_now

from openabm_worker.judges import run_rubric_judge

BENCHMARK_JUDGE_ID = "bench_wrong_tool_for_refund"
BENCHMARK_BEHAVIOR_LABEL = "wrong_tool_for_refund"


def benchmark_config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()


async def run_model_runtime_benchmark(
    provider: Any,
    *,
    fixtures: list[dict[str, Any]],
    fixture_version: str,
    model_config: dict[str, Any],
    token_budget: int,
    min_accuracy: float = 0.8,
    max_invalid_output_rate: float = 0.0,
    max_citation_failure_rate: float = 0.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = utc_now()
    results = []
    total_latency_ms = 0.0
    max_latency_ms = 0.0
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    health = provider.health_check()

    for fixture in fixtures:
        item_started = time.perf_counter()
        try:
            score = await run_rubric_judge(
                provider,
                fixture["trace"],
                fixture["spans"],
                _benchmark_judge(),
                token_budget=token_budget,
            )
        except Exception as exc:
            score = {
                "status": "invalid_output",
                "value": None,
                "failure_mode": "provider_error",
                "evidence_span_ids": [],
                "cost": {"error_type": type(exc).__name__, "error": str(exc)},
            }
        latency_ms = (time.perf_counter() - item_started) * 1000
        total_latency_ms += latency_ms
        max_latency_ms = max(max_latency_ms, latency_ms)
        cost = score.get("cost") or {}
        usage = cost.get("usage") or {}
        for key in usage_totals:
            usage_totals[key] += int(usage.get(key) or 0)

        expected_verdict = _expected_verdict(fixture)
        actual_verdict = (score.get("value") or {}).get("verdict")
        preserved_span_ids = {span["span_id"] for span in fixture["spans"]}
        cited_span_ids = set(score.get("evidence_span_ids") or [])
        citation_valid = cited_span_ids <= preserved_span_ids
        structured_valid = score["status"] != "invalid_output"
        accurate = structured_valid and actual_verdict == expected_verdict
        context_failure = score.get("failure_mode") in {
            "context_packet_empty",
            "context_budget_exhausted",
        }
        results.append(
            {
                "fixture_name": fixture["name"],
                "trace_id": fixture["trace"]["trace_id"],
                "expected_verdict": expected_verdict,
                "actual_verdict": actual_verdict,
                "score_status": score["status"],
                "failure_mode": score.get("failure_mode"),
                "structured_valid": structured_valid,
                "citation_valid": citation_valid,
                "accurate": accurate,
                "evidence_span_ids": score.get("evidence_span_ids") or [],
                "latency_ms": latency_ms,
                "cost": cost,
                "context_failure": context_failure,
            }
        )

    metrics = _benchmark_metrics(results, total_latency_ms, max_latency_ms, started, usage_totals)
    blocking_reasons = _promotion_blockers(
        metrics,
        min_accuracy=min_accuracy,
        max_invalid_output_rate=max_invalid_output_rate,
        max_citation_failure_rate=max_citation_failure_rate,
    )
    return {
        "benchmark_run_id": new_id("model_benchmark"),
        "started_at": started_at,
        "completed_at": utc_now(),
        "provider_adapter": health.adapter_name,
        "model_identifier": _model_identifier(health, model_config),
        "config_hash": benchmark_config_hash(model_config),
        "config": model_config,
        "fixture_version": fixture_version,
        "metrics": metrics,
        "promotion_gate": {
            "status": "blocked" if blocking_reasons else "eligible",
            "blocking_reasons": blocking_reasons,
            "thresholds": {
                "min_accuracy": min_accuracy,
                "max_invalid_output_rate": max_invalid_output_rate,
                "max_citation_failure_rate": max_citation_failure_rate,
            },
        },
        "results": results,
    }


def compare_model_runtime_benchmarks(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    keys = [
        "judge_accuracy",
        "structured_output_validity_rate",
        "citation_validity_rate",
        "invalid_output_rate",
        "unsure_rate",
        "avg_latency_ms",
        "throughput_per_second",
        "context_failure_rate",
    ]
    deltas = {}
    for key in keys:
        deltas[key] = _number(candidate["metrics"].get(key)) - _number(
            baseline["metrics"].get(key)
        )
    return {
        "baseline_run_id": baseline.get("benchmark_run_id"),
        "candidate_run_id": candidate.get("benchmark_run_id"),
        "baseline_model_identifier": baseline.get("model_identifier"),
        "candidate_model_identifier": candidate.get("model_identifier"),
        "metric_deltas": deltas,
        "candidate_gate_status": candidate.get("promotion_gate", {}).get("status"),
    }


def _benchmark_judge() -> dict[str, Any]:
    return {
        "judge_id": BENCHMARK_JUDGE_ID,
        "judge_type": "rubric_judge",
        "name": "Wrong refund tool benchmark judge",
        "description": (
            "Evaluate only whether the trace shows a refund decision made with the "
            "wrong operational tool. This is not a general trace-quality, safety, "
            "or business-correctness judge."
        ),
        "require_span_citations": False,
        "rubric": {
            "pass": (
                "The trace uses a refund-policy appropriate tool, or the trace is "
                "well-formed and does not show a refund decision made with an "
                "unrelated operational tool. Unrelated failure modes pass this "
                "narrow benchmark judge."
            ),
            "fail": (
                "The trace includes evidence of a refund decision and shows order "
                "lookup or another unrelated/non-refund tool being used for that "
                "refund decision."
            ),
            "unsure": (
                "The trace is malformed or incomplete enough that the narrow "
                "wrong-refund-tool question cannot be judged."
            ),
        },
    }


def _expected_verdict(fixture: dict[str, Any]) -> str:
    labels = fixture.get("expected", {}).get("behavior_labels") or []
    if BENCHMARK_BEHAVIOR_LABEL in labels:
        return "fail"
    trace = fixture["trace"]
    if trace.get("status") == "incomplete" or "malformed" in trace.get("tags", []):
        return "unsure"
    return "pass"


def _benchmark_metrics(
    results: list[dict[str, Any]],
    total_latency_ms: float,
    max_latency_ms: float,
    started: float,
    usage_totals: dict[str, int],
) -> dict[str, Any]:
    total = len(results)
    invalid = sum(1 for result in results if not result["structured_valid"])
    citation_valid = sum(1 for result in results if result["citation_valid"])
    accurate = sum(1 for result in results if result["accurate"])
    unsure = sum(1 for result in results if result["actual_verdict"] == "unsure")
    context_failures = sum(1 for result in results if result["context_failure"])
    elapsed_seconds = max(time.perf_counter() - started, 0.000001)
    return {
        "total_fixtures": total,
        "structured_output_validity_rate": _rate(total - invalid, total),
        "citation_validity_rate": _rate(citation_valid, total),
        "judge_accuracy": _rate(accurate, total),
        "unsure_rate": _rate(unsure, total),
        "invalid_output_rate": _rate(invalid, total),
        "avg_latency_ms": total_latency_ms / total if total else 0.0,
        "max_latency_ms": max_latency_ms,
        "total_latency_ms": total_latency_ms,
        "throughput_per_second": total / elapsed_seconds,
        "memory_rss_mb": _max_rss_mb(),
        "context_failure_rate": _rate(context_failures, total),
        "cost": {"usage": usage_totals},
        "operator_review_preference_score": None,
    }


def _promotion_blockers(
    metrics: dict[str, Any],
    *,
    min_accuracy: float,
    max_invalid_output_rate: float,
    max_citation_failure_rate: float,
) -> list[str]:
    blockers = []
    if metrics["judge_accuracy"] < min_accuracy:
        blockers.append("judge_accuracy_below_threshold")
    if metrics["invalid_output_rate"] > max_invalid_output_rate:
        blockers.append("invalid_output_rate_above_threshold")
    citation_failure_rate = 1.0 - metrics["citation_validity_rate"]
    if citation_failure_rate > max_citation_failure_rate:
        blockers.append("citation_failure_rate_above_threshold")
    return blockers


def _model_identifier(health: Any, model_config: dict[str, Any]) -> str:
    details = getattr(health, "details", {}) or {}
    return str(
        model_config.get("chat_model")
        or details.get("chat_model")
        or model_config.get("model")
        or "unknown"
    )


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _max_rss_mb() -> float:
    rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return rss / 1024 / 1024
    return rss / 1024
