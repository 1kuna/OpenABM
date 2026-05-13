from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any, Protocol

from fastapi import Header, HTTPException

from openabm_api.settings import Settings

Role = str

VIEWER_SCOPES = {
    "projects:read",
    "traces:read",
    "scores:read",
    "behaviors:read",
    "datasets:read",
    "evals:read",
    "prompts:read",
    "judges:read",
    "docs:read",
}

DEVELOPER_SCOPES = VIEWER_SCOPES | {
    "agent_configs:read",
    "agent_configs:write",
    "behaviors:write",
    "context_packs:read",
    "context_packs:write",
    "datasets:write",
    "evals:write",
    "exports:read",
    "feedback:write",
    "grounding:read",
    "grounding:write",
    "investigations:read",
    "investigations:write",
    "issues:read",
    "issues:write",
    "judges:write",
    "payloads:write",
    "prompts:write",
    "reviews:read",
    "reviews:write",
    "scores:write",
    "traces:write",
}

ADMIN_SCOPES = DEVELOPER_SCOPES | {
    "api_keys:read",
    "api_keys:write",
    "auth:read",
    "automations:read",
    "automations:write",
    "notifications:read",
    "notifications:write",
    "ops:read",
    "ops:write",
    "policies:read",
    "policies:write",
    "secrets:read",
    "secrets:write",
    "sessions:read",
    "sessions:write",
    "traces:delete",
}

OWNER_SCOPES = ADMIN_SCOPES | {
    "invites:read",
    "invites:write",
    "org_users:read",
    "org_users:write",
    "owner:write",
}

ROLE_SCOPES: dict[Role, set[str]] = {
    "viewer": VIEWER_SCOPES,
    "developer": DEVELOPER_SCOPES,
    "admin": ADMIN_SCOPES,
    "owner": OWNER_SCOPES,
}

SESSION_COOKIE_POLICY = {
    "cookie_name": "openabm_session",
    "http_only": True,
    "same_site": "lax",
    "secure_in_local_dev": False,
    "secure_in_production": True,
    "csrf": {
        "required_for_mutating_requests": True,
        "token_transport": "x-openabm-csrf-token",
    },
}


class ApiKeyStore(Protocol):
    def authenticate_api_key(self, api_key: str) -> dict[str, Any] | None: ...


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def auth_contract(
    settings: Settings,
    decision_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "active_auth_mode": settings.auth_mode,
        "supported_auth_modes": ["local", "local-open", "external-idp"],
        "local_development_auth_mode": {
            "mode": "Bearer API key",
            "env_var": "OPENABM_DEV_API_KEY",
            "local_open_mode": (
                "OPENABM_AUTH_MODE=local-open bypasses auth only for local development."
            ),
        },
        "user_signup_login_mode": {
            "status": "scaffolded",
            "decision": "passwordless_first",
            "implementation": (
                "Users, invites, memberships, and sessions are stored locally; password "
                "verification is intentionally deferred to an external IdP adapter."
            ),
        },
        "session_cookie_policy": SESSION_COOKIE_POLICY,
        "csrf_policy": SESSION_COOKIE_POLICY["csrf"],
        "password_or_passwordless_decision": "passwordless_first",
        "external_identity_provider_integration_point": {
            "status": "adapter_boundary",
            "stored_fields": ["auth_provider", "external_subject"],
            "expected_protocols": ["OIDC", "OAuth2"],
        },
        "service_accounts": {
            "status": "implemented",
            "api_key_actor_type": "service_account",
        },
        "api_key_creation_and_revocation": {
            "status": "implemented",
            "plaintext_returned_once": True,
            "storage": "sha256 hash only",
        },
        "org_project_switching": {
            "status": "implemented_reference_model",
            "switching_key": "project_id",
            "membership_scope": "project_memberships",
        },
        "invites": {
            "status": "implemented_reference_model",
            "delivery": "out_of_band",
        },
        "role_matrix": role_matrix(),
        "decision_records": decision_records or [],
    }


def role_matrix() -> dict[str, list[str]]:
    return {role: sorted(scopes) for role, scopes in ROLE_SCOPES.items()}


def require_api_key(
    settings: Settings,
    store: ApiKeyStore,
    required_scopes: Iterable[str],
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    required = [scope for scope in required_scopes if scope]
    if settings.auth_mode == "local-open":
        actor = {
            "actor_id": "local-open",
            "actor_type": "local",
            "role": "owner",
            "project_id": "proj_demo",
            "scopes": ["*"],
        }
        _require_scopes(actor, required)
        return actor

    api_key = _bearer_token(authorization)
    if api_key is None:
        raise _auth_required()

    record = store.authenticate_api_key(api_key)
    if record is None and api_key == settings.dev_api_key:
        record = {
            "api_key_id": "api_key_local_dev_fallback",
            "project_id": "proj_demo",
            "actor_id": "service_account_local_dev",
            "actor_type": "service_account",
            "role": "owner",
            "scopes": ["*"],
        }
    if record is None:
        raise _auth_required()

    actor = {
        "actor_id": record.get("actor_id") or record.get("api_key_id"),
        "actor_type": record.get("actor_type") or "service_account",
        "api_key_id": record.get("api_key_id"),
        "project_id": record.get("project_id"),
        "role": record.get("role") or "viewer",
        "scopes": record.get("scopes") or [],
    }
    _require_scopes(actor, required)
    return actor


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization.removeprefix(prefix).strip()
    return token or None


def _require_scopes(actor: dict[str, object], required_scopes: list[str]) -> None:
    if not required_scopes:
        return
    effective = _effective_scopes(
        str(actor.get("role") or "viewer"),
        [str(scope) for scope in actor.get("scopes", []) if scope],
    )
    missing = [
        scope
        for scope in required_scopes
        if scope not in effective and "*" not in effective
    ]
    if missing:
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "forbidden",
                    "message": "The authenticated actor does not have the required role or scope.",
                    "path": None,
                    "request_id": "local",
                    "retryable": False,
                    "required_scopes": missing,
                    "role": actor.get("role"),
                }
            },
        )


def _effective_scopes(role: str, granted_scopes: list[str]) -> set[str]:
    role_scopes = ROLE_SCOPES.get(role, VIEWER_SCOPES)
    if "*" in granted_scopes:
        return set(role_scopes)
    return set(granted_scopes) & role_scopes


def _auth_required() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "error": {
                "code": "auth_required",
                "message": "Missing or invalid API key.",
                "path": None,
                "request_id": "local",
                "retryable": False,
            }
        },
    )
