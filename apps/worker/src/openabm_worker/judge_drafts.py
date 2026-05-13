from __future__ import annotations

import json
from typing import Any

JUDGE_DRAFT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "judge_type", "definition", "uncertainty"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "judge_type": {
            "enum": ["rubric_judge", "code_judge", "deterministic_rule", "human_review_label"]
        },
        "definition": {"type": "object"},
        "uncertainty": {"type": "string"},
    },
}


async def draft_judge_from_request(
    provider: Any,
    *,
    request: dict[str, Any],
    trace: dict[str, Any] | None = None,
    spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    completion = await provider.structured_completion(
        {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Draft an OpenABM judge definition from the user's request. "
                        "Prefer rubric_judge unless the user explicitly asks for a deterministic "
                        "rule or code judge. Do not invent evidence IDs. Drafts are inactive and "
                        "require human review before activation. The definition must include all "
                        "fields needed to run the judge, such as rubric criteria for rubric_judge "
                        "or a rule object with match_semantics, conditions, and failure_mode for "
                        "deterministic_rule. Keep the final JSON concise."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"request": request, "trace": trace, "spans": spans or []},
                        sort_keys=True,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
        },
        JUDGE_DRAFT_SCHEMA,
    )
    if completion.get("status") != "succeeded":
        return {
            "status": "invalid_model_output",
            "model_metadata": _metadata(completion),
        }
    value = completion["value"]
    return {
        "status": "succeeded",
        **value,
        "model_metadata": _metadata(completion),
    }


def _metadata(completion: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": completion.get("provider"),
        "model": completion.get("model"),
        "usage": completion.get("usage"),
        "repaired": completion.get("repaired", False),
    }
