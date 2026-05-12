from __future__ import annotations

import json
from typing import Any

INVESTIGATION_ASSISTANCE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "suspected_root_causes",
        "behavior_drafts",
        "rubric_drafts",
        "recommended_next_actions",
        "confidence_or_uncertainty",
    ],
    "properties": {
        "suspected_root_causes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "hypothesis",
                    "evidence_trace_ids",
                    "evidence_span_ids",
                    "confidence_or_uncertainty",
                ],
                "properties": {
                    "hypothesis": {"type": "string"},
                    "evidence_trace_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence_span_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence_or_uncertainty": {"type": "string"},
                },
            },
        },
        "behavior_drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "description", "positive_trace_ids", "negative_trace_ids"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "positive_trace_ids": {"type": "array", "items": {"type": "string"}},
                    "negative_trace_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rubric_drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "pass", "fail", "unsure", "evidence_trace_ids"],
                "properties": {
                    "name": {"type": "string"},
                    "pass": {"type": "string"},
                    "fail": {"type": "string"},
                    "unsure": {"type": "string"},
                    "evidence_trace_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "recommended_next_actions": {"type": "array", "items": {"type": "string"}},
        "confidence_or_uncertainty": {"type": "string"},
    },
}


async def assist_investigation(
    provider: Any,
    *,
    issue: dict[str, Any] | None,
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
    impact_report: dict[str, Any],
) -> dict[str, Any]:
    trace_ids = [trace["trace_id"] for trace in traces]
    span_ids = {
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
                        "You assist an OpenABM incident investigation. Use only the "
                        "provided issue, traces, spans, and impact report. Drafts are "
                        "not active changes. Every factual hypothesis must cite trace "
                        "and span IDs from the input. If evidence is insufficient, leave "
                        "the relevant arrays empty and explain the uncertainty. Never "
                        "invent IDs or infer facts that are not supported by cited spans. "
                        "When a cited root-cause hypothesis is supported, also draft a "
                        "candidate behavior and rubric that a human could review; a "
                        "single positive trace is acceptable, and negative_trace_ids may "
                        "be empty when no counterexample is present."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "issue": issue,
                            "traces": traces,
                            "spans_by_trace": spans_by_trace,
                            "impact_report": impact_report,
                        },
                        sort_keys=True,
                    ),
                },
            ],
            "temperature": 0.1,
        },
        INVESTIGATION_ASSISTANCE_SCHEMA,
    )
    if completion.get("status") != "succeeded":
        return _unavailable(completion, "invalid_model_output")
    value = _filter_to_known_evidence(completion["value"], trace_ids, span_ids)
    return {
        **value,
        "model_metadata": {
            "provider": completion.get("provider"),
            "model": completion.get("model"),
            "usage": completion.get("usage"),
            "repaired": completion.get("repaired", False),
            "validation_status": "valid",
        },
    }


def _filter_to_known_evidence(
    value: dict[str, Any],
    trace_ids: list[str],
    span_ids: set[str],
) -> dict[str, Any]:
    filtered_root_causes = []
    for candidate in value.get("suspected_root_causes", []):
        evidence_trace_ids = [
            trace_id for trace_id in candidate["evidence_trace_ids"] if trace_id in trace_ids
        ]
        evidence_span_ids = [
            span_id for span_id in candidate["evidence_span_ids"] if span_id in span_ids
        ]
        if evidence_trace_ids and evidence_span_ids:
            filtered_root_causes.append(
                {
                    **candidate,
                    "evidence_trace_ids": evidence_trace_ids,
                    "evidence_span_ids": evidence_span_ids,
                }
            )
    filtered_behaviors = []
    for draft in value.get("behavior_drafts", []):
        positives = [trace_id for trace_id in draft["positive_trace_ids"] if trace_id in trace_ids]
        negatives = [trace_id for trace_id in draft["negative_trace_ids"] if trace_id in trace_ids]
        if positives:
            filtered_behaviors.append(
                {**draft, "positive_trace_ids": positives, "negative_trace_ids": negatives}
            )
    filtered_rubrics = []
    for draft in value.get("rubric_drafts", []):
        evidence = [trace_id for trace_id in draft["evidence_trace_ids"] if trace_id in trace_ids]
        if evidence:
            filtered_rubrics.append({**draft, "evidence_trace_ids": evidence})
    return {
        "suspected_root_causes": filtered_root_causes,
        "behavior_drafts": filtered_behaviors,
        "rubric_drafts": filtered_rubrics,
        "recommended_next_actions": value.get("recommended_next_actions", []),
        "confidence_or_uncertainty": value.get("confidence_or_uncertainty"),
    }


def _unavailable(completion: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "suspected_root_causes": [],
        "behavior_drafts": [],
        "rubric_drafts": [],
        "recommended_next_actions": [],
        "confidence_or_uncertainty": reason,
        "model_metadata": {
            "provider": completion.get("provider"),
            "model": completion.get("model"),
            "usage": completion.get("usage"),
            "repaired": completion.get("repaired", False),
            "validation_status": reason,
        },
    }
