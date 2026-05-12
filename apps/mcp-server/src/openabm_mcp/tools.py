from __future__ import annotations

from typing import Any

READ_SCOPE = ["traces:read"]
WRITE_DRAFT_SCOPE = ["drafts:write"]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_traces",
        "description": "Search traces by structured filters and text query.",
        "input_schema": {"type": "object", "required": ["project_id"]},
        "output_schema": {"type": "object"},
        "required_scopes": READ_SCOPE,
        "side_effects": False,
        "confirmation_required": False,
        "rate_limit": "local-default",
        "example_request": {"project_id": "proj_demo", "query": "wrong tool"},
        "example_response": {"traces": []},
    },
    {
        "name": "get_trace",
        "description": "Fetch reconstructed trace detail.",
        "input_schema": {"type": "object", "required": ["project_id", "trace_id"]},
        "output_schema": {"type": "object"},
        "required_scopes": READ_SCOPE,
        "side_effects": False,
        "confirmation_required": False,
        "rate_limit": "local-default",
        "example_request": {"project_id": "proj_demo", "trace_id": "trace_123"},
        "example_response": {"trace": {"trace_id": "trace_123"}},
    },
]

REQUIRED_TOOL_NAMES = [
    "search_traces",
    "get_trace",
    "get_span",
    "list_saved_searches",
    "get_saved_search",
    "create_saved_search",
    "create_issue",
    "get_issue",
    "start_investigation_run",
    "get_investigation_run",
    "get_impact_report",
    "get_agent_context_pack",
    "list_sessions",
    "get_session",
    "list_behaviors",
    "get_behavior",
    "create_behavior_draft",
    "list_judges",
    "get_judge",
    "run_judge",
    "create_judge_draft",
    "list_datasets",
    "get_dataset",
    "add_trace_to_dataset",
    "run_eval",
    "compare_eval_runs",
    "list_prompts",
    "get_prompt",
    "commit_prompt",
    "list_agent_configs",
    "get_agent_config",
    "compare_agent_configs",
    "list_automations",
    "get_automation",
    "search_docs",
]


def all_tool_definitions() -> list[dict[str, Any]]:
    existing = {tool["name"]: tool for tool in TOOL_DEFINITIONS}
    for name in REQUIRED_TOOL_NAMES:
        if name not in existing:
            existing[name] = _placeholder_tool(name)
    return [existing[name] for name in REQUIRED_TOOL_NAMES]


def _placeholder_tool(name: str) -> dict[str, Any]:
    side_effect = name.startswith(("create_", "add_", "run_", "commit_"))
    return {
        "name": name,
        "description": f"OpenABM scaffold tool contract for {name}.",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "required_scopes": WRITE_DRAFT_SCOPE if side_effect else READ_SCOPE,
        "side_effects": side_effect,
        "confirmation_required": name in {"add_trace_to_dataset", "run_eval", "commit_prompt"},
        "rate_limit": "local-default",
        "example_request": {},
        "example_response": {},
    }
