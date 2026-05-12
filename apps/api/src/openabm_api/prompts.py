from __future__ import annotations

import difflib
import hashlib
import json
import re
from typing import Any

SECRET_REF_PATTERN = re.compile(r"\{\{\s*secret:[^}]+\}\}")
VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def prompt_commit_id(
    *,
    template_text: str,
    variables_schema: dict[str, Any],
    parent_commit_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> str:
    payload = {
        "template_text": template_text,
        "variables_schema": variables_schema,
        "parent_commit_id": parent_commit_id,
        "metadata": metadata or {},
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"prompt_{digest[:32]}"


def render_prompt(template_text: str, variables: dict[str, Any]) -> str:
    if SECRET_REF_PATTERN.search(template_text):
        raise ValueError("Secret interpolation is disallowed in prompt templates.")

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            raise KeyError(f"Missing prompt variable: {key}")
        return str(variables[key])

    return VARIABLE_PATTERN.sub(replace, template_text)


def diff_prompt_text(old: str, new: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile="old",
            tofile="new",
            lineterm="",
        )
    )

