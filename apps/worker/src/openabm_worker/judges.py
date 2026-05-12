from __future__ import annotations

from typing import Any

from openabm_api.ids import new_id
from openabm_api.time import utc_now

from openabm_worker.conditions import evaluate_condition_group


def validate_judge_output(
    output: dict[str, Any],
    *,
    trace_id: str,
    judge_id: str,
    judge_version_id: str | None,
    preserved_span_ids: set[str],
    require_span_citations: bool,
) -> dict[str, Any]:
    evidence = list(output.get("evidence_span_ids") or [])
    if require_span_citations and not evidence:
        return _invalid(trace_id, judge_id, judge_version_id, "missing_citations")
    if any(span_id not in preserved_span_ids for span_id in evidence):
        return _invalid(trace_id, judge_id, judge_version_id, "invalid_citation")

    verdict = output.get("verdict")
    if verdict not in {"pass", "fail", "unsure"}:
        return _invalid(trace_id, judge_id, judge_version_id, "invalid_verdict")

    return {
        "score_id": new_id("score"),
        "trace_id": trace_id,
        "span_id": None,
        "judge_id": judge_id,
        "judge_version_id": judge_version_id,
        "status": "succeeded",
        "value": {"verdict": verdict, "score": output.get("score")},
        "confidence": output.get("confidence"),
        "reasoning": output.get("reasoning"),
        "evidence_span_ids": evidence,
        "failure_mode": output.get("failure_mode"),
        "cost": None,
        "latency_ms": None,
        "created_at": utc_now(),
    }


def run_deterministic_rule_judge(
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    judge: dict[str, Any],
) -> dict[str, Any]:
    rule = judge["rule"]
    span_matches = []
    for span in spans:
        context = {"trace": trace, "span": span, "attributes": span.get("attributes", {})}
        result = evaluate_condition_group(rule["conditions"], context)
        if result["passed"]:
            span_matches.append(span["span_id"])

    if rule.get("match_semantics") == "any_match_is_pass":
        passed = bool(span_matches)
    else:
        passed = not span_matches
    verdict = "pass" if passed else "fail"
    return {
        "score_id": new_id("score"),
        "trace_id": trace["trace_id"],
        "span_id": None,
        "judge_id": judge["judge_id"],
        "judge_version_id": judge.get("judge_version_id"),
        "status": "succeeded",
        "value": {"verdict": verdict, "score": 1.0 if passed else 0.0},
        "confidence": 1.0,
        "reasoning": "Deterministic rule evaluation completed.",
        "evidence_span_ids": span_matches,
        "failure_mode": None if passed else rule.get("failure_mode"),
        "cost": None,
        "latency_ms": 0,
        "created_at": utc_now(),
    }


def _invalid(
    trace_id: str,
    judge_id: str,
    judge_version_id: str | None,
    failure_mode: str,
) -> dict[str, Any]:
    return {
        "score_id": new_id("score"),
        "trace_id": trace_id,
        "span_id": None,
        "judge_id": judge_id,
        "judge_version_id": judge_version_id,
        "status": "invalid_output",
        "value": None,
        "confidence": None,
        "reasoning": None,
        "evidence_span_ids": [],
        "failure_mode": failure_mode,
        "cost": None,
        "latency_ms": None,
        "created_at": utc_now(),
    }
