from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

AGENT_FLOW_SMOKE_TOOL_NAME = "record_agent_flow_plan"
OPENABM_AGENT_FLOW_TOOL_NAMES = [
    "search_traces",
    "search_spans",
    "get_trace",
    "start_investigation_run",
    "create_agent_context_pack",
    "run_judge",
    "search_docs",
]

DEFAULT_AGENT_FLOW_INCIDENT = (
    "A refund-support agent used order_lookup instead of refund_policy_lookup, "
    "then produced an unsupported refund denial. Plan the first OpenABM "
    "investigation search steps and cite which OpenABM tools should be used."
)

AGENT_FLOW_SMOKE_TOOL = {
    "type": "function",
    "function": {
        "name": AGENT_FLOW_SMOKE_TOOL_NAME,
        "description": (
            "Record a first-pass OpenABM investigation plan for an agent behavior incident."
        ),
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["queries", "expected_tools", "risk_notes", "confidence"],
            "properties": {
                "queries": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "expected_tools": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"enum": OPENABM_AGENT_FLOW_TOOL_NAMES},
                },
                "risk_notes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "confidence": {"enum": ["low", "medium", "high"]},
            },
        },
    },
}


async def run_agent_flow_tool_smoke(
    provider: Any,
    *,
    incident: str = DEFAULT_AGENT_FLOW_INCIDENT,
) -> dict[str, Any]:
    health = provider.health_check()
    request = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are testing OpenABM's local agentic tool-calling lane. "
                    "Use the provided tool exactly once. Do not answer in prose. "
                    "Choose expected_tools only from these OpenABM MCP tools: "
                    f"{', '.join(OPENABM_AGENT_FLOW_TOOL_NAMES)}."
                ),
            },
            {
                "role": "user",
                "content": incident,
            },
        ],
        "temperature": 0.1,
        "tool_choice": {"type": "function", "function": {"name": AGENT_FLOW_SMOKE_TOOL_NAME}},
    }
    completion = await provider.tool_completion(request, [AGENT_FLOW_SMOKE_TOOL])
    tool_calls = completion.get("tool_calls") or []
    matching_calls = [
        call for call in tool_calls if call.get("name") == AGENT_FLOW_SMOKE_TOOL_NAME
    ]
    validation_errors = _validate_tool_calls(matching_calls)
    status = (
        "succeeded"
        if completion.get("status") == "succeeded"
        and len(matching_calls) == 1
        and not validation_errors
        else "invalid_output"
    )
    return {
        "status": status,
        "raw_status": completion.get("status"),
        "requested_tool": AGENT_FLOW_SMOKE_TOOL_NAME,
        "tool_call_count": len(tool_calls),
        "matching_tool_call_count": len(matching_calls),
        "tool_calls": matching_calls,
        "parse_errors": completion.get("parse_errors") or [],
        "validation_errors": validation_errors,
        "usage": completion.get("usage"),
        "provider": completion.get("provider") or health.adapter_name,
        "model": completion.get("model") or _health_detail(health, "chat_model"),
        "provider_health": {
            "adapter_name": health.adapter_name,
            "status": health.status,
            "supported_capabilities": health.supported_capabilities,
            "context_length": _health_detail(health, "context_length"),
            "memory_guard_status": _health_detail(health, "memory_guard_status"),
            "available_memory_mb": _health_detail(health, "available_memory_mb"),
            "min_available_memory_mb": _health_detail(health, "min_available_memory_mb"),
            "timeout_behavior": _health_detail(health, "timeout_behavior"),
        },
    }


def _validate_tool_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    if len(tool_calls) != 1:
        return [f"expected exactly one {AGENT_FLOW_SMOKE_TOOL_NAME} tool call"]
    schema = AGENT_FLOW_SMOKE_TOOL["function"]["parameters"]
    validator = Draft202012Validator(schema)
    return [
        error.message
        for error in validator.iter_errors(tool_calls[0].get("arguments") or {})
    ]


def _health_detail(health: Any, key: str) -> Any:
    details = getattr(health, "details", {}) or {}
    return details.get(key)
