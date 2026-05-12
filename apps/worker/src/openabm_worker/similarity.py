from __future__ import annotations

from typing import Any

TRACE_SIMILARITY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["matches", "uncertainty"],
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["trace_id", "similarity_score", "rationale", "evidence_span_ids"],
                "properties": {
                    "trace_id": {"type": "string"},
                    "similarity_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                    "evidence_span_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "uncertainty": {"type": "string"},
    },
}


async def rank_similar_traces(
    provider: Any,
    *,
    source_trace: dict[str, Any],
    source_spans: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    candidate_spans: dict[str, list[dict[str, Any]]],
    limit: int,
) -> dict[str, Any]:
    candidate_trace_ids = [trace["trace_id"] for trace in candidates]
    candidate_span_ids = {
        span["span_id"]
        for spans in candidate_spans.values()
        for span in spans
    }
    completion = await provider.structured_completion(
        {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You rank OpenABM traces by semantic behavioral similarity. "
                        "Use trace and span evidence only. Cite candidate span IDs for "
                        "each match. Do not include traces that are not in candidates."
                    ),
                },
                {
                    "role": "user",
                    "content": str(
                        {
                            "source_trace": source_trace,
                            "source_spans": source_spans,
                            "candidates": candidates,
                            "candidate_spans": candidate_spans,
                            "limit": limit,
                        }
                    ),
                },
            ],
            "temperature": 0.1,
        },
        TRACE_SIMILARITY_SCHEMA,
    )
    if completion.get("status") != "succeeded":
        return {
            "status": "invalid_output",
            "matches": [],
            "uncertainty": "Model output did not satisfy the similarity schema.",
            "model_metadata": _metadata(completion, "invalid_output"),
        }
    ranked = _validate_and_sort_matches(
        completion["value"]["matches"],
        candidate_trace_ids,
        candidate_span_ids,
        limit,
    )
    return {
        "status": "succeeded",
        "matches": ranked,
        "uncertainty": completion["value"].get("uncertainty"),
        "model_metadata": _metadata(completion, "valid"),
    }


def _validate_and_sort_matches(
    matches: list[dict[str, Any]],
    candidate_trace_ids: list[str],
    candidate_span_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    valid = []
    for match in matches:
        if match["trace_id"] not in candidate_trace_ids:
            continue
        span_ids = [
            span_id
            for span_id in match["evidence_span_ids"]
            if span_id in candidate_span_ids
        ]
        if not span_ids:
            continue
        valid.append({**match, "evidence_span_ids": span_ids})
    return sorted(valid, key=lambda item: item["similarity_score"], reverse=True)[:limit]


def _metadata(completion: dict[str, Any], validation_status: str) -> dict[str, Any]:
    return {
        "provider": completion.get("provider"),
        "model": completion.get("model"),
        "usage": completion.get("usage"),
        "repaired": completion.get("repaired", False),
        "validation_status": validation_status,
    }
