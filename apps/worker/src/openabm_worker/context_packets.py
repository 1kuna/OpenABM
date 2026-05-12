from __future__ import annotations

from typing import Any


def build_trace_context_packet(
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    *,
    token_budget: int,
    payload_policy: str = "redacted",
) -> dict[str, Any]:
    if token_budget < 32768:
        raise ValueError("Trace context packets must use at least 32768 tokens.")

    preserved_span_ids = [span["span_id"] for span in spans]
    return {
        "trace_id": trace["trace_id"],
        "context_version": "ctx_1",
        "span_tree": [
            {
                "span_id": span["span_id"],
                "parent_span_id": span.get("parent_span_id"),
                "name": span["name"],
                "span_type": span["span_type"],
                "status": span["status"],
                "started_at": span["started_at"],
                "ended_at": span.get("ended_at"),
                "attributes": span.get("attributes", {}),
                "events": span.get("events", []),
                "input": span.get("input"),
                "output": span.get("output"),
            }
            for span in spans
        ],
        "trace": trace,
        "preserved_span_ids": preserved_span_ids,
        "omitted_span_ids": [],
        "summaries": [],
        "payload_policy": payload_policy,
        "token_budget": token_budget,
        "truncation_notes": [],
    }
