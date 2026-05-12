from __future__ import annotations

from collections import defaultdict
from typing import Any

from openabm_api.time import parse_utc, utc_now


def _span_order(span: dict[str, Any]) -> tuple[str, str]:
    return (span.get("started_at") or "", span.get("server_received_at") or "")


def reconstruct_trace(
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    incomplete_threshold_seconds: int = 300,
) -> dict[str, Any]:
    del incomplete_threshold_seconds
    spans_by_id = {span["span_id"]: span for span in spans}
    children_by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    missing_parent: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    incomplete_spans: list[str] = []

    for span in spans:
        parent_id = span.get("parent_span_id")
        if parent_id is None:
            roots.append(span)
        elif parent_id in spans_by_id:
            children_by_parent[parent_id].append(span)
        else:
            missing_parent.append(span)
            warnings.append(
                {
                    "type": "missing_parent",
                    "span_id": span["span_id"],
                    "parent_span_id": parent_id,
                }
            )

        started = parse_utc(span.get("started_at"))
        ended = parse_utc(span.get("ended_at"))
        if ended is None:
            incomplete_spans.append(span["span_id"])
        elif started and ended < started:
            warnings.append({"type": "unreliable_duration", "span_id": span["span_id"]})

    for span in spans:
        parent_id = span.get("parent_span_id")
        if not parent_id or parent_id not in spans_by_id:
            continue
        parent = spans_by_id[parent_id]
        parent_started = parse_utc(parent.get("started_at"))
        parent_ended = parse_utc(parent.get("ended_at"))
        child_started = parse_utc(span.get("started_at"))
        child_ended = parse_utc(span.get("ended_at"))
        if parent_started and child_started and child_started < parent_started:
            warnings.append(
                {"type": "clock_skew", "span_id": span["span_id"], "parent_span_id": parent_id}
            )
        if parent_ended and child_ended and child_ended > parent_ended:
            warnings.append(
                {"type": "clock_skew", "span_id": span["span_id"], "parent_span_id": parent_id}
            )

    if len(roots) > 1:
        warnings.append({"type": "multiple_roots", "span_ids": [span["span_id"] for span in roots]})

    def build_node(span: dict[str, Any]) -> dict[str, Any]:
        children = sorted(
            children_by_parent.get(span["span_id"], []),
            key=_span_order,
        )
        return {
            "span": span,
            "children": [build_node(child) for child in children],
            "payload_state": {
                "input": _payload_state(span.get("input")),
                "output": _payload_state(span.get("output")),
            },
        }

    ordered_roots = sorted(roots, key=_span_order)
    ordered_missing = sorted(missing_parent, key=_span_order)

    return {
        "trace_root": {
            "trace_id": trace["trace_id"],
            "status": trace.get("status", "unknown"),
            "generated_at": utc_now(),
        },
        "span_tree": [build_node(span) for span in ordered_roots],
        "timeline_rows": [
            {
                "span_id": span["span_id"],
                "parent_span_id": span.get("parent_span_id"),
                "name": span["name"],
                "span_type": span["span_type"],
                "status": span.get("status", "unknown"),
                "started_at": span["started_at"],
                "ended_at": span.get("ended_at"),
            }
            for span in sorted(spans, key=_span_order)
        ],
        "orphan_group": [],
        "missing_parent_group": [build_node(span) for span in ordered_missing],
        "incomplete_span_ids": incomplete_spans,
        "warnings": warnings,
        "payload_availability": {
            span["span_id"]: {
                "input": _payload_state(span.get("input")),
                "output": _payload_state(span.get("output")),
            }
            for span in spans
        },
        "score_overlays": [],
        "behavior_overlays": [],
        "dataset_membership": [],
    }


def _payload_state(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "unavailable"
    return str(payload.get("redaction_state") or payload.get("mode") or "unavailable")
