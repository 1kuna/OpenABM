from __future__ import annotations

import hashlib
import json
import math
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
            "max_tokens": 8192,
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


async def rank_similar_traces_by_embeddings(
    provider: Any,
    *,
    source_trace: dict[str, Any],
    source_spans: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    candidate_spans: dict[str, list[dict[str, Any]]],
    limit: int,
) -> dict[str, Any]:
    documents = _embedding_documents(
        source_trace=source_trace,
        source_spans=source_spans,
        candidates=candidates,
        candidate_spans=candidate_spans,
    )
    completion = await provider.embed_documents(documents)
    if completion.get("status") != "succeeded":
        return {
            "status": "invalid_output",
            "matches": [],
            "uncertainty": "Embedding provider output was invalid.",
            "model_metadata": _embedding_metadata(completion, "invalid_output"),
        }
    vectors = {
        item["document_id"]: item["embedding"]
        for item in completion.get("embeddings", [])
        if isinstance(item, dict)
    }
    source_vector = vectors.get("source_trace")
    if source_vector is None:
        return {
            "status": "invalid_output",
            "matches": [],
            "uncertainty": "Embedding response did not include the source trace vector.",
            "model_metadata": _embedding_metadata(completion, "missing_source"),
        }
    matches = []
    for trace in candidates:
        trace_id = trace["trace_id"]
        trace_vector = vectors.get(f"trace:{trace_id}")
        if trace_vector is None:
            continue
        spans = candidate_spans.get(trace_id, [])
        evidence_span_ids = _top_embedding_span_ids(source_vector, trace_id, spans, vectors)
        matches.append(
            {
                "trace_id": trace_id,
                "similarity_score": _cosine_similarity(source_vector, trace_vector),
                "rationale": "Embedding similarity over trace and span representations.",
                "evidence_span_ids": evidence_span_ids,
            }
        )
    return {
        "status": "succeeded",
        "matches": sorted(
            matches,
            key=lambda item: item["similarity_score"],
            reverse=True,
        )[:limit],
        "uncertainty": "Embedding similarity is deterministic over provider vectors.",
        "model_metadata": _embedding_metadata(completion, "valid"),
    }


def rank_similar_traces_from_vectors(
    *,
    source_vector: dict[str, Any],
    candidate_trace_vectors: list[dict[str, Any]],
    candidate_span_vectors: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    source = source_vector.get("vector", [])
    span_vectors_by_trace: dict[str, list[dict[str, Any]]] = {}
    for record in candidate_span_vectors:
        trace_id = record.get("trace_id_nullable")
        if isinstance(trace_id, str):
            span_vectors_by_trace.setdefault(trace_id, []).append(record)
    matches = []
    for record in candidate_trace_vectors:
        trace_id = record["entity_id"]
        if trace_id == source_vector.get("entity_id"):
            continue
        matches.append(
            {
                "trace_id": trace_id,
                "similarity_score": _cosine_similarity(source, record.get("vector", [])),
                "rationale": "Stored embedding-index similarity over trace vectors.",
                "evidence_span_ids": _top_index_span_ids(
                    source,
                    span_vectors_by_trace.get(trace_id, []),
                ),
            }
        )
    return {
        "status": "succeeded",
        "matches": sorted(
            matches,
            key=lambda item: item["similarity_score"],
            reverse=True,
        )[:limit],
        "uncertainty": "Stored embedding index ranked deterministically by cosine similarity.",
        "model_metadata": {
            "provider": source_vector.get("provider"),
            "model": source_vector.get("model"),
            "validation_status": "valid",
            "representation_version": source_vector.get("representation_version"),
            "indexed_vector_count": len(candidate_trace_vectors) + len(candidate_span_vectors),
        },
    }


def build_trace_embedding_document(
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
) -> dict[str, str]:
    text = _trace_embedding_text(trace, spans)
    return {
        "document_id": f"trace:{trace['trace_id']}",
        "text": text,
        "source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def build_span_embedding_document(trace_id: str, span: dict[str, Any]) -> dict[str, str]:
    text = _span_embedding_text(span)
    return {
        "document_id": f"span:{trace_id}:{span['span_id']}",
        "text": text,
        "source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def embedding_representation_version(model: str) -> str:
    return f"embedding_index_v1:{model}"


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


def _embedding_documents(
    *,
    source_trace: dict[str, Any],
    source_spans: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    candidate_spans: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    documents = [
        {
            "document_id": "source_trace",
            "text": _trace_embedding_text(source_trace, source_spans),
        }
    ]
    for trace in candidates:
        trace_id = trace["trace_id"]
        spans = candidate_spans.get(trace_id, [])
        documents.append(
            {
                "document_id": f"trace:{trace_id}",
                "text": _trace_embedding_text(trace, spans),
            }
        )
        for span in spans:
            documents.append(
                {
                    "document_id": f"span:{trace_id}:{span['span_id']}",
                    "text": _span_embedding_text(span),
                }
            )
    return documents


def _top_index_span_ids(
    source_vector: list[float],
    span_vectors: list[dict[str, Any]],
) -> list[str]:
    scored = []
    for record in span_vectors:
        score = _cosine_similarity(source_vector, record.get("vector", []))
        if score > 0.0:
            scored.append((record["entity_id"], score))
    return [
        span_id
        for span_id, _score in sorted(scored, key=lambda item: item[1], reverse=True)[:3]
    ]


def _trace_embedding_text(trace: dict[str, Any], spans: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "trace_id": trace.get("trace_id"),
            "status": trace.get("status"),
            "summary": trace.get("summary"),
            "attributes": trace.get("attributes", {}),
            "spans": [_span_embedding_payload(span) for span in spans[:20]],
        },
        sort_keys=True,
    )


def _span_embedding_text(span: dict[str, Any]) -> str:
    return json.dumps(_span_embedding_payload(span), sort_keys=True)


def _span_embedding_payload(span: dict[str, Any]) -> dict[str, Any]:
    return {
        "span_id": span.get("span_id"),
        "name": span.get("name"),
        "span_type": span.get("span_type"),
        "status": span.get("status"),
        "input": _bounded_text(span.get("input")),
        "output": _bounded_text(span.get("output")),
        "attributes": span.get("attributes", {}),
        "events": span.get("events", [])[:20],
    }


def _bounded_text(value: Any, max_chars: int = 4000) -> Any:
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    if len(text) <= max_chars:
        return value
    return {"summary_text": text[:max_chars], "omission_reason": "embedding_text_truncated"}


def _top_embedding_span_ids(
    source_vector: list[float],
    trace_id: str,
    spans: list[dict[str, Any]],
    vectors: dict[str, list[float]],
) -> list[str]:
    scored = []
    for span in spans:
        span_id = span["span_id"]
        vector = vectors.get(f"span:{trace_id}:{span_id}")
        if vector is None:
            continue
        score = _cosine_similarity(source_vector, vector)
        if score > 0.0:
            scored.append((span_id, score))
    return [
        span_id
        for span_id, _score in sorted(scored, key=lambda item: item[1], reverse=True)[:3]
    ]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _metadata(completion: dict[str, Any], validation_status: str) -> dict[str, Any]:
    return {
        "provider": completion.get("provider"),
        "model": completion.get("model"),
        "usage": completion.get("usage"),
        "repaired": completion.get("repaired", False),
        "validation_status": validation_status,
    }


def _embedding_metadata(completion: dict[str, Any], validation_status: str) -> dict[str, Any]:
    return {
        "provider": completion.get("provider"),
        "model": completion.get("model"),
        "usage": completion.get("usage"),
        "validation_status": validation_status,
        "embedding_count": len(completion.get("embeddings", [])),
    }
