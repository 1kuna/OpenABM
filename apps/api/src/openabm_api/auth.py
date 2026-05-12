from __future__ import annotations

import hashlib
from collections.abc import Iterable

from fastapi import Header, HTTPException

from openabm_api.settings import Settings


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def require_api_key(
    settings: Settings,
    required_scopes: Iterable[str],
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    if settings.auth_mode == "local-open":
        return {"actor_id": "local-open", "scopes": ["*"]}

    expected = f"Bearer {settings.dev_api_key}"
    if authorization != expected:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "auth_required",
                    "message": "Missing or invalid local development API key.",
                    "path": None,
                    "request_id": "local",
                    "retryable": False,
                }
            },
        )
    return {"actor_id": "local-dev", "scopes": list(required_scopes)}

