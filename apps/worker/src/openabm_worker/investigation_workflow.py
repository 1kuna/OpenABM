from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from openabm_worker.similarity import rank_similar_traces_from_vectors

GRAPH_VERSION = "openabm_investigation_graph_v1"


RESOURCE_FIELDS = {
    "trace_id": "trace",
    "span_id": "span",
    "session_id": "session",
    "behavior_id": "behavior",
    "judge_id": "judge",
    "dataset_id": "dataset",
    "prompt_id": "prompt",
    "eval_run_id": "eval-run",
    "automation_id": "automation",
    "saved_search_id": "saved-search",
    "issue_id": "issue",
    "investigation_run_id": "investigation-run",
    "impact_report_id": "impact-report",
    "report_id": "impact-report",
    "context_pack_id": "agent-context-pack",
}


class InvestigationWorkflowState(TypedDict, total=False):
    project_id: str
    request: dict[str, Any]
    candidate_search_queries: list[str]
    structured_trace_ids: list[str]
    full_text_trace_ids: list[str]
    semantic_trace_ids: list[str]
    semantic_similarity: dict[str, Any]
    orchestration_events: list[dict[str, Any]]
    run: dict[str, Any]


def run_investigation_workflow(store: Any, request: dict[str, Any]) -> dict[str, Any]:
    graph = _build_investigation_graph(store)
    state = graph.invoke(
        {
            "project_id": request["project_id"],
            "request": request,
            "orchestration_events": [],
        }
    )
    return state["run"]


def _build_investigation_graph(store: Any) -> Any:
    builder = StateGraph(InvestigationWorkflowState)
    builder.add_node("generate_candidate_search_queries", _generate_candidate_search_queries)
    builder.add_node("run_structured_search", _run_structured_search(store))
    builder.add_node("run_full_text_search", _run_full_text_search(store))
    builder.add_node("run_semantic_similarity_search", _run_semantic_similarity_search(store))
    builder.add_node("persist_investigation_run", _persist_investigation_run(store))
    builder.add_edge(START, "generate_candidate_search_queries")
    builder.add_edge("generate_candidate_search_queries", "run_structured_search")
    builder.add_edge("run_structured_search", "run_full_text_search")
    builder.add_edge("run_full_text_search", "run_semantic_similarity_search")
    builder.add_edge("run_semantic_similarity_search", "persist_investigation_run")
    builder.add_edge("persist_investigation_run", END)
    return builder.compile()


def _generate_candidate_search_queries(
    state: InvestigationWorkflowState,
) -> dict[str, Any]:
    request = state["request"]
    queries = []
    for value in [
        request.get("natural_language_problem_nullable"),
        request.get("query"),
    ]:
        if isinstance(value, str) and value.strip() and value.strip() not in queries:
            queries.append(value.strip())
    return {
        "candidate_search_queries": queries,
        "orchestration_events": _append_event(
            state,
            {
                "node": "generate_candidate_search_queries",
                "tool": "query_planner",
                "side_effects": False,
                "input": {
                    "has_natural_language_problem": bool(
                        request.get("natural_language_problem_nullable")
                    ),
                    "has_seed_trace": bool(request.get("seed_trace_id_nullable")),
                },
                "output": {"query_count": len(queries)},
            },
        ),
    }


def _run_structured_search(store: Any) -> Any:
    def node(state: InvestigationWorkflowState) -> dict[str, Any]:
        request = state["request"]
        project_id = state["project_id"]
        filters = request.get("filters") or {}
        limit = int(request.get("limit", 50))
        traces = store.search_traces(project_id, filters=filters, limit=limit)
        trace_ids = [trace["trace_id"] for trace in traces]
        return {
            "structured_trace_ids": trace_ids,
            "orchestration_events": _append_event(
                state,
                {
                    "node": "run_structured_search",
                    "tool": "search_traces",
                    "side_effects": False,
                    "input": {"filters": filters, "limit": limit},
                    "output": {"trace_ids": trace_ids},
                },
            ),
        }

    return node


def _run_full_text_search(store: Any) -> Any:
    def node(state: InvestigationWorkflowState) -> dict[str, Any]:
        request = state["request"]
        project_id = state["project_id"]
        filters = request.get("filters") or {}
        limit = int(request.get("limit", 50))
        trace_ids = []
        for query in state.get("candidate_search_queries", []):
            traces = store.search_traces(
                project_id,
                filters=filters,
                full_text_query=query,
                limit=limit,
            )
            for trace in traces:
                if trace["trace_id"] not in trace_ids:
                    trace_ids.append(trace["trace_id"])
        return {
            "full_text_trace_ids": trace_ids,
            "orchestration_events": _append_event(
                state,
                {
                    "node": "run_full_text_search",
                    "tool": "search_traces",
                    "side_effects": False,
                    "input": {
                        "query_count": len(state.get("candidate_search_queries", [])),
                        "filters": filters,
                        "limit": limit,
                    },
                    "output": {"trace_ids": trace_ids},
                },
            ),
        }

    return node


def _run_semantic_similarity_search(store: Any) -> Any:
    def node(state: InvestigationWorkflowState) -> dict[str, Any]:
        request = state["request"]
        project_id = state["project_id"]
        seed_trace_id = request.get("seed_trace_id_nullable")
        if not isinstance(seed_trace_id, str) or not seed_trace_id:
            return _semantic_similarity_state(
                state,
                {
                    "status": "skipped",
                    "reason": "seed_trace_required",
                    "matches": [],
                },
            )

        representation_version = _select_similarity_representation(
            store,
            project_id,
            request.get("similarity_representation_version"),
        )
        if representation_version is None:
            return _semantic_similarity_state(
                state,
                {
                    "status": "skipped",
                    "reason": "no_similarity_index",
                    "matches": [],
                },
            )

        source_vector = store.get_similarity_vector(
            project_id,
            "trace",
            seed_trace_id,
            representation_version,
        )
        if source_vector is None:
            return _semantic_similarity_state(
                state,
                {
                    "status": "skipped",
                    "reason": "source_trace_not_indexed",
                    "representation_version": representation_version,
                    "matches": [],
                },
            )

        scoped_trace_ids = set(state.get("structured_trace_ids", []))
        candidate_trace_vectors = [
            vector
            for vector in store.list_similarity_vectors(
                project_id,
                representation_version,
                entity_type="trace",
            )
            if vector["entity_id"] != seed_trace_id
            and (not scoped_trace_ids or vector["entity_id"] in scoped_trace_ids)
        ]
        if not candidate_trace_vectors:
            return _semantic_similarity_state(
                state,
                {
                    "status": "skipped",
                    "reason": "no_indexed_candidates",
                    "representation_version": representation_version,
                    "matches": [],
                },
            )

        candidate_trace_ids = [vector["entity_id"] for vector in candidate_trace_vectors]
        result = rank_similar_traces_from_vectors(
            source_vector=source_vector,
            candidate_trace_vectors=candidate_trace_vectors,
            candidate_span_vectors=store.list_similarity_vectors(
                project_id,
                representation_version,
                entity_type="span",
                trace_ids=candidate_trace_ids,
            ),
            limit=int(request.get("limit", 50)),
        )
        result["representation_version"] = representation_version
        return _semantic_similarity_state(state, result)

    return node


def _persist_investigation_run(store: Any) -> Any:
    def node(state: InvestigationWorkflowState) -> dict[str, Any]:
        request = state["request"]
        enriched_request = {
            **request,
            "candidate_trace_ids": _ordered_unique(
                [
                    *state.get("structured_trace_ids", []),
                    *state.get("full_text_trace_ids", []),
                    *state.get("semantic_trace_ids", []),
                ]
            ),
        }
        run = store.start_investigation(enriched_request)
        result = dict(run["result"])
        semantic_similarity = state.get(
            "semantic_similarity",
            {"status": "skipped", "reason": "not_run", "matches": []},
        )
        result["semantic_similarity"] = semantic_similarity
        if semantic_similarity.get("status") == "succeeded":
            result["llm_deferred"] = [
                item for item in result.get("llm_deferred", []) if item != "semantic similarity"
            ]
        result["orchestration"] = {
            "framework": "langgraph",
            "graph_version": GRAPH_VERSION,
            "candidate_search_queries": state.get("candidate_search_queries", []),
            "structured_trace_ids": state.get("structured_trace_ids", []),
            "full_text_trace_ids": state.get("full_text_trace_ids", []),
            "semantic_trace_ids": state.get("semantic_trace_ids", []),
            "tool_calls": _append_event(
                state,
                {
                    "node": "persist_investigation_run",
                    "tool": "start_investigation",
                    "side_effects": True,
                    "input": {
                        "project_id": request["project_id"],
                        "seed_trace_id_nullable": request.get("seed_trace_id_nullable"),
                        "issue_id_nullable": request.get("issue_id_nullable"),
                    },
                    "output": {
                        "investigation_run_id": run["investigation_run_id"],
                        "impact_report_id": run["result"]["impact_report"]["report_id"],
                    },
                },
            ),
        }
        run = store.update_investigation_result(
            request["project_id"],
            run["investigation_run_id"],
            result,
        )
        return {"run": run, "orchestration_events": result["orchestration"]["tool_calls"]}

    return node


def _semantic_similarity_state(
    state: InvestigationWorkflowState,
    result: dict[str, Any],
) -> dict[str, Any]:
    trace_ids = [
        match["trace_id"]
        for match in result.get("matches", [])
        if isinstance(match, dict) and isinstance(match.get("trace_id"), str)
    ]
    return {
        "semantic_trace_ids": trace_ids,
        "semantic_similarity": result,
        "orchestration_events": _append_event(
            state,
            {
                "node": "run_semantic_similarity_search",
                "tool": "search_similar",
                "status": result.get("status", "succeeded"),
                "side_effects": False,
                "input": {
                    "seed_trace_id_nullable": state["request"].get("seed_trace_id_nullable"),
                    "representation_version": result.get("representation_version"),
                },
                "output": {
                    "reason": result.get("reason"),
                    "trace_ids": trace_ids,
                    "match_count": len(trace_ids),
                },
            },
        ),
    }


def _select_similarity_representation(
    store: Any,
    project_id: str,
    requested: Any,
) -> str | None:
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    representations = [
        item
        for item in store.similarity_index_summary(project_id).get("representations", [])
        if item.get("entity_type") == "trace"
    ]
    if not representations:
        return None
    selected = sorted(
        representations,
        key=lambda item: (
            str(item.get("last_updated_at") or ""),
            str(item.get("representation_version") or ""),
        ),
        reverse=True,
    )[0]
    return str(selected["representation_version"])


def _ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _append_event(
    state: InvestigationWorkflowState,
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    return [*state.get("orchestration_events", []), _normalize_event(event)]


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "status": "succeeded",
        "citations": [],
        "resource_uris": [],
        **event,
    }
    citations, resource_uris = _extract_event_references(
        {"input": normalized.get("input", {}), "output": normalized.get("output", {})}
    )
    normalized["citations"] = citations
    normalized["resource_uris"] = resource_uris
    return normalized


def _extract_event_references(value: Any) -> tuple[list[str], list[str]]:
    citations: set[str] = set()
    resource_uris: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                resource_type = _resource_type_for_field(key)
                if resource_type and isinstance(nested, str):
                    citations.add(nested)
                    resource_uris.add(f"{resource_type}://{nested}")
                elif resource_type and isinstance(nested, list):
                    for candidate in nested:
                        if isinstance(candidate, str):
                            citations.add(candidate)
                            resource_uris.add(f"{resource_type}://{candidate}")
                elif key.endswith("_id") and isinstance(nested, str):
                    citations.add(nested)
                elif key.endswith("_ids") and isinstance(nested, list):
                    citations.update(
                        candidate for candidate in nested if isinstance(candidate, str)
                    )
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return sorted(citations), sorted(resource_uris)


def _resource_type_for_field(field_name: str) -> str | None:
    if field_name in RESOURCE_FIELDS:
        return RESOURCE_FIELDS[field_name]
    if field_name.endswith("trace_ids"):
        return "trace"
    if field_name.endswith("span_ids"):
        return "span"
    return None
