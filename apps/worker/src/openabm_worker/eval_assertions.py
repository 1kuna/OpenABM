from __future__ import annotations

from typing import Any


def evaluate_trace_assertions(
    spans: list[dict[str, Any]],
    assertions: dict[str, Any],
) -> dict[str, Any]:
    tool_names = [_tool_name(span) for span in spans if _tool_name(span)]
    span_types = [str(span.get("span_type", "unknown")) for span in spans]
    behavior_ids_by_span = {
        span.get("span_id", ""): _as_string_list(_attr(span, "openabm.behavior_ids"))
        for span in spans
    }
    behavior_ids = {value for values in behavior_ids_by_span.values() for value in values}
    retrieval_sources_by_span = {
        span.get("span_id", ""): _retrieval_sources(span)
        for span in spans
    }
    retrieval_sources = {value for values in retrieval_sources_by_span.values() for value in values}
    grounding_evidence_ids = {
        value
        for span in spans
        for value in _as_string_list(_attr(span, "grounding.evidence_span_ids"))
    }
    total_cost = sum(_float_attr(span, "cost.estimated_usd") for span in spans)
    total_duration_ms = sum(_span_duration_ms(span) for span in spans)
    retry_count = sum(_span_retry_count(span) for span in spans)
    failures: list[dict[str, Any]] = []

    for tool in assertions.get("required_tools", assertions.get("expected_tool_calls", [])):
        if tool not in tool_names:
            failures.append({"type": "missing_required_tool", "tool": tool, "span_ids": []})

    for tool in assertions.get("forbidden_tools", assertions.get("forbidden_tool_calls", [])):
        span_ids = [
            span["span_id"]
            for span in spans
            if _tool_name(span) == tool
        ]
        if span_ids:
            failures.append({"type": "forbidden_tool_used", "tool": tool, "span_ids": span_ids})

    for behavior_id in assertions.get("expected_behavior_ids", []):
        if behavior_id not in behavior_ids:
            failures.append(
                {"type": "missing_expected_behavior", "behavior_id": behavior_id, "span_ids": []}
            )

    for behavior_id in assertions.get("forbidden_behavior_ids", []):
        if behavior_id in behavior_ids:
            span_ids = [
                span_id
                for span_id, observed in behavior_ids_by_span.items()
                if behavior_id in observed
            ]
            failures.append(
                {
                    "type": "forbidden_behavior_present",
                    "behavior_id": behavior_id,
                    "span_ids": span_ids,
                }
            )

    for source in assertions.get("required_retrieval_sources", []):
        if source not in retrieval_sources:
            failures.append({"type": "missing_retrieval_source", "source": source, "span_ids": []})

    for source in assertions.get("forbidden_retrieval_sources", []):
        span_ids = [
            span_id
            for span_id, observed in retrieval_sources_by_span.items()
            if source in observed
        ]
        if span_ids:
            failures.append(
                {"type": "forbidden_retrieval_source", "source": source, "span_ids": span_ids}
            )

    for span_type in assertions.get("required_span_types", []):
        if span_type not in span_types:
            failures.append({"type": "missing_span_type", "span_type": span_type, "span_ids": []})

    for span_type in assertions.get("forbidden_span_types", []):
        span_ids = [
            str(span.get("span_id"))
            for span in spans
            if span.get("span_type") == span_type
        ]
        if span_ids:
            failures.append(
                {"type": "forbidden_span_type", "span_type": span_type, "span_ids": span_ids}
            )

    if "max_cost" in assertions and total_cost > float(assertions["max_cost"]):
        failures.append(
            {"type": "max_cost_exceeded", "actual": total_cost, "limit": assertions["max_cost"]}
        )

    duration_limit = assertions.get("max_total_duration_ms", assertions.get("max_latency_ms"))
    if duration_limit is not None and total_duration_ms > float(duration_limit):
        failures.append(
            {
                "type": "max_duration_exceeded",
                "actual": total_duration_ms,
                "limit": duration_limit,
            }
        )

    if "max_retries" in assertions and retry_count > int(assertions["max_retries"]):
        failures.append(
            {
                "type": "max_retries_exceeded",
                "actual": retry_count,
                "limit": assertions["max_retries"],
            }
        )

    min_grounding = assertions.get("min_grounding_evidence_span_count")
    if min_grounding is not None and len(grounding_evidence_ids) < int(min_grounding):
        failures.append(
            {
                "type": "missing_grounding_evidence",
                "actual": len(grounding_evidence_ids),
                "limit": min_grounding,
            }
        )

    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "observed": {
            "tool_names": tool_names,
            "retrieval_sources": sorted(retrieval_sources),
            "behavior_ids": sorted(behavior_ids),
            "span_types": span_types,
            "total_cost": total_cost,
            "total_duration_ms": total_duration_ms,
            "retry_count": retry_count,
            "grounding_evidence_span_ids": sorted(grounding_evidence_ids),
        },
    }


def _tool_name(span: dict[str, Any]) -> str | None:
    value = _attr(span, "tool.name")
    return str(value) if value else None


def _retrieval_sources(span: dict[str, Any]) -> list[str]:
    values = []
    values.extend(_as_string_list(_attr(span, "retrieval.source_ids")))
    values.extend(_as_string_list(_attr(span, "retrieval.sources")))
    source_id = _attr(span, "retrieval.source_id")
    if source_id:
        values.append(str(source_id))
    return sorted(set(values))


def _float_attr(span: dict[str, Any], key: str) -> float:
    value = _attr(span, key)
    return float(value or 0)


def _span_duration_ms(span: dict[str, Any]) -> float:
    value = span.get("duration_ms", _attr(span, "duration_ms"))
    return float(value or 0)


def _span_retry_count(span: dict[str, Any]) -> int:
    value = _attr(span, "retry.count")
    if value is None:
        value = _attr(span, "retry_count")
    if value is None:
        attempt = _attr(span, "retry.attempt")
        return 1 if int(attempt or 0) > 0 else 0
    return int(value or 0)


def _attr(span: dict[str, Any], key: str) -> Any:
    attributes = span.get("attributes") or {}
    if key in attributes:
        return attributes[key]
    current: Any = attributes
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        normalized = []
        for item in value:
            if isinstance(item, dict):
                candidate = item.get("source_id") or item.get("id") or item.get("name")
                if candidate:
                    normalized.append(str(candidate))
            else:
                normalized.append(str(item))
        return normalized
    return [str(value)]
