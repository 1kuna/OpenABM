from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[4]
SCHEMA_DIR = ROOT / "packages" / "shared-types" / "schemas"


class SchemaValidationFailure(ValueError):
    def __init__(self, code: str, message: str, path: str | None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


@cache
def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text())


@cache
def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name))


def validate_payload(name: str, payload: dict[str, Any]) -> None:
    try:
        validator(name).validate(payload)
    except ValidationError as exc:
        path = "/" + "/".join(str(part) for part in exc.absolute_path)
        if path == "/":
            path = None
        raise SchemaValidationFailure(
            code="schema_validation_failed",
            message=exc.message,
            path=path,
        ) from exc

