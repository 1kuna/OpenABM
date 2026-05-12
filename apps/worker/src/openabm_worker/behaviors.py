from __future__ import annotations

from typing import Any

from openabm_worker.conditions import evaluate_condition_group


def backtest_behavior(
    behavior: dict[str, Any],
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
    scores_by_trace: dict[str, list[dict[str, Any]]],
    *,
    sample_limit: int = 10,
) -> dict[str, Any]:
    detector = behavior.get("detector", {})
    detector_type = detector.get("type")
    positives = []
    negatives = []
    unsupported = detector_type not in {"manual_label", "rule", "judge"}

    for trace in traces:
        spans = spans_by_trace.get(trace["trace_id"], [])
        scores = scores_by_trace.get(trace["trace_id"], [])
        evaluation = evaluate_behavior_detector(behavior, trace, spans, scores)
        example = {
            "trace_id": trace["trace_id"],
            "evidence_span_ids": evaluation["evidence_span_ids"],
            "reason": evaluation["reason"],
        }
        if evaluation["matched"]:
            positives.append(example)
        else:
            negatives.append(example)

    trace_count = len(traces)
    positive_count = len(positives)
    return {
        "status": "unsupported_detector" if unsupported else "succeeded",
        "behavior_id": behavior["behavior_id"],
        "detector_type": detector_type,
        "trace_count": trace_count,
        "positive_count": positive_count,
        "negative_count": len(negatives),
        "detection_rate": positive_count / trace_count if trace_count else 0,
        "positive_examples": positives[:sample_limit],
        "negative_examples": negatives[:sample_limit],
        "review_required": positive_count > 0,
        "unsupported_reason": (
            f"Detector type {detector_type!r} is not backtestable by the reference runner."
            if unsupported
            else None
        ),
        "cost": {"model_calls": 0, "model_tokens": 0},
    }


def evaluate_behavior_detector(
    behavior: dict[str, Any],
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    scores: list[dict[str, Any]],
) -> dict[str, Any]:
    detector = behavior.get("detector", {})
    detector_type = detector.get("type")
    if detector_type == "rule":
        return _evaluate_rule_detector(detector, trace, spans)
    if detector_type == "judge":
        return _evaluate_judge_detector(detector, scores)
    if detector_type == "manual_label":
        return _evaluate_manual_label_detector(detector, behavior, trace)
    return {
        "matched": False,
        "evidence_span_ids": [],
        "reason": "Detector type is not supported by deterministic backtesting.",
    }


def _evaluate_rule_detector(
    detector: dict[str, Any],
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
) -> dict[str, Any]:
    conditions = detector.get("conditions") or {"combine": "all", "items": []}
    scope = detector.get("scope", "span")
    match_semantics = detector.get("match_semantics", "any_match_is_behavior")

    if scope == "trace":
        result = evaluate_condition_group(
            conditions,
            {"trace": trace, "attributes": trace.get("attributes", {})},
        )
        return {
            "matched": result["passed"],
            "evidence_span_ids": [],
            "reason": (
                "Trace-level rule matched."
                if result["passed"]
                else "Trace-level rule missed."
            ),
        }

    matching_span_ids = []
    for span in spans:
        result = evaluate_condition_group(
            conditions,
            {"trace": trace, "span": span, "attributes": span.get("attributes", {})},
        )
        if result["passed"]:
            matching_span_ids.append(span["span_id"])

    if match_semantics == "no_match_is_behavior":
        matched = not matching_span_ids
        return {
            "matched": matched,
            "evidence_span_ids": [],
            "reason": (
                "No spans matched the rule, as configured."
                if matched
                else "Rule found spans, so the no-match detector did not fire."
            ),
        }

    return {
        "matched": bool(matching_span_ids),
        "evidence_span_ids": matching_span_ids,
        "reason": (
            "One or more spans matched the behavior rule."
            if matching_span_ids
            else "No spans matched the behavior rule."
        ),
    }


def _evaluate_judge_detector(
    detector: dict[str, Any],
    scores: list[dict[str, Any]],
) -> dict[str, Any]:
    judge_id = detector.get("judge_id")
    verdict = detector.get("verdict", "fail")
    matching_scores = [
        score
        for score in scores
        if score.get("judge_id") == judge_id
        and score.get("status") == "succeeded"
        and (score.get("value") or {}).get("verdict") == verdict
    ]
    evidence_span_ids = sorted(
        {
            span_id
            for score in matching_scores
            for span_id in score.get("evidence_span_ids", [])
        }
    )
    return {
        "matched": bool(matching_scores),
        "evidence_span_ids": evidence_span_ids,
        "reason": (
            f"Found {len(matching_scores)} matching judge scores."
            if matching_scores
            else "No matching judge scores found."
        ),
    }


def _evaluate_manual_label_detector(
    detector: dict[str, Any],
    behavior: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    expected_labels = set(detector.get("labels") or [behavior["name"]])
    trace_labels = set(trace.get("tags") or [])
    behavior_ids = trace.get("attributes", {}).get("openabm.behavior_ids") or []
    trace_labels.update(behavior_ids if isinstance(behavior_ids, list) else [behavior_ids])
    matched = bool(expected_labels & trace_labels)
    return {
        "matched": matched,
        "evidence_span_ids": [],
        "reason": "Trace label matched behavior." if matched else "Trace label did not match.",
    }
