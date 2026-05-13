from __future__ import annotations

import json
from typing import Any

NOVELTY_GROUPING_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["groups"],
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "candidate_names"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "candidate_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "severity": {
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "uncertainty": {"type": "string"},
                },
            },
        },
        "uncertainty": {"type": "string"},
    },
}

NOVELTY_GROUPING_TOOL = {
    "type": "function",
    "function": {
        "name": "record_novelty_groups",
        "description": (
            "Record semantic group names for deterministic OpenABM novelty candidates. "
            "This tool groups and names existing candidates; it does not create traces."
        ),
        "parameters": NOVELTY_GROUPING_SCHEMA,
    },
}


def detect_novel_behavior_candidates(
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
    known_behaviors: list[dict[str, Any]],
) -> dict[str, Any]:
    known_names = {
        behavior["name"]
        for behavior in known_behaviors
        if behavior.get("status") == "active"
    }
    grouped: dict[str, dict[str, Any]] = {}
    for trace in traces:
        if trace.get("status") not in {"error", "failed"}:
            continue
        signature = _trace_signature(trace, spans_by_trace.get(trace["trace_id"], []))
        if signature in known_names:
            continue
        group = grouped.setdefault(
            signature,
            {
                "name": signature,
                "description": f"Recurring failure signature: {signature}",
                "representative_positive_traces": [],
                "representative_negative_traces": [],
                "severity": "medium",
                "frequency": 0,
                "uncertainty": "deterministic exact-signature grouping",
            },
        )
        group["frequency"] += 1
        group["representative_positive_traces"].append(trace["trace_id"])

    candidates = sorted(
        grouped.values(),
        key=lambda item: item["frequency"],
        reverse=True,
    )
    return {
        "new_behavior_candidates": candidates,
        "uncertainty": (
            "Deterministic novelty groups exact error/tool signatures; semantic grouping "
            "can be layered behind the model provider."
        ),
    }


async def group_novel_behavior_candidates_with_model(
    provider: Any,
    deterministic_result: dict[str, Any],
    *,
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    candidates = deterministic_result.get("new_behavior_candidates", [])
    if not candidates:
        return {
            **deterministic_result,
            "semantic_grouping": {"status": "skipped", "reason": "no candidates"},
        }
    completion = await provider.tool_completion(
        {
            **_novelty_grouping_request(
                candidates=candidates,
                traces=traces,
                spans_by_trace=spans_by_trace,
            ),
            "tool_choice": {
                "type": "function",
                "function": {"name": "record_novelty_groups"},
            },
        },
        [NOVELTY_GROUPING_TOOL],
    )
    if completion.get("status") != "succeeded":
        return _invalid_model_grouping(deterministic_result, completion)
    call = _first_named_tool_call(completion, "record_novelty_groups")
    if call is None:
        return _invalid_model_grouping(deterministic_result, completion)
    grouped = _model_grouping_success(
        deterministic_result,
        call["arguments"],
        completion,
    )
    return grouped if grouped["semantic_grouping"]["status"] == "succeeded" else grouped


def _trace_signature(trace: dict[str, Any], spans: list[dict[str, Any]]) -> str:
    error_type = trace.get("attributes", {}).get("error.type")
    span_error_types = [
        span.get("attributes", {}).get("error.type")
        for span in spans
        if span.get("attributes", {}).get("error.type")
    ]
    tool_names = [
        span.get("attributes", {}).get("tool.name")
        for span in spans
        if span.get("attributes", {}).get("tool.name")
    ]
    if error_type:
        return f"error_{error_type}"
    if span_error_types:
        return f"error_{span_error_types[0]}"
    if tool_names:
        return "tool_sequence_" + "_then_".join(str(name) for name in tool_names[:3])
    return f"status_{trace.get('status', 'unknown')}"


def _novelty_grouping_request(
    *,
    candidates: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    trace_context = []
    traces_by_id = {trace["trace_id"]: trace for trace in traces}
    for candidate in candidates:
        candidate_trace_ids = candidate.get("representative_positive_traces", [])[:5]
        trace_context.append(
            {
                "candidate_name": candidate["name"],
                "candidate_description": candidate.get("description"),
                "trace_summaries": [
                    _trace_summary(traces_by_id[trace_id], spans_by_trace.get(trace_id, []))
                    for trace_id in candidate_trace_ids
                    if trace_id in traces_by_id
                ],
            }
        )
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Group deterministic novelty candidates into human-readable behavior "
                    "drafts. Call record_novelty_groups exactly once. Use only supplied "
                    "candidate_names. Do not invent trace ids, evidence ids, or active "
                    "behaviors. Prefer concise names that describe the user-visible "
                    "agent failure pattern."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"novelty_candidates": trace_context}, sort_keys=True),
            },
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }


def _trace_summary(trace: dict[str, Any], spans: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trace_id": trace["trace_id"],
        "status": trace.get("status"),
        "summary": trace.get("summary"),
        "attributes": trace.get("attributes", {}),
        "tool_names": [
            span.get("attributes", {}).get("tool.name")
            for span in spans
            if span.get("attributes", {}).get("tool.name")
        ],
        "span_errors": [
            span.get("attributes", {}).get("error.type")
            for span in spans
            if span.get("attributes", {}).get("error.type")
        ],
    }


def _model_grouping_success(
    deterministic_result: dict[str, Any],
    value: dict[str, Any],
    completion: dict[str, Any],
) -> dict[str, Any]:
    candidates_by_name = {
        candidate["name"]: candidate
        for candidate in deterministic_result.get("new_behavior_candidates", [])
    }
    used = set()
    grouped_candidates = []
    for item in value.get("groups", []):
        if not isinstance(item, dict):
            continue
        names = [
            name
            for name in item.get("candidate_names", [])
            if isinstance(name, str) and name in candidates_by_name and name not in used
        ]
        if not names:
            continue
        used.update(names)
        source_candidates = [candidates_by_name[name] for name in names]
        traces = sorted(
            {
                trace_id
                for candidate in source_candidates
                for trace_id in candidate.get("representative_positive_traces", [])
            }
        )
        grouped_candidates.append(
            {
                "name": str(item.get("name") or source_candidates[0]["name"]).strip(),
                "description": str(
                    item.get("description") or source_candidates[0].get("description") or ""
                ).strip(),
                "source_candidate_names": names,
                "representative_positive_traces": traces,
                "representative_negative_traces": [],
                "severity": item.get("severity") or "medium",
                "frequency": sum(
                    int(candidate.get("frequency", 0)) for candidate in source_candidates
                ),
                "uncertainty": str(item.get("uncertainty") or "model semantic grouping"),
            }
        )
    for candidate in deterministic_result.get("new_behavior_candidates", []):
        if candidate["name"] not in used:
            grouped_candidates.append({**candidate, "source_candidate_names": [candidate["name"]]})
    if not grouped_candidates:
        return {
            **deterministic_result,
            "semantic_grouping": {
                "status": "invalid_model_output",
                "model_metadata": _metadata(completion),
                "raw_output": value,
            },
        }
    return {
        **deterministic_result,
        "source_signature_candidates": deterministic_result.get("new_behavior_candidates", []),
        "new_behavior_candidates": sorted(
            grouped_candidates,
            key=lambda item: item["frequency"],
            reverse=True,
        ),
        "semantic_grouping": {
            "status": "succeeded",
            "uncertainty": value.get("uncertainty") or "model semantic grouping",
            "model_metadata": _metadata(completion),
        },
        "uncertainty": "Model grouped deterministic novelty signatures; membership was validated.",
    }


def _invalid_model_grouping(
    deterministic_result: dict[str, Any],
    completion: dict[str, Any],
) -> dict[str, Any]:
    return {
        **deterministic_result,
        "semantic_grouping": {
            "status": "invalid_model_output",
            "model_metadata": _metadata(completion),
            "raw_output": completion.get("raw_message"),
        },
    }


def _first_named_tool_call(
    completion: dict[str, Any],
    name: str,
) -> dict[str, Any] | None:
    for call in completion.get("tool_calls", []):
        if call.get("name") == name:
            return call
    return None


def _metadata(completion: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": completion.get("provider"),
        "model": completion.get("model"),
        "usage": completion.get("usage"),
        "repaired": completion.get("repaired", False),
    }
