from __future__ import annotations

from typing import Any


def detect_novel_behavior_candidates(
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
    known_behaviors: list[dict[str, Any]],
) -> dict[str, Any]:
    known_names = {
        behavior["name"]
        for behavior in known_behaviors
        if behavior.get("status") == "active"
    }
    grouped: dict[str, dict[str, Any]] = {}
    for trace in traces:
        if trace.get("status") not in {"error", "failed"}:
            continue
        signature = _trace_signature(trace, spans_by_trace.get(trace["trace_id"], []))
        if signature in known_names:
            continue
        group = grouped.setdefault(
            signature,
            {
                "name": signature,
                "description": f"Recurring failure signature: {signature}",
                "representative_positive_traces": [],
                "representative_negative_traces": [],
                "severity": "medium",
                "frequency": 0,
                "uncertainty": "deterministic exact-signature grouping",
            },
        )
        group["frequency"] += 1
        group["representative_positive_traces"].append(trace["trace_id"])

    candidates = sorted(
        grouped.values(),
        key=lambda item: item["frequency"],
        reverse=True,
    )
    return {
        "new_behavior_candidates": candidates,
        "uncertainty": (
            "Deterministic novelty groups exact error/tool signatures; semantic grouping "
            "can be layered behind the model provider."
        ),
    }


def _trace_signature(trace: dict[str, Any], spans: list[dict[str, Any]]) -> str:
    error_type = trace.get("attributes", {}).get("error.type")
    tool_names = [
        span.get("attributes", {}).get("tool.name")
        for span in spans
        if span.get("attributes", {}).get("tool.name")
    ]
    if error_type:
        return f"error_{error_type}"
    if tool_names:
        return "tool_sequence_" + "_then_".join(str(name) for name in tool_names[:3])
    return f"status_{trace.get('status', 'unknown')}"
