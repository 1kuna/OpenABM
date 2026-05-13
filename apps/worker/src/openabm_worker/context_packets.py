from __future__ import annotations

import hashlib
import json
from typing import Any

CONTEXT_VERSION = "ctx_2"
CHARS_PER_TOKEN = 4
MAX_PAYLOAD_SUMMARY_CHARS = 2000


def build_trace_context_packet(
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    *,
    token_budget: int,
    payload_policy: str = "redacted",
) -> dict[str, Any]:
    if token_budget < 32768:
        raise ValueError("Trace context packets must use at least 32768 tokens.")

    payload_summaries: list[dict[str, Any]] = []
    span_entries = [
        _span_entry(span, payload_summaries=payload_summaries)
        for span in sorted(spans, key=_span_sort_key)
    ]
    packet = _packet(
        trace,
        span_entries,
        payload_summaries,
        payload_policy=payload_policy,
        token_budget=token_budget,
        truncation_notes=[],
    )
    if _estimated_tokens(packet) > token_budget:
        packet = _truncate_packet(
            trace,
            span_entries,
            payload_summaries,
            payload_policy=payload_policy,
            token_budget=token_budget,
        )
    packet["context_packet_hash"] = _packet_hash(packet)
    return packet


def _packet(
    trace: dict[str, Any],
    span_entries: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    *,
    payload_policy: str,
    token_budget: int,
    truncation_notes: list[dict[str, Any]],
) -> dict[str, Any]:
    preserved_span_ids = [span["span_id"] for span in span_entries]
    omitted_span_ids = [
        summary["span_id"]
        for summary in summaries
        if summary.get("summary_type") == "omitted_span"
    ]
    return {
        "trace_id": trace["trace_id"],
        "context_version": CONTEXT_VERSION,
        "span_tree": span_entries,
        "trace": trace,
        "preserved_span_ids": preserved_span_ids,
        "omitted_span_ids": omitted_span_ids,
        "summaries": summaries,
        "payload_policy": payload_policy,
        "token_budget": token_budget,
        "estimated_tokens": _estimated_tokens(
            {
                "trace": trace,
                "span_tree": span_entries,
                "summaries": summaries,
                "payload_policy": payload_policy,
            }
        ),
        "truncation_notes": truncation_notes,
        "reproducibility": {
            "builder": "openabm_worker.context_packets.build_trace_context_packet",
            "inputs": ["trace", "spans", "payload_policy", "token_budget"],
            "deterministic": True,
        },
    }


def _truncate_packet(
    trace: dict[str, Any],
    span_entries: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    *,
    payload_policy: str,
    token_budget: int,
) -> dict[str, Any]:
    max_chars = token_budget * CHARS_PER_TOKEN
    preserved: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    running = _json_byte_size(
        {"trace": trace, "payload_policy": payload_policy, "summaries": summaries}
    )
    for span in sorted(span_entries, key=_preservation_sort_key):
        span_size = _json_byte_size(span)
        if running + span_size <= max_chars or not preserved:
            preserved.append(span)
            running += span_size
        else:
            omitted.append(span)

    omitted_summaries = [
        {
            "summary_type": "omitted_span",
            "span_id": span["span_id"],
            "name": span["name"],
            "span_type": span["span_type"],
            "status": span["status"],
            "reason": "context_budget",
        }
        for span in omitted
    ]
    preserved.sort(key=_span_sort_key)
    truncation_notes = [
        {
            "reason": "context_budget_exceeded",
            "omitted_span_count": len(omitted),
            "preserved_span_count": len(preserved),
            "token_budget": token_budget,
        }
    ]
    return _packet(
        trace,
        preserved,
        summaries + omitted_summaries,
        payload_policy=payload_policy,
        token_budget=token_budget,
        truncation_notes=truncation_notes,
    )


def _span_entry(
    span: dict[str, Any],
    *,
    payload_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "span_id": span["span_id"],
        "parent_span_id": span.get("parent_span_id"),
        "name": span["name"],
        "span_type": span["span_type"],
        "status": span["status"],
        "started_at": span["started_at"],
        "ended_at": span.get("ended_at"),
        "attributes": span.get("attributes", {}),
        "events": _summarize_events(span.get("events", []), span["span_id"], payload_summaries),
        "input": _summarize_payload(span.get("input"), span["span_id"], "input", payload_summaries),
        "output": _summarize_payload(
            span.get("output"),
            span["span_id"],
            "output",
            payload_summaries,
        ),
        "priority": _span_priority(span),
    }


def _summarize_payload(
    payload: Any,
    span_id: str,
    field_name: str,
    summaries: list[dict[str, Any]],
) -> Any:
    if not isinstance(payload, dict) or payload.get("mode") != "inline" or "value" not in payload:
        return payload
    rendered = json.dumps(payload["value"], default=str, sort_keys=True)
    if len(rendered) <= MAX_PAYLOAD_SUMMARY_CHARS:
        return payload
    summary = {
        "summary_type": "payload",
        "span_id": span_id,
        "field": field_name,
        "original_byte_size": len(rendered.encode("utf-8")),
        "preview": rendered[:MAX_PAYLOAD_SUMMARY_CHARS],
        "reason": "long_payload",
    }
    summaries.append(summary)
    return {
        "mode": "omitted",
        "redaction_state": payload.get("redaction_state", "raw"),
        "omission_reason": "context_payload_summary",
        "summary_ref": {
            "span_id": span_id,
            "field": field_name,
            "summary_type": "payload",
        },
        "original_byte_size": summary["original_byte_size"],
    }


def _summarize_events(
    events: Any,
    span_id: str,
    summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    if len(events) <= 25:
        return events
    kept = events[:10] + events[-10:]
    summaries.append(
        {
            "summary_type": "events",
            "span_id": span_id,
            "event_count": len(events),
            "preserved_event_count": len(kept),
            "omitted_event_count": len(events) - len(kept),
            "reason": "long_event_sequence",
        }
    )
    kept.append(
        {
            "name": "openabm.context_events_omitted",
            "time": kept[-1].get("time") if isinstance(kept[-1], dict) else None,
            "attributes": {
                "omitted_event_count": len(events) - len(kept),
                "reason": "context_budget",
            },
        }
    )
    return kept


def _span_priority(span: dict[str, Any]) -> int:
    if span.get("parent_span_id") is None:
        return 100
    if span.get("status") in {"error", "timeout", "cancelled"}:
        return 95
    event_names = {
        event.get("name")
        for event in span.get("events", [])
        if isinstance(event, dict)
    }
    if event_names & {"exception", "tool.timeout", "model.refusal", "user.feedback"}:
        return 90
    if span.get("span_type") == "tool":
        return 80
    if span.get("span_type") in {"retriever", "memory"}:
        return 70
    if span.get("span_type") == "model_call":
        return 50
    if span.get("output") is not None:
        return 40
    return 20


def _preservation_sort_key(span: dict[str, Any]) -> tuple[int, str, str]:
    return (-int(span.get("priority", 0)), str(span.get("started_at") or ""), span["span_id"])


def _span_sort_key(span: dict[str, Any]) -> tuple[str, str]:
    return str(span.get("started_at") or ""), span["span_id"]


def _estimated_tokens(packet: dict[str, Any]) -> int:
    return max(1, _json_byte_size(packet) // CHARS_PER_TOKEN)


def _json_byte_size(value: Any) -> int:
    return len(json.dumps(value, default=str, sort_keys=True).encode("utf-8"))


def _packet_hash(packet: dict[str, Any]) -> str:
    without_hash = {
        key: value
        for key, value in packet.items()
        if key != "context_packet_hash"
    }
    return hashlib.sha256(
        json.dumps(without_hash, default=str, sort_keys=True).encode("utf-8")
    ).hexdigest()
