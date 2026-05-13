from __future__ import annotations

import json
from typing import Any


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
