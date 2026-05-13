from __future__ import annotations

import json
from typing import Any

GROUNDING_EXTRACTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Shortest literal factual phrases extracted from the text. These should "
                "be suitable for exact evidence lookup, such as delivered or refund "
                "policy approved."
            ),
        },
        "uncertainty": {"type": "string"},
    },
}

GROUNDING_EXTRACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_grounding_extraction",
        "description": (
            "Record factual claims extracted from a text passage. This tool does not "
            "decide whether the claims are supported by trace evidence."
        ),
        "parameters": GROUNDING_EXTRACTION_SCHEMA,
    },
}


def evaluate_grounding_claims(
    claims: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> dict[str, Any]:
    evaluated = []
    all_evidence_span_ids = set()
    for claim in claims:
        claim_text = str(claim.get("claim") or claim.get("text") or "").strip()
        evidence_span_ids = _matching_span_ids(claim_text, spans)
        all_evidence_span_ids.update(evidence_span_ids)
        evaluated.append(
            {
                **claim,
                "claim": claim_text,
                "status": "supported" if evidence_span_ids else "missing_evidence",
                "evidence_span_ids": evidence_span_ids,
                "uncertainty": (
                    "exact evidence text match"
                    if evidence_span_ids
                    else "no exact evidence text match in trace spans"
                ),
            }
        )
    unsupported = [claim for claim in evaluated if claim["status"] != "supported"]
    return {
        "status": "supported" if not unsupported else "needs_review",
        "claims": evaluated,
        "evidence_span_ids": sorted(all_evidence_span_ids),
    }


def claims_from_text(text: str) -> list[dict[str, str]]:
    return [
        {"claim": sentence}
        for sentence in _split_sentences(text)
        if sentence
    ]


async def extract_grounding_claims_with_model(
    provider: Any,
    *,
    text: str,
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
) -> dict[str, Any]:
    span_ids = {span["span_id"] for span in spans}
    del trace
    request = _grounding_extraction_request(text=text)
    completion = await provider.tool_completion(
        {
            **request,
            "tool_choice": {
                "type": "function",
                "function": {"name": "record_grounding_extraction"},
            },
        },
        [GROUNDING_EXTRACTION_TOOL],
    )
    if completion.get("status") == "succeeded":
        call = _first_named_tool_call(completion, "record_grounding_extraction")
        if call is not None:
            return _grounding_extraction_success(call["arguments"], completion, span_ids)

    if completion.get("status") != "succeeded":
        return {
            "status": "invalid_model_output",
            "model_metadata": _metadata(completion),
            "raw_output": completion.get("raw_message"),
        }
    return {
        "status": "invalid_model_output",
        "model_metadata": _metadata(completion),
        "raw_output": completion.get("raw_message"),
    }


def _grounding_extraction_request(
    *,
    text: str,
) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract factual claims from text_to_check. Call "
                    "record_grounding_extraction exactly once. Return only short, atomic "
                    "claim strings suitable for exact evidence lookup. Prefer the "
                    "shortest literal phrase that preserves the fact. For status claims, "
                    "use the status term itself when that identifies the fact; for "
                    "approval claims, keep the approved thing plus approved. Examples: "
                    "'The shipment was delivered' becomes 'delivered'; 'the refund "
                    "policy was approved' becomes 'refund policy approved'. Do not "
                    "compare claims against evidence, decide support status, discuss "
                    "contradictions, or include evidence span IDs."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"text_to_check": text},
                    sort_keys=True,
                ),
            },
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
    }


def _grounding_extraction_success(
    value: dict[str, Any],
    completion: dict[str, Any],
    span_ids: set[str],
) -> dict[str, Any]:
    claims = _normalize_model_claims(value.get("claims", []))
    if not claims:
        return {
            "status": "invalid_model_output",
            "model_metadata": _metadata(completion),
            "raw_output": value,
        }
    return {
        "status": "succeeded",
        "claims": claims,
        "possible_contradictions": _normalize_model_contradictions(
            value.get("possible_contradictions", []),
            span_ids,
        ),
        "uncertainty": str(value.get("uncertainty") or "model extracted claims via tool call"),
        "model_metadata": _metadata(completion),
    }


def _normalize_model_claims(raw_claims: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_claims, list):
        return []
    claims = []
    for item in raw_claims:
        if isinstance(item, str):
            claim_text = item.strip()
            if claim_text:
                claims.append({"claim": claim_text})
            continue
        if isinstance(item, dict):
            claim_text = str(item.get("claim") or item.get("text") or "").strip()
            if claim_text:
                claims.append({**item, "claim": claim_text})
    return claims


def _normalize_model_contradictions(
    raw_contradictions: Any,
    span_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_contradictions, list):
        return []
    contradictions = []
    for item in raw_contradictions:
        if not isinstance(item, dict):
            continue
        claim_text = str(item.get("claim") or "").strip()
        raw_ids = item.get("contradicted_by_span_ids", [])
        if not claim_text or not isinstance(raw_ids, list):
            continue
        contradictions.append(
            {
                **item,
                "claim": claim_text,
                "contradicted_by_span_ids": [
                    span_id
                    for span_id in raw_ids
                    if isinstance(span_id, str) and span_id in span_ids
                ],
            }
        )
    return contradictions


def _first_named_tool_call(
    completion: dict[str, Any],
    name: str,
) -> dict[str, Any] | None:
    for call in completion.get("tool_calls", []):
        if call.get("name") == name:
            return call
    return None


def _matching_span_ids(claim_text: str, spans: list[dict[str, Any]]) -> list[str]:
    if not claim_text:
        return []
    needle = claim_text.lower()
    matches = []
    for span in spans:
        haystack = json.dumps(
            {
                "input": span.get("input"),
                "output": span.get("output"),
                "attributes": span.get("attributes", {}),
                "events": span.get("events", []),
            },
            sort_keys=True,
        ).lower()
        if needle in haystack:
            matches.append(span["span_id"])
    return matches


def _span_context(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "span_id": span["span_id"],
            "name": span.get("name"),
            "span_type": span.get("span_type"),
            "status": span.get("status"),
            "input": span.get("input"),
            "output": span.get("output"),
            "attributes": span.get("attributes", {}),
            "events": span.get("events", []),
        }
        for span in spans
    ]


def _metadata(completion: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": completion.get("provider"),
        "model": completion.get("model"),
        "usage": completion.get("usage"),
        "repaired": completion.get("repaired", False),
    }


def _split_sentences(text: str) -> list[str]:
    normalized = text.replace("\n", " ")
    parts = []
    current = []
    for char in normalized:
        current.append(char)
        if char in ".!?":
            parts.append("".join(current).strip())
            current = []
    if current:
        parts.append("".join(current).strip())
    return parts
