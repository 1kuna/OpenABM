from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from openabm_api.time import utc_now

HIGH_PRIORITY_VALUES = {"high", "critical", "p0", "p1"}
ALWAYS_KEEP_STATUSES = {"error", "timeout", "cancelled"}
STREAM_EVENT_HINTS = ("stream", "delta", "token")


@dataclass
class IngestPolicyReport:
    total_items: int = 0
    high_priority_present: bool = False
    backpressure_retry: bool = False
    retry_after_seconds: int = 1
    payloads_omitted: int = 0
    payload_bytes_omitted: int = 0
    events_omitted: int = 0
    stream_events_omitted: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_items": self.total_items,
            "high_priority_present": self.high_priority_present,
            "backpressure_retry": self.backpressure_retry,
            "retry_after_seconds": self.retry_after_seconds,
            "payloads_omitted": self.payloads_omitted,
            "payload_bytes_omitted": self.payload_bytes_omitted,
            "events_omitted": self.events_omitted,
            "stream_events_omitted": self.stream_events_omitted,
            "reasons": self.reasons,
        }

    @property
    def changed(self) -> bool:
        return any(
            [
                self.backpressure_retry,
                self.payloads_omitted,
                self.events_omitted,
                self.stream_events_omitted,
                self.reasons,
            ]
        )


def apply_ingest_batch_policy(
    batch: dict[str, Any],
    *,
    max_batch_items: int,
    retryable_batch_items: int,
    inline_payload_max_bytes: int,
    max_events_per_span: int,
    stream_event_sample_rate: int,
) -> tuple[dict[str, Any], IngestPolicyReport]:
    normalized = copy.deepcopy(batch)
    report = IngestPolicyReport(total_items=_batch_item_count(normalized))
    trace_priority = {
        trace.get("trace_id"): is_high_priority_trace(trace)
        for trace in normalized.get("traces", [])
        if isinstance(trace, dict)
    }
    report.high_priority_present = _batch_has_high_priority(normalized, trace_priority)
    if (
        retryable_batch_items > 0
        and report.total_items > retryable_batch_items
    ):
        if report.high_priority_present:
            report.reasons.append("always_keep_overrode_retryable_backpressure")
        else:
            report.backpressure_retry = True
            report.reasons.append("batch_item_limit_exceeded")
            return normalized, report

    server_under_pressure = max_batch_items > 0 and report.total_items > max_batch_items
    for span in normalized.get("spans", []):
        if not isinstance(span, dict):
            continue
        span_priority = is_high_priority_span(
            span,
            trace_priority.get(span.get("trace_id"), False),
        )
        _apply_span_payload_policy(
            span,
            report,
            inline_payload_max_bytes=inline_payload_max_bytes,
            preserve_payloads=span_priority and not server_under_pressure,
        )
        _apply_span_event_policy(
            span,
            report,
            max_events_per_span=max_events_per_span,
            stream_event_sample_rate=stream_event_sample_rate,
            preserve_events=span_priority and not server_under_pressure,
        )
    if server_under_pressure:
        report.reasons.append("server_backpressure_degraded_payload_or_events_before_metadata")
    return normalized, report


def apply_ingest_span_policy(
    span: dict[str, Any],
    *,
    inline_payload_max_bytes: int,
    max_events_per_span: int,
    stream_event_sample_rate: int,
) -> tuple[dict[str, Any], IngestPolicyReport]:
    normalized = copy.deepcopy(span)
    report = IngestPolicyReport(total_items=1, high_priority_present=is_high_priority_span(span))
    preserve = report.high_priority_present
    _apply_span_payload_policy(
        normalized,
        report,
        inline_payload_max_bytes=inline_payload_max_bytes,
        preserve_payloads=preserve,
    )
    _apply_span_event_policy(
        normalized,
        report,
        max_events_per_span=max_events_per_span,
        stream_event_sample_rate=stream_event_sample_rate,
        preserve_events=preserve,
    )
    return normalized, report


def is_high_priority_trace(trace: dict[str, Any]) -> bool:
    attributes = trace.get("attributes") if isinstance(trace.get("attributes"), dict) else {}
    tags = trace.get("tags") if isinstance(trace.get("tags"), list) else []
    return (
        trace.get("status") in ALWAYS_KEEP_STATUSES
        or _truthy(attributes.get("openabm.keep"))
        or str(attributes.get("openabm.priority", "")).lower() in HIGH_PRIORITY_VALUES
        or bool(attributes.get("openabm.feedback"))
        or bool(attributes.get("openabm.behavior_ids"))
        or bool(attributes.get("openabm.dataset_ids"))
        or any(
            str(tag).lower() in {"feedback", "behavior", "dataset", "high_priority"}
            for tag in tags
        )
    )


def is_high_priority_span(span: dict[str, Any], trace_is_high_priority: bool = False) -> bool:
    attributes = span.get("attributes") if isinstance(span.get("attributes"), dict) else {}
    return (
        trace_is_high_priority
        or span.get("status") in ALWAYS_KEEP_STATUSES
        or _truthy(attributes.get("openabm.keep"))
        or str(attributes.get("openabm.priority", "")).lower() in HIGH_PRIORITY_VALUES
        or bool(attributes.get("openabm.feedback"))
        or bool(attributes.get("openabm.behavior_ids"))
        or bool(attributes.get("openabm.dataset_ids"))
    )


def _apply_span_payload_policy(
    span: dict[str, Any],
    report: IngestPolicyReport,
    *,
    inline_payload_max_bytes: int,
    preserve_payloads: bool,
) -> None:
    if inline_payload_max_bytes <= 0 or preserve_payloads:
        return
    for field_name in ("input", "output"):
        payload = span.get(field_name)
        if (
            not isinstance(payload, dict)
            or payload.get("mode") != "inline"
            or "value" not in payload
        ):
            continue
        byte_size = _json_byte_size(payload["value"])
        if byte_size <= inline_payload_max_bytes:
            continue
        span[field_name] = {
            "mode": "omitted",
            "redaction_state": "omitted",
            "omission_reason": "server_payload_sampling",
            "byte_size_nullable": byte_size,
            "sampling_policy": {
                "inline_payload_max_bytes": inline_payload_max_bytes,
                "preserved_metadata": True,
            },
        }
        report.payloads_omitted += 1
        report.payload_bytes_omitted += byte_size
    if report.payloads_omitted and "payload_body_sampling" not in report.reasons:
        report.reasons.append("payload_body_sampling")


def _apply_span_event_policy(
    span: dict[str, Any],
    report: IngestPolicyReport,
    *,
    max_events_per_span: int,
    stream_event_sample_rate: int,
    preserve_events: bool,
) -> None:
    events = span.get("events")
    if preserve_events or not isinstance(events, list) or not events:
        return
    sampled_events, stream_omitted = _sample_stream_events(events, stream_event_sample_rate)
    capped_events, capped_omitted = _cap_events(sampled_events, max_events_per_span)
    omitted = stream_omitted + capped_omitted
    if omitted == 0:
        return
    capped_events.append(
        _omission_event(stream_omitted=stream_omitted, capped_omitted=capped_omitted)
    )
    span["events"] = capped_events
    report.events_omitted += omitted
    report.stream_events_omitted += stream_omitted
    if stream_omitted and "model_stream_event_sampling" not in report.reasons:
        report.reasons.append("model_stream_event_sampling")
    if capped_omitted and "event_sampling" not in report.reasons:
        report.reasons.append("event_sampling")


def _sample_stream_events(events: list[Any], sample_rate: int) -> tuple[list[Any], int]:
    if sample_rate <= 1:
        return events, 0
    kept: list[Any] = []
    omitted = 0
    stream_index = 0
    for event in events:
        if isinstance(event, dict) and _is_stream_event(event):
            if stream_index % sample_rate == 0:
                kept.append(event)
            else:
                omitted += 1
            stream_index += 1
            continue
        kept.append(event)
    return kept, omitted


def _cap_events(events: list[Any], max_events: int) -> tuple[list[Any], int]:
    if max_events <= 0 or len(events) <= max_events:
        return events, 0
    if max_events == 1:
        return [events[-1]], len(events) - 1
    head_count = max_events // 2
    tail_count = max_events - head_count
    return events[:head_count] + events[-tail_count:], len(events) - max_events


def _omission_event(*, stream_omitted: int, capped_omitted: int) -> dict[str, Any]:
    return {
        "name": "openabm.events_omitted",
        "time": utc_now(),
        "attributes": {
            "omission_reason": "event_sampling",
            "stream_events_omitted": stream_omitted,
            "other_events_omitted": capped_omitted,
            "preserved_metadata": True,
        },
    }


def _is_stream_event(event: dict[str, Any]) -> bool:
    name = str(event.get("name", "")).lower()
    if any(hint in name for hint in STREAM_EVENT_HINTS):
        return True
    attributes = event.get("attributes") if isinstance(event.get("attributes"), dict) else {}
    return str(attributes.get("openabm.event_kind", "")).lower() in {
        "stream_delta",
        "model_delta",
        "token_delta",
    }


def _batch_item_count(batch: dict[str, Any]) -> int:
    return sum(
        len(batch.get(key, [])) if isinstance(batch.get(key), list) else 0
        for key in ("traces", "spans", "events", "feedback", "payloads")
    )


def _batch_has_high_priority(
    batch: dict[str, Any],
    trace_priority: dict[Any, bool],
) -> bool:
    if isinstance(batch.get("feedback"), list) and batch["feedback"]:
        return True
    if any(trace_priority.values()):
        return True
    for span in batch.get("spans", []):
        if isinstance(span, dict) and is_high_priority_span(
            span,
            trace_priority.get(span.get("trace_id"), False),
        ):
            return True
    return False


def _json_byte_size(value: Any) -> int:
    return len(json.dumps(value, default=str, sort_keys=True).encode("utf-8"))


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
