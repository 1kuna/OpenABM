from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

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
    builder.add_node("persist_investigation_run", _persist_investigation_run(store))
    builder.add_edge(START, "generate_candidate_search_queries")
    builder.add_edge("generate_candidate_search_queries", "run_structured_search")
    builder.add_edge("run_structured_search", "run_full_text_search")
    builder.add_edge("run_full_text_search", "persist_investigation_run")
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


def _persist_investigation_run(store: Any) -> Any:
    def node(state: InvestigationWorkflowState) -> dict[str, Any]:
        request = state["request"]
        run = store.start_investigation(request)
        result = dict(run["result"])
        result["orchestration"] = {
            "framework": "langgraph",
            "graph_version": GRAPH_VERSION,
            "candidate_search_queries": state.get("candidate_search_queries", []),
            "structured_trace_ids": state.get("structured_trace_ids", []),
            "full_text_trace_ids": state.get("full_text_trace_ids", []),
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
