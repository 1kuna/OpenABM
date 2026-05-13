from __future__ import annotations

import difflib
import hashlib
import json
import re
from typing import Any

SECRET_REF_PATTERN = re.compile(r"\{\{\s*secret:([^}\s]+)\s*\}\}")
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


def secret_refs_in_prompt(template_text: str) -> list[str]:
    return sorted({match.group(1).strip() for match in SECRET_REF_PATTERN.finditer(template_text)})


def render_prompt(
    template_text: str,
    variables: dict[str, Any],
    *,
    secret_values: dict[str, str] | None = None,
) -> str:
    secret_refs = secret_refs_in_prompt(template_text)
    if secret_refs and secret_values is None:
        raise ValueError("Secret interpolation requires explicit secret refs.")

    def replace_secret(match: re.Match[str]) -> str:
        secret_ref = match.group(1).strip()
        values = secret_values or {}
        if secret_ref not in values:
            raise KeyError(f"Missing prompt secret ref: {secret_ref}")
        return values[secret_ref]

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            raise KeyError(f"Missing prompt variable: {key}")
        return str(variables[key])

    rendered = SECRET_REF_PATTERN.sub(replace_secret, template_text)
    return VARIABLE_PATTERN.sub(replace, rendered)


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
