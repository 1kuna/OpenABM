from __future__ import annotations

from typing import Any

READ_TRACE_SCOPE = ["traces:read"]
WRITE_TRACE_SCOPE = ["traces:write"]
READ_BEHAVIOR_SCOPE = ["behaviors:read"]
WRITE_BEHAVIOR_SCOPE = ["behaviors:write"]
READ_CONTEXT_SCOPE = ["context_packs:read"]
WRITE_CONTEXT_SCOPE = ["context_packs:write"]
READ_DATASET_SCOPE = ["datasets:read"]
WRITE_DATASET_SCOPE = ["datasets:write"]
READ_DOCS_SCOPE = ["docs:read"]
WRITE_EVAL_SCOPE = ["evals:write"]
READ_ISSUE_SCOPE = ["issues:read"]
WRITE_ISSUE_SCOPE = ["issues:write"]
READ_INVESTIGATION_SCOPE = ["investigations:read"]
WRITE_INVESTIGATION_SCOPE = ["investigations:write"]
READ_JUDGE_SCOPE = ["judges:read"]
WRITE_JUDGE_SCOPE = ["judges:write"]
WRITE_SCORE_SCOPE = ["scores:write"]
READ_REVIEW_SCOPE = ["reviews:read"]
WRITE_REVIEW_SCOPE = ["reviews:write"]
READ_PROMPT_SCOPE = ["prompts:read"]
WRITE_PROMPT_SCOPE = ["prompts:write"]
READ_AGENT_CONFIG_SCOPE = ["agent_configs:read"]
WRITE_AGENT_CONFIG_SCOPE = ["agent_configs:write"]
READ_AUTOMATION_SCOPE = ["automations:read"]

STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}
OBJECT = {"type": "object"}
ARRAY = {"type": "array"}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 200}


def _schema(
    required: list[str],
    properties: dict[str, dict[str, Any]],
    *,
    additional_properties: bool = True,
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": additional_properties,
    }


def _tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    scopes: list[str],
    side_effects: bool = False,
    confirmation_required: bool = False,
    example_request: dict[str, Any] | None = None,
    example_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_input_schema = input_schema
    if confirmation_required:
        effective_input_schema = {
            **input_schema,
            "properties": {
                **input_schema.get("properties", {}),
                "confirmed": {"type": "boolean"},
            },
        }
    return {
        "name": name,
        "description": description,
        "input_schema": effective_input_schema,
        "output_schema": {"type": "object"},
        "required_scopes": scopes,
        "side_effects": side_effects,
        "confirmation_required": confirmation_required,
        "rate_limit": "local-default",
        "example_request": example_request or {},
        "example_response": example_response or {},
    }


REQUIRED_TOOL_NAMES = [
    "search_traces",
    "search_spans",
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
    "list_affected_entities",
    "get_affected_entity",
    "update_affected_entity",
    "get_agent_context_pack",
    "create_agent_context_pack",
    "list_review_tasks",
    "update_review_task",
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
    "render_prompt",
    "commit_prompt",
    "list_agent_configs",
    "get_agent_config",
    "commit_agent_config",
    "compare_agent_configs",
    "list_automations",
    "get_automation",
    "search_docs",
]


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool(
        "search_traces",
        "Search traces by structured filters and full-text query.",
        _schema(
            ["project_id"],
            {"project_id": STRING, "query": STRING, "filters": OBJECT, "limit": LIMIT},
        ),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo", "query": "wrong tool", "limit": 20},
        example_response={"data": [{"trace_id": "trace_wrong_tool"}]},
    ),
    _tool(
        "search_spans",
        "Search spans by structured filters and full-text query.",
        _schema(
            ["project_id"],
            {"project_id": STRING, "query": STRING, "filters": OBJECT, "limit": LIMIT},
        ),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo", "query": "order lookup", "limit": 20},
        example_response={"data": [{"span_id": "span_wrong_tool_order_lookup"}]},
    ),
    _tool(
        "get_trace",
        "Fetch reconstructed trace detail, including spans and payload availability.",
        _schema(["project_id", "trace_id"], {"project_id": STRING, "trace_id": STRING}),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo", "trace_id": "trace_wrong_tool"},
        example_response={"trace": {"trace_id": "trace_wrong_tool"}, "spans": []},
    ),
    _tool(
        "get_span",
        "Fetch one span by ID for focused evidence inspection.",
        _schema(["project_id", "span_id"], {"project_id": STRING, "span_id": STRING}),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo", "span_id": "span_wrong_tool_order_lookup"},
        example_response={"span_id": "span_wrong_tool_order_lookup"},
    ),
    _tool(
        "list_saved_searches",
        "List reusable saved searches for a project.",
        _schema(["project_id"], {"project_id": STRING}),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo"},
        example_response={"data": []},
    ),
    _tool(
        "get_saved_search",
        "Fetch one saved search definition.",
        _schema(
            ["project_id", "saved_search_id"], {"project_id": STRING, "saved_search_id": STRING}
        ),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo", "saved_search_id": "saved_search_123"},
        example_response={"saved_search_id": "saved_search_123"},
    ),
    _tool(
        "create_saved_search",
        "Create a reusable saved search for repeated investigations or eval inputs.",
        _schema(
            ["project_id", "name", "query"],
            {"project_id": STRING, "name": STRING, "query": STRING, "filters": OBJECT},
        ),
        scopes=WRITE_TRACE_SCOPE,
        side_effects=True,
        example_request={"project_id": "proj_demo", "name": "Refund errors", "query": "refund"},
        example_response={"saved_search_id": "saved_search_123"},
    ),
    _tool(
        "create_issue",
        "Create an issue from a trace, session, manual report, or weak human report.",
        _schema(
            ["project_id", "title"],
            {
                "project_id": STRING,
                "title": STRING,
                "description": NULLABLE_STRING,
                "source_type": STRING,
                "seed_trace_id_nullable": NULLABLE_STRING,
                "seed_session_id_nullable": NULLABLE_STRING,
            },
        ),
        scopes=WRITE_ISSUE_SCOPE,
        side_effects=True,
        example_request={"project_id": "proj_demo", "title": "Refund workflow uses wrong tool"},
        example_response={"issue_id": "issue_123"},
    ),
    _tool(
        "get_issue",
        "Fetch one issue and its seed trace/session metadata.",
        _schema(["project_id", "issue_id"], {"project_id": STRING, "issue_id": STRING}),
        scopes=READ_ISSUE_SCOPE,
        example_request={"project_id": "proj_demo", "issue_id": "issue_123"},
        example_response={"issue_id": "issue_123"},
    ),
    _tool(
        "start_investigation_run",
        "Start an auditable investigation run from issue or seed-trace context.",
        _schema(
            ["project_id"],
            {
                "project_id": STRING,
                "issue_id_nullable": NULLABLE_STRING,
                "seed_trace_id_nullable": NULLABLE_STRING,
                "problem_statement": STRING,
                "filters": OBJECT,
            },
        ),
        scopes=WRITE_INVESTIGATION_SCOPE,
        side_effects=True,
        example_request={"project_id": "proj_demo", "seed_trace_id_nullable": "trace_wrong_tool"},
        example_response={"investigation_run_id": "investigation_run_123"},
    ),
    _tool(
        "get_investigation_run",
        "Fetch an investigation run with stored inputs, outputs, and orchestration metadata.",
        _schema(
            ["project_id", "investigation_run_id"],
            {"project_id": STRING, "investigation_run_id": STRING},
        ),
        scopes=READ_INVESTIGATION_SCOPE,
        example_request={
            "project_id": "proj_demo",
            "investigation_run_id": "investigation_run_123",
        },
        example_response={"investigation_run_id": "investigation_run_123"},
    ),
    _tool(
        "get_impact_report",
        "Fetch an impact report with affected entities and cohort breakdowns.",
        _schema(["project_id", "report_id"], {"project_id": STRING, "report_id": STRING}),
        scopes=READ_INVESTIGATION_SCOPE,
        example_request={"project_id": "proj_demo", "report_id": "impact_report_123"},
        example_response={"report_id": "impact_report_123"},
    ),
    _tool(
        "list_affected_entities",
        "List affected entities for an issue or project remediation view.",
        _schema(
            ["project_id"],
            {"project_id": STRING, "issue_id": NULLABLE_STRING},
        ),
        scopes=READ_INVESTIGATION_SCOPE,
        example_request={"project_id": "proj_demo", "issue_id": "issue_123"},
        example_response={"data": []},
    ),
    _tool(
        "get_affected_entity",
        "Fetch one affected entity remediation record.",
        _schema(
            ["project_id", "affected_entity_id"],
            {"project_id": STRING, "affected_entity_id": STRING},
        ),
        scopes=READ_INVESTIGATION_SCOPE,
        example_request={
            "project_id": "proj_demo",
            "affected_entity_id": "affected_entity_123",
        },
        example_response={"affected_entity_id": "affected_entity_123"},
    ),
    _tool(
        "update_affected_entity",
        "Update remediation status, owner, or notes for an affected entity.",
        _schema(
            ["project_id", "affected_entity_id"],
            {
                "project_id": STRING,
                "affected_entity_id": STRING,
                "status": STRING,
                "owner_nullable": NULLABLE_STRING,
                "notes_nullable": NULLABLE_STRING,
                "remediation_target_type": STRING,
                "remediation_target_id": STRING,
                "remediation_relation": STRING,
            },
        ),
        scopes=WRITE_INVESTIGATION_SCOPE,
        side_effects=True,
        confirmation_required=True,
        example_request={
            "project_id": "proj_demo",
            "affected_entity_id": "affected_entity_123",
            "status": "fixed",
            "remediation_target_type": "eval_run",
            "remediation_target_id": "eval_run_123",
        },
        example_response={"affected_entity_id": "affected_entity_123", "status": "fixed"},
    ),
    _tool(
        "get_agent_context_pack",
        "Fetch a bounded context pack suitable for model or coding-agent review.",
        _schema(
            ["project_id", "context_pack_id"], {"project_id": STRING, "context_pack_id": STRING}
        ),
        scopes=READ_CONTEXT_SCOPE,
        example_request={"project_id": "proj_demo", "context_pack_id": "context_pack_123"},
        example_response={"context_pack_id": "context_pack_123"},
    ),
    _tool(
        "create_agent_context_pack",
        "Create a cited agent context pack from trace evidence.",
        _schema(
            ["project_id", "source_trace_ids"],
            {
                "project_id": STRING,
                "source_trace_ids": ARRAY,
                "issue_id_nullable": NULLABLE_STRING,
                "allowed_next_actions": ARRAY,
                "redaction_policy": OBJECT,
            },
        ),
        scopes=WRITE_CONTEXT_SCOPE,
        side_effects=True,
        example_request={"project_id": "proj_demo", "source_trace_ids": ["trace_wrong_tool"]},
        example_response={"context_pack_id": "context_pack_123"},
    ),
    _tool(
        "list_review_tasks",
        (
            "List human review tasks for judge outputs, behavior candidates, "
            "grounding, root causes, and affected entities."
        ),
        _schema(
            ["project_id"],
            {"project_id": STRING, "status": STRING, "task_type": STRING},
        ),
        scopes=READ_REVIEW_SCOPE,
        example_request={"project_id": "proj_demo", "status": "open"},
        example_response={"data": []},
    ),
    _tool(
        "update_review_task",
        "Record a human review decision on an existing review task.",
        _schema(
            ["project_id", "review_task_id", "status", "decision"],
            {
                "project_id": STRING,
                "review_task_id": STRING,
                "status": STRING,
                "decision": STRING,
                "notes": NULLABLE_STRING,
            },
        ),
        scopes=WRITE_REVIEW_SCOPE,
        side_effects=True,
        confirmation_required=True,
        example_request={
            "project_id": "proj_demo",
            "review_task_id": "review_task_123",
            "status": "accepted",
            "decision": "accepted",
        },
        example_response={"review_task_id": "review_task_123", "status": "accepted"},
    ),
    _tool(
        "list_sessions",
        "List sessions for timeline or cohort navigation.",
        _schema(["project_id"], {"project_id": STRING, "limit": LIMIT}),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo", "limit": 20},
        example_response={"data": []},
    ),
    _tool(
        "get_session",
        "Fetch traces and summary metadata for one session.",
        _schema(["project_id", "session_id"], {"project_id": STRING, "session_id": STRING}),
        scopes=READ_TRACE_SCOPE,
        example_request={"project_id": "proj_demo", "session_id": "session_123"},
        example_response={"session_id": "session_123", "traces": []},
    ),
    _tool(
        "list_behaviors",
        "List known behavior definitions for filtering, judging, or eval design.",
        _schema(["project_id"], {"project_id": STRING}),
        scopes=READ_BEHAVIOR_SCOPE,
        example_request={"project_id": "proj_demo"},
        example_response={"data": []},
    ),
    _tool(
        "get_behavior",
        "Fetch one behavior definition and detector.",
        _schema(["project_id", "behavior_id"], {"project_id": STRING, "behavior_id": STRING}),
        scopes=READ_BEHAVIOR_SCOPE,
        example_request={"project_id": "proj_demo", "behavior_id": "behavior_123"},
        example_response={"behavior_id": "behavior_123"},
    ),
    _tool(
        "create_behavior_draft",
        "Create a draft behavior definition for human review.",
        _schema(
            ["project_id", "name"],
            {
                "project_id": STRING,
                "name": STRING,
                "description": NULLABLE_STRING,
                "severity": STRING,
                "detector": OBJECT,
            },
        ),
        scopes=WRITE_BEHAVIOR_SCOPE,
        side_effects=True,
        example_request={"project_id": "proj_demo", "name": "wrong_tool_for_refund"},
        example_response={"behavior_id": "behavior_123", "status": "draft"},
    ),
    _tool(
        "list_judges",
        "List judge definitions and versions available to score traces or evals.",
        _schema(["project_id"], {"project_id": STRING}),
        scopes=READ_JUDGE_SCOPE,
        example_request={"project_id": "proj_demo"},
        example_response={"data": []},
    ),
    _tool(
        "get_judge",
        "Fetch one judge definition and latest version metadata.",
        _schema(["project_id", "judge_id"], {"project_id": STRING, "judge_id": STRING}),
        scopes=READ_JUDGE_SCOPE,
        example_request={"project_id": "proj_demo", "judge_id": "judge_123"},
        example_response={"judge_id": "judge_123"},
    ),
    _tool(
        "run_judge",
        "Run a judge against one trace and persist the scored result.",
        _schema(
            ["project_id", "trace_id", "judge"],
            {"project_id": STRING, "trace_id": STRING, "judge": OBJECT},
        ),
        scopes=WRITE_SCORE_SCOPE,
        side_effects=True,
        example_request={"project_id": "proj_demo", "trace_id": "trace_wrong_tool", "judge": {}},
        example_response={"score_id": "score_123", "status": "succeeded"},
    ),
    _tool(
        "create_judge_draft",
        "Create a judge draft from explicit definition or model-assisted request.",
        _schema(
            ["project_id"],
            {
                "project_id": STRING,
                "name": STRING,
                "judge_type": STRING,
                "definition": OBJECT,
                "trace_id": STRING,
                "instructions": STRING,
            },
        ),
        scopes=WRITE_JUDGE_SCOPE,
        side_effects=True,
        example_request={"project_id": "proj_demo", "name": "Refund policy judge"},
        example_response={"judge_id": "judge_123"},
    ),
    _tool(
        "list_datasets",
        "List datasets available for evals and regression suites.",
        _schema(["project_id"], {"project_id": STRING}),
        scopes=READ_DATASET_SCOPE,
        example_request={"project_id": "proj_demo"},
        example_response={"data": []},
    ),
    _tool(
        "get_dataset",
        "Fetch one dataset definition and latest version metadata.",
        _schema(["project_id", "dataset_id"], {"project_id": STRING, "dataset_id": STRING}),
        scopes=READ_DATASET_SCOPE,
        example_request={"project_id": "proj_demo", "dataset_id": "dataset_123"},
        example_response={"dataset_id": "dataset_123"},
    ),
    _tool(
        "add_trace_to_dataset",
        "Add one trace as a dataset example for eval or regression coverage.",
        _schema(
            ["project_id", "dataset_id", "trace_id"],
            {
                "project_id": STRING,
                "dataset_id": STRING,
                "trace_id": STRING,
                "labels": ARRAY,
                "metadata": OBJECT,
            },
        ),
        scopes=WRITE_DATASET_SCOPE,
        side_effects=True,
        confirmation_required=True,
        example_request={
            "project_id": "proj_demo",
            "dataset_id": "dataset_123",
            "trace_id": "trace_wrong_tool",
        },
        example_response={"dataset_example_id": "dataset_example_123"},
    ),
    _tool(
        "run_eval",
        "Run an eval against a dataset version with one or more judges.",
        _schema(
            ["project_id", "dataset_version_id"],
            {
                "project_id": STRING,
                "dataset_version_id": STRING,
                "judges": ARRAY,
                "judge_ids": ARRAY,
                "baseline_eval_run_id": NULLABLE_STRING,
                "prompt_version_id": NULLABLE_STRING,
                "agent_config_version_id": NULLABLE_STRING,
                "runtime_context": OBJECT,
            },
        ),
        scopes=WRITE_EVAL_SCOPE,
        side_effects=True,
        confirmation_required=True,
        example_request={"project_id": "proj_demo", "dataset_version_id": "dataset_version_123"},
        example_response={"eval_run_id": "eval_run_123"},
    ),
    _tool(
        "compare_eval_runs",
        "Compare two eval runs and report score plus provenance deltas.",
        _schema(
            ["project_id", "baseline_eval_run_id", "candidate_eval_run_id"],
            {"project_id": STRING, "baseline_eval_run_id": STRING, "candidate_eval_run_id": STRING},
        ),
        scopes=WRITE_EVAL_SCOPE,
        side_effects=True,
        example_request={
            "project_id": "proj_demo",
            "baseline_eval_run_id": "eval_run_base",
            "candidate_eval_run_id": "eval_run_candidate",
        },
        example_response={"status": "compared"},
    ),
    _tool(
        "list_prompts",
        "List prompt registry entries and current version pointers.",
        _schema(["project_id"], {"project_id": STRING}),
        scopes=READ_PROMPT_SCOPE,
        example_request={"project_id": "proj_demo"},
        example_response={"data": []},
    ),
    _tool(
        "get_prompt",
        "Fetch one prompt registry entry with version history.",
        _schema(["project_id", "prompt_id"], {"project_id": STRING, "prompt_id": STRING}),
        scopes=READ_PROMPT_SCOPE,
        example_request={"project_id": "proj_demo", "prompt_id": "prompt_123"},
        example_response={"prompt_id": "prompt_123"},
    ),
    _tool(
        "render_prompt",
        "Render a prompt version with deterministic variables and optional audited secret refs.",
        _schema(
            ["project_id", "prompt_id", "commit_id", "variables"],
            {
                "project_id": STRING,
                "prompt_id": STRING,
                "commit_id": STRING,
                "variables": OBJECT,
                "resolve_secret_refs": {"type": "boolean"},
                "purpose": NULLABLE_STRING,
            },
        ),
        scopes=READ_PROMPT_SCOPE,
        example_request={
            "project_id": "proj_demo",
            "prompt_id": "prompt_123",
            "commit_id": "prompt_commit",
            "variables": {"name": "OpenABM"},
        },
        example_response={"rendered": "Hi OpenABM"},
    ),
    _tool(
        "commit_prompt",
        "Commit a new immutable prompt version.",
        _schema(
            ["project_id", "prompt_id", "template_text", "variables_schema"],
            {
                "project_id": STRING,
                "prompt_id": STRING,
                "template_text": STRING,
                "variables_schema": OBJECT,
                "metadata": OBJECT,
                "parent_commit_id": NULLABLE_STRING,
                "tag": NULLABLE_STRING,
            },
        ),
        scopes=WRITE_PROMPT_SCOPE,
        side_effects=True,
        confirmation_required=True,
        example_request={
            "project_id": "proj_demo",
            "prompt_id": "prompt_123",
            "template_text": "Use cited evidence for {{name}}.",
            "variables_schema": {"type": "object", "required": ["name"]},
        },
        example_response={"prompt_version_id": "prompt_version_123"},
    ),
    _tool(
        "list_agent_configs",
        "List agent runtime configuration registry entries.",
        _schema(["project_id"], {"project_id": STRING}),
        scopes=READ_AGENT_CONFIG_SCOPE,
        example_request={"project_id": "proj_demo"},
        example_response={"data": []},
    ),
    _tool(
        "get_agent_config",
        "Fetch one agent runtime configuration and version history.",
        _schema(
            ["project_id", "agent_config_id"], {"project_id": STRING, "agent_config_id": STRING}
        ),
        scopes=READ_AGENT_CONFIG_SCOPE,
        example_request={"project_id": "proj_demo", "agent_config_id": "agent_config_123"},
        example_response={"agent_config_id": "agent_config_123"},
    ),
    _tool(
        "commit_agent_config",
        "Commit an immutable agent runtime configuration version and optionally "
        "move a mutable tag pointer.",
        _schema(
            ["project_id", "agent_config_id", "content"],
            {
                "project_id": STRING,
                "agent_config_id": STRING,
                "content": OBJECT,
                "metadata": OBJECT,
                "tag": STRING,
            },
        ),
        scopes=WRITE_AGENT_CONFIG_SCOPE,
        side_effects=True,
        confirmation_required=True,
        example_request={
            "project_id": "proj_demo",
            "agent_config_id": "agent_config_123",
            "content": {"model": "qwen3.5-9b-mlx", "tools": ["search_traces"]},
            "tag": "prod",
        },
        example_response={"agent_config_version_id": "agent_config_version_123"},
    ),
    _tool(
        "compare_agent_configs",
        "Compare two immutable agent config commits.",
        _schema(
            ["project_id", "agent_config_id", "old_commit_id", "new_commit_id"],
            {
                "project_id": STRING,
                "agent_config_id": STRING,
                "old_commit_id": STRING,
                "new_commit_id": STRING,
            },
        ),
        scopes=READ_AGENT_CONFIG_SCOPE,
        example_request={
            "project_id": "proj_demo",
            "agent_config_id": "agent_config_123",
            "old_commit_id": "commit_old",
            "new_commit_id": "commit_new",
        },
        example_response={"changed_fields": []},
    ),
    _tool(
        "list_automations",
        "List automations for reviews, notifications, or remediation workflows.",
        _schema(["project_id"], {"project_id": STRING}),
        scopes=READ_AUTOMATION_SCOPE,
        example_request={"project_id": "proj_demo"},
        example_response={"data": []},
    ),
    _tool(
        "get_automation",
        "Fetch one automation definition and current status.",
        _schema(["project_id", "automation_id"], {"project_id": STRING, "automation_id": STRING}),
        scopes=READ_AUTOMATION_SCOPE,
        example_request={"project_id": "proj_demo", "automation_id": "automation_123"},
        example_response={"automation_id": "automation_123"},
    ),
    _tool(
        "search_docs",
        "Search bundled public OpenABM docs for tool, API, or product guidance.",
        _schema(["project_id", "query"], {"project_id": STRING, "query": STRING, "limit": LIMIT}),
        scopes=READ_DOCS_SCOPE,
        example_request={"project_id": "proj_demo", "query": "judge registry"},
        example_response={"data": []},
    ),
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
        "required_scopes": WRITE_ISSUE_SCOPE if side_effect else READ_TRACE_SCOPE,
        "side_effects": side_effect,
        "confirmation_required": name in {"add_trace_to_dataset", "run_eval", "commit_prompt"},
        "rate_limit": "local-default",
        "example_request": {},
        "example_response": {},
    }
