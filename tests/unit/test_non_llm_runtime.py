import asyncio
import textwrap

import pytest
from jsonschema import Draft202012Validator
from openabm_api.classification import classify_payload, redact_if_needed
from openabm_api.prompts import diff_prompt_text, prompt_commit_id, render_prompt
from openabm_mcp.handlers import call_tool, tool_manifest
from openabm_mcp.tools import REQUIRED_TOOL_NAMES, all_tool_definitions
from openabm_worker.code_sandbox import run_code_judge_dev_sandbox
from openabm_worker.conditions import evaluate_condition_group
from openabm_worker.eval_assertions import evaluate_trace_assertions
from openabm_worker.judges import run_deterministic_rule_judge, validate_judge_output
from openabm_worker.model_runtime import DisabledModelProvider, ModelCallsDisabled


def test_disabled_model_provider_fails_closed() -> None:
    provider = DisabledModelProvider()
    health = provider.health_check()
    assert health.status == "disabled"
    with pytest.raises(ModelCallsDisabled):
        asyncio.run(provider.structured_completion({}, {}, 1))


def test_condition_grammar_supports_nested_groups() -> None:
    context = {"trace": {"status": "error"}, "cost": {"total": 3.5}}
    result = evaluate_condition_group(
        {
            "combine": "all",
            "items": [
                {"field": "trace.status", "op": "eq", "value": "error"},
                {"field": "cost.total", "op": "gt", "value": 2.0},
            ],
        },
        context,
    )
    assert result["passed"] is True


def test_deterministic_rule_judge_cites_matching_spans() -> None:
    trace = {"trace_id": "trace_wrong_tool"}
    spans = [
        {
            "span_id": "span_order_lookup",
            "attributes": {"tool": {"name": "order_lookup"}},
        }
    ]
    score = run_deterministic_rule_judge(
        trace,
        spans,
        {
            "judge_id": "judge_wrong_tool",
            "rule": {
                "match_semantics": "any_match_is_pass",
                "conditions": {
                    "combine": "all",
                    "items": [
                        {"field": "attributes.tool.name", "op": "eq", "value": "order_lookup"}
                    ],
                },
            },
        },
    )
    assert score["status"] == "succeeded"
    assert score["evidence_span_ids"] == ["span_order_lookup"]


def test_judge_output_validation_rejects_missing_or_invalid_citations() -> None:
    invalid = validate_judge_output(
        {"verdict": "fail", "score": 0, "evidence_span_ids": []},
        trace_id="trace_1",
        judge_id="judge_1",
        judge_version_id="judge_version_1",
        preserved_span_ids={"span_1"},
        require_span_citations=True,
    )
    assert invalid["status"] == "invalid_output"
    assert invalid["failure_mode"] == "missing_citations"

    valid = validate_judge_output(
        {"verdict": "fail", "score": 0, "evidence_span_ids": ["span_1"]},
        trace_id="trace_1",
        judge_id="judge_1",
        judge_version_id="judge_version_1",
        preserved_span_ids={"span_1"},
        require_span_citations=True,
    )
    assert valid["status"] == "succeeded"


def test_code_judge_dev_sandbox_scrubs_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENABM_SECRET_SHOULD_NOT_LEAK", "hidden")
    code = textwrap.dedent(
        """
        import json
        import os

        output = {
            "status": "succeeded",
            "saw_secret": os.getenv("OPENABM_SECRET_SHOULD_NOT_LEAK") is not None,
        }
        with open(os.environ["OPENABM_CODE_JUDGE_OUTPUT"], "w") as handle:
            json.dump(output, handle)
        """
    )
    result = run_code_judge_dev_sandbox(code, {"trace_id": "trace_1"})
    assert result["status"] == "succeeded"
    assert result["failure_reason"] is None
    assert result["result"]["saw_secret"] is False
    assert result["isolation_level"] == "dev_only"
    assert result["sandbox_policy"]["network_disabled"] is True
    assert result["sandbox_policy"]["secrets_mounted"] is False


def test_code_judge_dev_sandbox_uses_score_failure_statuses() -> None:
    timeout = run_code_judge_dev_sandbox("while True:\n    pass\n", {}, timeout_seconds=1)
    assert timeout["status"] == "timeout"
    assert timeout["failure_reason"] == "resource_exceeded"

    invalid = run_code_judge_dev_sandbox("print('no structured result')", {})
    assert invalid["status"] == "invalid_output"
    assert invalid["failure_reason"] == "invalid_result"

    blocked_network = run_code_judge_dev_sandbox("import socket\n", {})
    assert blocked_network["status"] == "failed"
    assert blocked_network["failure_reason"] == "permission_denied"
    assert "socket" in blocked_network["stderr"]


def test_code_judge_dev_sandbox_restricts_filesystem_to_temp_bundle() -> None:
    code = textwrap.dedent(
        """
        import json
        import os

        try:
            with open("/etc/hosts") as handle:
                outside_read = handle.read(1)
        except PermissionError:
            outside_read = "blocked"

        with open(os.environ["OPENABM_CODE_JUDGE_OUTPUT"], "w") as handle:
            json.dump({"outside_read": outside_read}, handle)
        """
    )
    result = run_code_judge_dev_sandbox(code, {"trace_id": "trace_1"})
    assert result["status"] == "succeeded"
    assert result["result"]["outside_read"] == "blocked"


def test_prompt_commit_render_and_diff_are_deterministic() -> None:
    commit_a = prompt_commit_id(
        template_text="Hello {{name}}",
        variables_schema={"type": "object", "required": ["name"]},
        parent_commit_id=None,
    )
    commit_b = prompt_commit_id(
        template_text="Hello {{name}}",
        variables_schema={"type": "object", "required": ["name"]},
        parent_commit_id=None,
    )
    assert commit_a == commit_b
    assert render_prompt("Hello {{name}}", {"name": "OpenABM"}) == "Hello OpenABM"
    assert (
        render_prompt(
            "Use {{secret:api_key}} for {{name}}",
            {"name": "OpenABM"},
            secret_values={"api_key": "secret-value"},
        )
        == "Use secret-value for OpenABM"
    )
    assert "-Hello {{name}}" in diff_prompt_text("Hello {{name}}", "Hi {{name}}")
    with pytest.raises(ValueError):
        render_prompt("Use {{secret:api_key}}", {})


def test_mcp_tool_contracts_cover_required_names() -> None:
    tools = all_tool_definitions()
    by_name = {tool["name"]: tool for tool in tools}
    assert set(REQUIRED_TOOL_NAMES) == set(by_name)
    assert "start_investigation_run" in by_name
    assert "get_agent_context_pack" in by_name
    for tool in tools:
        assert tool["description"]
        assert "scaffold tool contract" not in tool["description"]
        assert "input_schema" in tool
        assert "output_schema" in tool
        assert "required_scopes" in tool
        assert tool["required_scopes"]
        assert tool["required_scopes"] != ["drafts:write"]
        assert "confirmation_required" in tool
        assert "project_id" in tool["input_schema"].get("properties", {})
        assert tool["example_request"]
        assert tool["example_response"]
        Draft202012Validator.check_schema(tool["input_schema"])
        Draft202012Validator.check_schema(tool["output_schema"])
    assert by_name["commit_prompt"]["confirmation_required"] is True
    assert by_name["run_eval"]["confirmation_required"] is True
    assert by_name["search_traces"]["side_effects"] is False
    assert by_name["create_issue"]["side_effects"] is True


def test_mcp_handlers_route_supported_tools_and_fail_closed_for_gaps() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def request(self, method, path, *, params=None, json_body=None):
            self.calls.append(
                {
                    "method": method,
                    "path": path,
                    "params": params,
                    "json_body": json_body,
                }
            )
            return {"ok": True, "path": path}

    client = FakeClient()
    result = call_tool(
        "get_trace",
        {"project_id": "proj_demo", "trace_id": "trace_1"},
        client=client,
    )
    assert result["path"] == "/v1/traces/trace_1"
    assert client.calls[0]["params"] == {"project_id": "proj_demo"}
    assert client.calls[1]["path"] == "/v1/ops/mcp-tool-observations"
    assert client.calls[1]["json_body"]["tool_name"] == "get_trace"
    assert client.calls[1]["json_body"]["status"] == "succeeded"
    assert client.calls[1]["json_body"]["request"]["trace_id"] == "trace_1"
    assert client.calls[1]["json_body"]["response"]["path"] == "/v1/traces/trace_1"
    assert client.calls[1]["json_body"]["confirmation_required"] is False

    prompt_result = call_tool("list_prompts", {"project_id": "proj_demo"}, client=client)
    assert prompt_result["path"] == "/v1/prompts"
    automation_result = call_tool("list_automations", {"project_id": "proj_demo"}, client=client)
    assert automation_result["path"] == "/v1/automations"
    judge_result = call_tool("list_judges", {"project_id": "proj_demo"}, client=client)
    assert judge_result["path"] == "/v1/judges"
    docs_result = call_tool(
        "search_docs",
        {"project_id": "proj_demo", "query": "judge registry"},
        client=client,
    )
    assert docs_result["path"] == "/v1/docs/search"
    assert "trace://{trace_id}" in tool_manifest()["resource_templates"]


def test_trajectory_assertions_cite_failing_tool_spans() -> None:
    spans = [
        {
            "span_id": "span_order_lookup",
            "span_type": "tool",
            "duration_ms": 800,
            "attributes": {
                "tool.name": "order_lookup",
                "cost.estimated_usd": 0.2,
                "retry.count": 2,
                "retrieval.source_ids": ["orders_index"],
            },
        }
    ]
    result = evaluate_trace_assertions(
        spans,
        {
            "required_tools": ["refund_policy_lookup"],
            "forbidden_tools": ["order_lookup"],
            "forbidden_retrieval_sources": ["orders_index"],
            "max_cost": 0.1,
            "max_total_duration_ms": 500,
            "max_retries": 1,
            "min_grounding_evidence_span_count": 1,
        },
    )
    assert result["status"] == "failed"
    assert {
        "type": "forbidden_tool_used",
        "tool": "order_lookup",
        "span_ids": ["span_order_lookup"],
    } in result["failures"]
    assert result["observed"]["retrieval_sources"] == ["orders_index"]


def test_data_classification_rules_redact_above_access_level() -> None:
    result = classify_payload(
        {"customer": {"email": "zach@example.com"}, "note": "internal workflow"},
        {
            "default_classification": "internal",
            "rules": [
                {
                    "rule_id": "email",
                    "path": "customer.email",
                    "classification": "confidential",
                    "contains": "@",
                }
            ],
        },
    )
    assert result["classification"] == "confidential"
    assert redact_if_needed(
        {"customer": {"email": "zach@example.com"}},
        result["classification"],
        "internal",
    )["redacted"] is True
