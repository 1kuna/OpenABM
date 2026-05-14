from __future__ import annotations

from typing import Any

CONTEXT_PACK_SUMMARY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "issue_summary",
        "trace_summaries",
        "tool_sequence_summary",
        "business_dimension_summary",
        "key_evidence",
        "uncertainty",
    ],
    "properties": {
        "issue_summary": {"type": "string"},
        "trace_summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["trace_id", "summary", "evidence_span_ids"],
                "properties": {
                    "trace_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "evidence_span_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "tool_sequence_summary": {"type": "string"},
        "business_dimension_summary": {"type": "string"},
        "key_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "trace_id", "span_ids"],
                "properties": {
                    "claim": {"type": "string"},
                    "trace_id": {"type": "string"},
                    "span_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "uncertainty": {"type": "string"},
    },
}


async def build_agent_context_pack_content(
    provider: Any,
    *,
    issue: dict[str, Any] | None,
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
    dimensions_by_trace: dict[str, list[dict[str, Any]]],
    allowed_next_actions: list[str],
    classification: str,
) -> dict[str, Any]:
    source_trace_ids = [trace["trace_id"] for trace in traces]
    preserved_span_ids = {
        span["span_id"]
        for spans in spans_by_trace.values()
        for span in spans
    }
    completion = await provider.structured_completion(
        {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You build OpenABM agent context packs from trace evidence. "
                        "Summaries must cite trace IDs and span IDs present in the input. "
                        "Say when evidence is insufficient; do not invent production facts."
                    ),
                },
                {
                    "role": "user",
                    "content": str(
                        {
                            "issue": issue,
                            "traces": traces,
                            "spans_by_trace": spans_by_trace,
                            "dimensions_by_trace": dimensions_by_trace,
                            "allowed_next_actions": allowed_next_actions,
                            "classification": classification,
                        }
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
        },
        CONTEXT_PACK_SUMMARY_SCHEMA,
    )

    summary = completion.get("value") if completion.get("status") == "succeeded" else None
    validation = _validate_summary_citations(summary, source_trace_ids, preserved_span_ids)
    if summary is None or validation["status"] != "valid":
        summary = _fallback_summary(issue, traces, spans_by_trace)
        validation = {
            "status": "fallback",
            "reason": completion.get("status", "invalid_citations"),
            "invalid_references": validation.get("invalid_references", []),
        }

    return {
        "issue": issue,
        "source_trace_ids": source_trace_ids,
        "summary": summary,
        "dimensions_by_trace": dimensions_by_trace,
        "allowed_next_actions": allowed_next_actions,
        "redaction_and_permission_policy": {"classification": classification},
        "model_metadata": {
            "provider": completion.get("provider"),
            "model": completion.get("model"),
            "usage": completion.get("usage"),
            "repaired": completion.get("repaired", False),
            "summary_validation": validation,
        },
    }


def _validate_summary_citations(
    summary: dict[str, Any] | None,
    source_trace_ids: list[str],
    preserved_span_ids: set[str],
) -> dict[str, Any]:
    if not summary:
        return {"status": "invalid", "invalid_references": []}
    invalid = []
    for trace_summary in summary.get("trace_summaries", []):
        if trace_summary.get("trace_id") not in source_trace_ids:
            invalid.append({"type": "trace", "value": trace_summary.get("trace_id")})
        for span_id in trace_summary.get("evidence_span_ids", []):
            if span_id not in preserved_span_ids:
                invalid.append({"type": "span", "value": span_id})
    for evidence in summary.get("key_evidence", []):
        if evidence.get("trace_id") not in source_trace_ids:
            invalid.append({"type": "trace", "value": evidence.get("trace_id")})
        for span_id in evidence.get("span_ids", []):
            if span_id not in preserved_span_ids:
                invalid.append({"type": "span", "value": span_id})
    return {"status": "valid" if not invalid else "invalid", "invalid_references": invalid}


def _fallback_summary(
    issue: dict[str, Any] | None,
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "issue_summary": issue.get("title") if issue else "No issue supplied.",
        "trace_summaries": [
            {
                "trace_id": trace["trace_id"],
                "summary": trace.get("summary") or trace["trace_id"],
                "evidence_span_ids": _first_span_ids(spans_by_trace[trace["trace_id"]]),
            }
            for trace in traces
        ],
        "tool_sequence_summary": "Model summary unavailable; raw span order is preserved.",
        "business_dimension_summary": "Model summary unavailable; dimensions are preserved.",
        "key_evidence": [],
        "uncertainty": "Model summary was unavailable or failed citation validation.",
    }


def _first_span_ids(spans: list[dict[str, Any]]) -> list[str]:
    return [span["span_id"] for span in spans][:3]
