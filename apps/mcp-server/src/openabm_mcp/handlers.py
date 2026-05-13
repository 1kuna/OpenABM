from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from openabm_mcp.tools import all_tool_definitions

UNSUPPORTED_TOOLS: dict[str, str] = {}


RESOURCE_TEMPLATE_DEFINITIONS = [
    {
        "uriTemplate": "trace://{trace_id}",
        "name": "OpenABM trace",
        "description": "Fetch reconstructed trace detail with spans and payload metadata.",
    },
    {
        "uriTemplate": "span://{span_id}",
        "name": "OpenABM span",
        "description": "Fetch one trace span for focused evidence inspection.",
    },
    {
        "uriTemplate": "session://{session_id}",
        "name": "OpenABM session",
        "description": "Fetch a session and its related trace context.",
    },
    {
        "uriTemplate": "behavior://{behavior_id}",
        "name": "OpenABM behavior",
        "description": "Fetch a behavior definition and monitoring metadata.",
    },
    {
        "uriTemplate": "judge://{judge_id}",
        "name": "OpenABM judge",
        "description": "Fetch a judge definition and immutable versions.",
    },
    {
        "uriTemplate": "dataset://{dataset_id}",
        "name": "OpenABM dataset",
        "description": "Fetch a dataset definition and version metadata.",
    },
    {
        "uriTemplate": "prompt://{prompt_id}",
        "name": "OpenABM prompt",
        "description": "Fetch a prompt registry entry and version history.",
    },
    {
        "uriTemplate": "eval-run://{eval_run_id}",
        "name": "OpenABM eval run",
        "description": "Fetch an eval run summary and linked results.",
    },
    {
        "uriTemplate": "automation://{automation_id}",
        "name": "OpenABM automation",
        "description": "Fetch an automation definition and current status.",
    },
    {
        "uriTemplate": "saved-search://{saved_search_id}",
        "name": "OpenABM saved search",
        "description": "Fetch a saved trace-search definition.",
    },
    {
        "uriTemplate": "issue://{issue_id}",
        "name": "OpenABM issue",
        "description": "Fetch an issue with seed trace/session metadata.",
    },
    {
        "uriTemplate": "investigation-run://{investigation_run_id}",
        "name": "OpenABM investigation run",
        "description": "Fetch an auditable investigation run record.",
    },
    {
        "uriTemplate": "impact-report://{report_id}",
        "name": "OpenABM impact report",
        "description": "Fetch an investigation impact report.",
    },
    {
        "uriTemplate": "agent-context-pack://{context_pack_id}",
        "name": "OpenABM agent context pack",
        "description": "Fetch a bounded cited context pack for agent review.",
    },
]
for template in RESOURCE_TEMPLATE_DEFINITIONS:
    template["mimeType"] = "application/json"

RESOURCE_TEMPLATES = [template["uriTemplate"] for template in RESOURCE_TEMPLATE_DEFINITIONS]

MAX_OBSERVATION_STRING_LENGTH = 2000
MAX_OBSERVATION_ITEMS = 25
MAX_OBSERVATION_DEPTH = 5


@dataclass(frozen=True)
class OpenABMApiClient:
    base_url: str
    api_key: str

    @classmethod
    def from_env(cls) -> OpenABMApiClient:
        return cls(
            base_url=os.getenv("OPENABM_API_BASE_URL", "http://127.0.0.1:8787").rstrip("/"),
            api_key=os.getenv("OPENABM_API_KEY", "dev-openabm-key"),
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(base_url=self.base_url, headers=headers) as client:
            response = client.request(method, path, params=params, json=json_body)
        response.raise_for_status()
        return response.json()


def tool_manifest() -> dict[str, Any]:
    return {"tools": all_tool_definitions(), "resource_templates": RESOURCE_TEMPLATES}


def resource_template_manifest() -> list[dict[str, str]]:
    return [dict(template) for template in RESOURCE_TEMPLATE_DEFINITIONS]


def read_resource(
    uri: str,
    *,
    client: OpenABMApiClient | None = None,
) -> dict[str, str]:
    api_client = client or OpenABMApiClient.from_env()
    parsed = _parse_resource_uri(uri)
    project_id = parsed["project_id"]
    resource_type = parsed["resource_type"]
    resource_id = parsed["resource_id"]
    payload = _read_resource_payload(
        api_client,
        project_id=project_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(payload),
    }


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    client: OpenABMApiClient | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    api_client = client or OpenABMApiClient.from_env()
    status = "succeeded"
    error_type = None
    error_message = None
    response_payload: dict[str, Any] | None = None
    try:
        if _tool_requires_confirmation(name):
            if arguments.get("confirmed") is not True:
                result = {
                    "status": "confirmation_required",
                    "tool": name,
                    "message": "Set confirmed=true to execute this side-effecting tool.",
                }
            else:
                result = _call_tool_impl(
                    name,
                    _strip_execution_controls(arguments),
                    client=api_client,
                )
        else:
            result = _call_tool_impl(name, arguments, client=api_client)
        response_payload = result
        result_status = result.get("status")
        if result_status in {"unsupported", "confirmation_required"}:
            status = result_status
        return result
    except Exception as exc:
        status = "failed"
        error_type = type(exc).__name__
        error_message = str(exc)
        response_payload = {
            "error_type": error_type,
            "error_message": error_message,
        }
        raise
    finally:
        _record_tool_observation(
            api_client,
            project_id=arguments.get("project_id"),
            tool_name=name,
            status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_type=error_type,
            error_message=error_message,
            request_payload=arguments,
            response_payload=response_payload,
            confirmation_required=_tool_requires_confirmation(name),
        )


def _call_tool_impl(
    name: str,
    arguments: dict[str, Any],
    *,
    client: OpenABMApiClient,
) -> dict[str, Any]:
    if name in UNSUPPORTED_TOOLS:
        return {
            "status": "unsupported",
            "tool": name,
            "reason": UNSUPPORTED_TOOLS[name],
        }
    if name == "search_traces":
        return client.request("POST", "/v1/search/traces", json_body=arguments)
    if name == "get_trace":
        return client.request(
            "GET",
            f"/v1/traces/{arguments['trace_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_span":
        return client.request(
            "GET",
            f"/v1/spans/{arguments['span_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "list_saved_searches":
        return client.request(
            "GET",
            "/v1/saved-searches",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_saved_search":
        return client.request(
            "GET",
            f"/v1/saved-searches/{arguments['saved_search_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "create_saved_search":
        return client.request("POST", "/v1/saved-searches", json_body=arguments)
    if name == "create_issue":
        return client.request("POST", "/v1/issues", json_body=arguments)
    if name == "get_issue":
        return client.request(
            "GET",
            f"/v1/issues/{arguments['issue_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "start_investigation_run":
        return client.request("POST", "/v1/investigations", json_body=arguments)
    if name == "get_investigation_run":
        return client.request(
            "GET",
            f"/v1/investigations/{arguments['investigation_run_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_impact_report":
        return client.request(
            "GET",
            f"/v1/impact-reports/{arguments['report_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "list_affected_entities":
        params = {"project_id": arguments["project_id"]}
        if arguments.get("issue_id"):
            params["issue_id"] = arguments["issue_id"]
        return client.request("GET", "/v1/affected-entities", params=params)
    if name == "update_affected_entity":
        return client.request(
            "PATCH",
            f"/v1/affected-entities/{arguments['affected_entity_id']}",
            json_body=arguments,
        )
    if name == "get_agent_context_pack":
        return client.request(
            "GET",
            f"/v1/context-packs/{arguments['context_pack_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "create_agent_context_pack":
        return client.request("POST", "/v1/context-packs", json_body=arguments)
    if name == "list_review_tasks":
        params = {"project_id": arguments["project_id"]}
        if arguments.get("status"):
            params["status"] = arguments["status"]
        if arguments.get("task_type"):
            params["task_type"] = arguments["task_type"]
        return client.request("GET", "/v1/review-tasks", params=params)
    if name == "update_review_task":
        return client.request(
            "PATCH",
            f"/v1/review-tasks/{arguments['review_task_id']}",
            json_body=arguments,
        )
    if name == "list_sessions":
        return client.request(
            "GET",
            "/v1/sessions",
            params={"project_id": arguments["project_id"], "limit": arguments.get("limit", 50)},
        )
    if name == "get_session":
        return client.request(
            "GET",
            f"/v1/sessions/{arguments['session_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "list_behaviors":
        return client.request(
            "GET",
            "/v1/behaviors",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_behavior":
        return client.request(
            "GET",
            f"/v1/behaviors/{arguments['behavior_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "create_behavior_draft":
        return client.request(
            "POST",
            "/v1/behaviors",
            json_body={**arguments, "status": "draft"},
        )
    if name == "list_datasets":
        return client.request(
            "GET",
            "/v1/datasets",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_dataset":
        return client.request(
            "GET",
            f"/v1/datasets/{arguments['dataset_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "add_trace_to_dataset":
        return client.request(
            "POST",
            f"/v1/datasets/{arguments['dataset_id']}/examples/from-trace",
            json_body=arguments,
        )
    if name == "list_judges":
        return client.request(
            "GET",
            "/v1/judges",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_judge":
        return client.request(
            "GET",
            f"/v1/judges/{arguments['judge_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "create_judge_draft":
        return client.request("POST", "/v1/judges/drafts", json_body=arguments)
    if name == "run_judge":
        return client.request("POST", "/v1/judges/rubric/run", json_body=arguments)
    if name == "run_eval":
        return client.request("POST", "/v1/evals/run", json_body=arguments)
    if name == "compare_eval_runs":
        return client.request("POST", "/v1/evals/compare", json_body=arguments)
    if name == "search_docs":
        return client.request("POST", "/v1/docs/search", json_body=arguments)
    if name == "list_prompts":
        return client.request(
            "GET",
            "/v1/prompts",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_prompt":
        return client.request(
            "GET",
            f"/v1/prompts/{arguments['prompt_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "render_prompt":
        return client.request(
            "POST",
            f"/v1/prompts/{arguments['prompt_id']}/render",
            json_body=arguments,
        )
    if name == "commit_prompt":
        return client.request(
            "POST",
            f"/v1/prompts/{arguments['prompt_id']}/versions",
            json_body=arguments,
        )
    if name == "list_agent_configs":
        return client.request(
            "GET",
            "/v1/agent-configs",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_agent_config":
        return client.request(
            "GET",
            f"/v1/agent-configs/{arguments['agent_config_id']}",
            params={"project_id": arguments["project_id"]},
        )
    if name == "compare_agent_configs":
        return client.request(
            "POST",
            f"/v1/agent-configs/{arguments['agent_config_id']}/compare",
            json_body=arguments,
        )
    if name == "list_automations":
        return client.request(
            "GET",
            "/v1/automations",
            params={"project_id": arguments["project_id"]},
        )
    if name == "get_automation":
        return client.request(
            "GET",
            f"/v1/automations/{arguments['automation_id']}",
            params={"project_id": arguments["project_id"]},
        )
    return {
        "status": "unsupported",
        "tool": name,
        "reason": "Tool is declared but no handler is registered.",
    }


def _read_resource_payload(
    client: OpenABMApiClient,
    *,
    project_id: str,
    resource_type: str,
    resource_id: str,
) -> dict[str, Any]:
    tool_arguments = _resource_tool_arguments(project_id, resource_type, resource_id)
    if tool_arguments is not None:
        tool_name, arguments = tool_arguments
        return _call_tool_impl(tool_name, arguments, client=client)
    if resource_type == "eval-run":
        return client.request(
            "GET",
            f"/v1/evals/{resource_id}",
            params={"project_id": project_id},
        )
    raise ValueError(f"Unsupported resource type: {resource_type}")


def _resource_tool_arguments(
    project_id: str,
    resource_type: str,
    resource_id: str,
) -> tuple[str, dict[str, Any]] | None:
    tool_by_resource = {
        "trace": ("get_trace", "trace_id"),
        "span": ("get_span", "span_id"),
        "session": ("get_session", "session_id"),
        "behavior": ("get_behavior", "behavior_id"),
        "judge": ("get_judge", "judge_id"),
        "dataset": ("get_dataset", "dataset_id"),
        "prompt": ("get_prompt", "prompt_id"),
        "automation": ("get_automation", "automation_id"),
        "saved-search": ("get_saved_search", "saved_search_id"),
        "issue": ("get_issue", "issue_id"),
        "investigation-run": ("get_investigation_run", "investigation_run_id"),
        "impact-report": ("get_impact_report", "report_id"),
        "agent-context-pack": ("get_agent_context_pack", "context_pack_id"),
    }
    if resource_type not in tool_by_resource:
        return None
    tool_name, id_field = tool_by_resource[resource_type]
    return tool_name, {"project_id": project_id, id_field: resource_id}


def _parse_resource_uri(uri: str) -> dict[str, str]:
    parsed = urlparse(uri)
    resource_type = parsed.scheme
    resource_id = parsed.netloc or parsed.path.lstrip("/")
    if not resource_type or not resource_id:
        raise ValueError("Resource URI must include a scheme and resource id.")
    query = parse_qs(parsed.query)
    project_id = query.get("project_id", [os.getenv("OPENABM_PROJECT_ID", "proj_demo")])[0]
    if not project_id:
        raise ValueError("Resource URI requires project_id or OPENABM_PROJECT_ID.")
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "project_id": project_id,
    }


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _record_tool_observation(
    client: OpenABMApiClient,
    *,
    project_id: Any,
    tool_name: str,
    status: str,
    latency_ms: int,
    error_type: str | None,
    error_message: str | None,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None,
    confirmation_required: bool,
) -> None:
    if not isinstance(project_id, str) or not project_id:
        return
    try:
        client.request(
            "POST",
            "/v1/ops/mcp-tool-observations",
            json_body={
                "project_id": project_id,
                "tool_name": tool_name,
                "status": status,
                "latency_ms": latency_ms,
                "error_type_nullable": error_type,
                "error_message_nullable": error_message,
                "request": _bounded_observation_payload(request_payload),
                "response": _bounded_observation_payload(response_payload or {}),
                "citations": _extract_observation_citations(response_payload or {}),
                "confirmation_required": confirmation_required,
            },
        )
    except Exception:
        return


def _tool_requires_confirmation(tool_name: str) -> bool:
    for tool in all_tool_definitions():
        if tool["name"] == tool_name:
            return bool(tool.get("confirmation_required"))
    return False


def _strip_execution_controls(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if key != "confirmed"}


def _bounded_observation_payload(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_OBSERVATION_DEPTH:
        return {"truncated": True, "type": type(value).__name__}
    if isinstance(value, dict):
        items = list(value.items())
        bounded = {
            str(key): _bounded_observation_payload(item, depth=depth + 1)
            for key, item in items[:MAX_OBSERVATION_ITEMS]
        }
        if len(items) > MAX_OBSERVATION_ITEMS:
            bounded["_truncated_keys"] = len(items) - MAX_OBSERVATION_ITEMS
        return bounded
    if isinstance(value, list):
        bounded_items = [
            _bounded_observation_payload(item, depth=depth + 1)
            for item in value[:MAX_OBSERVATION_ITEMS]
        ]
        if len(value) > MAX_OBSERVATION_ITEMS:
            bounded_items.append({"truncated_items": len(value) - MAX_OBSERVATION_ITEMS})
        return bounded_items
    if isinstance(value, str):
        if len(value) > MAX_OBSERVATION_STRING_LENGTH:
            return value[:MAX_OBSERVATION_STRING_LENGTH] + "...[truncated]"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _extract_observation_citations(value: Any) -> list[str]:
    citations: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key.endswith("_id") and isinstance(nested, str):
                    citations.add(nested)
                elif key.endswith("_ids") and isinstance(nested, list):
                    for candidate in nested:
                        if isinstance(candidate, str):
                            citations.add(candidate)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return sorted(citations)[:MAX_OBSERVATION_ITEMS]
