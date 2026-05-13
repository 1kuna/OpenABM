from __future__ import annotations

import json
import sys

from openabm_mcp.handlers import (
    call_tool,
    read_resource,
    resource_template_manifest,
    tool_manifest,
)


def main() -> None:
    if sys.stdin.isatty():
        print(json.dumps(tool_manifest(), indent=2, sort_keys=True))
        return
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        response = _handle_jsonrpc_message(message)
        print(json.dumps(response, sort_keys=True), flush=True)


def _handle_jsonrpc_message(message: dict[str, object]) -> dict[str, object]:
    method = message.get("method")
    request_id = message.get("id")
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "openabm-mcp", "version": "0.0.0"},
                "capabilities": {"tools": {}, "resources": {}},
            }
        elif method == "tools/list":
            result = {"tools": tool_manifest()["tools"]}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": resource_template_manifest()}
        elif method == "resources/read":
            params = message.get("params") or {}
            if not isinstance(params, dict) or not isinstance(params.get("uri"), str):
                raise ValueError("resources/read requires a uri")
            result = {"contents": [read_resource(params["uri"])]}
        elif method == "tools/call":
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            name = params["name"]
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("tools/call requires name and object arguments")
            structured = call_tool(name, arguments)
            result = {
                "content": [{"type": "text", "text": json.dumps(structured, sort_keys=True)}],
                "structuredContent": structured,
                "isError": structured.get("status")
                in {"failed", "unsupported", "confirmation_required"},
            }
        else:
            raise ValueError(f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }


if __name__ == "__main__":
    main()
