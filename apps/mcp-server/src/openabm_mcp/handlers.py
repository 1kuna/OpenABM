from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from openabm_mcp.tools import all_tool_definitions

UNSUPPORTED_TOOLS: dict[str, str] = {}


RESOURCE_TEMPLATES = [
    "trace://{trace_id}",
    "span://{span_id}",
    "session://{session_id}",
    "behavior://{behavior_id}",
    "judge://{judge_id}",
    "dataset://{dataset_id}",
    "prompt://{prompt_id}",
    "eval-run://{eval_run_id}",
    "automation://{automation_id}",
    "saved-search://{saved_search_id}",
    "issue://{issue_id}",
    "investigation-run://{investigation_run_id}",
    "impact-report://{report_id}",
    "agent-context-pack://{context_pack_id}",
]


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
    try:
        result = _call_tool_impl(name, arguments, client=api_client)
        if result.get("status") == "unsupported":
            status = "unsupported"
        return result
    except Exception as exc:
        status = "failed"
        error_type = type(exc).__name__
        error_message = str(exc)
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
    if name == "get_agent_context_pack":
        return client.request(
            "GET",
            f"/v1/context-packs/{arguments['context_pack_id']}",
            params={"project_id": arguments["project_id"]},
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


def _record_tool_observation(
    client: OpenABMApiClient,
    *,
    project_id: Any,
    tool_name: str,
    status: str,
    latency_ms: int,
    error_type: str | None,
    error_message: str | None,
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
            },
        )
    except Exception:
        return
