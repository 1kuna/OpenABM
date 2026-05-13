from __future__ import annotations

import json
import math
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
    *,
    baseline_traces: list[dict[str, Any]] | None = None,
    baseline_spans_by_trace: dict[str, list[dict[str, Any]]] | None = None,
    negative_example_limit: int = 3,
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
    negative_selection = _attach_representative_negative_examples(
        candidates,
        baseline_traces or [],
        baseline_spans_by_trace or {},
        limit=negative_example_limit,
    )
    return {
        "new_behavior_candidates": candidates,
        "negative_example_selection": negative_selection,
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


def group_novel_behavior_candidates_with_similarity_index(
    deterministic_result: dict[str, Any],
    trace_vectors: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.82,
) -> dict[str, Any]:
    candidates = deterministic_result.get("new_behavior_candidates", [])
    vectors_by_trace = {
        record["entity_id"]: record.get("vector", [])
        for record in trace_vectors
        if record.get("entity_type") == "trace"
    }
    if not candidates or not vectors_by_trace:
        return {
            **deterministic_result,
            "similarity_index_grouping": {
                "status": "skipped",
                "reason": "no indexed candidate vectors",
            },
        }

    candidate_vectors = {
        candidate["name"]: _candidate_vector(candidate, vectors_by_trace)
        for candidate in candidates
    }
    used = set()
    grouped_candidates = []
    for candidate in candidates:
        name = candidate["name"]
        if name in used or candidate_vectors.get(name) is None:
            continue
        used.add(name)
        group = [candidate]
        for other in candidates:
            other_name = other["name"]
            if other_name in used:
                continue
            similarity = _cosine_similarity(
                candidate_vectors[name] or [],
                candidate_vectors.get(other_name) or [],
            )
            if similarity >= similarity_threshold:
                used.add(other_name)
                group.append(other)
        grouped_candidates.append(_merge_similarity_group(group, similarity_threshold))

    for candidate in candidates:
        if candidate["name"] not in used:
            grouped_candidates.append(candidate)

    return {
        **deterministic_result,
        "source_signature_candidates": deterministic_result.get("new_behavior_candidates", []),
        "new_behavior_candidates": sorted(
            grouped_candidates,
            key=lambda item: item["frequency"],
            reverse=True,
        ),
        "similarity_index_grouping": {
            "status": "succeeded",
            "threshold": similarity_threshold,
            "indexed_trace_count": len(vectors_by_trace),
            "uncertainty": (
                "Deterministic grouping over stored trace embeddings; human review "
                "still decides whether a behavior should be promoted."
            ),
        },
        "uncertainty": "Similarity-index grouping merged deterministic failure signatures.",
    }


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


def _candidate_vector(
    candidate: dict[str, Any],
    vectors_by_trace: dict[str, list[float]],
) -> list[float] | None:
    vectors = [
        vectors_by_trace[trace_id]
        for trace_id in candidate.get("representative_positive_traces", [])
        if trace_id in vectors_by_trace
    ]
    if not vectors:
        return None
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        return None
    return [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(len(vectors[0]))
    ]


def _merge_similarity_group(
    candidates: list[dict[str, Any]],
    similarity_threshold: float,
) -> dict[str, Any]:
    if len(candidates) == 1:
        candidate = candidates[0]
        return {
            **candidate,
            "source_candidate_names": candidate.get(
                "source_candidate_names",
                [candidate["name"]],
            ),
            "representative_negative_traces": list(
                candidate.get("representative_negative_traces", [])
            ),
            "similarity_cluster_threshold": similarity_threshold,
        }
    source_names = [candidate["name"] for candidate in candidates]
    traces = sorted(
        {
            trace_id
            for candidate in candidates
            for trace_id in candidate.get("representative_positive_traces", [])
        }
    )
    negative_traces = sorted(
        {
            trace_id
            for candidate in candidates
            for trace_id in candidate.get("representative_negative_traces", [])
            if trace_id not in traces
        }
    )
    severity_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    severity = max(
        (candidate.get("severity", "medium") for candidate in candidates),
        key=lambda value: severity_rank.get(value, 1),
    )
    return {
        "name": f"embedding_cluster_{source_names[0]}",
        "description": (
            f"Similarity-index cluster merging {len(candidates)} deterministic "
            "failure signatures."
        ),
        "source_candidate_names": source_names,
        "representative_positive_traces": traces,
        "representative_negative_traces": negative_traces,
        "severity": severity,
        "frequency": sum(int(candidate.get("frequency", 0)) for candidate in candidates),
        "similarity_cluster_threshold": similarity_threshold,
        "uncertainty": "deterministic grouping over stored embedding vectors",
    }


def _attach_representative_negative_examples(
    candidates: list[dict[str, Any]],
    baseline_traces: list[dict[str, Any]],
    baseline_spans_by_trace: dict[str, list[dict[str, Any]]],
    *,
    limit: int,
) -> dict[str, Any]:
    if not candidates:
        return {"status": "skipped", "reason": "no candidates"}
    if limit <= 0:
        return {"status": "skipped", "reason": "negative examples disabled"}
    if not baseline_traces:
        return {
            "status": "skipped",
            "reason": "no baseline traces",
            "negative_example_limit": limit,
        }

    candidate_count_with_negatives = 0
    for candidate in candidates:
        candidate_signature_names = {
            candidate["name"],
            *candidate.get("source_candidate_names", []),
        }
        positive_trace_ids = set(candidate.get("representative_positive_traces", []))
        negatives = []
        for trace in baseline_traces:
            trace_id = trace["trace_id"]
            if trace_id in positive_trace_ids:
                continue
            signature = _trace_signature(trace, baseline_spans_by_trace.get(trace_id, []))
            if signature in candidate_signature_names:
                continue
            negatives.append(trace_id)
            if len(negatives) >= limit:
                break
        candidate["representative_negative_traces"] = negatives
        if negatives:
            candidate_count_with_negatives += 1

    return {
        "status": "succeeded",
        "baseline_trace_count": len(baseline_traces),
        "negative_example_limit": limit,
        "candidate_count_with_negatives": candidate_count_with_negatives,
        "uncertainty": (
            "Negative examples are deterministic baseline traces that do not share "
            "the candidate failure signature; human review still decides behavior fit."
        ),
    }


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


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
                "representative_negative_traces": sorted(
                    {
                        trace_id
                        for candidate in source_candidates
                        for trace_id in candidate.get("representative_negative_traces", [])
                        if trace_id not in traces
                    }
                ),
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
