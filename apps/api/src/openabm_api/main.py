from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute
from openabm_worker.automations import (
    evaluate_automation_conditions,
    evaluate_automation_cooldown,
    plan_automation_cooldown,
    planned_automation_actions,
)
from openabm_worker.behaviors import backtest_behavior
from openabm_worker.context_packs import build_agent_context_pack_content
from openabm_worker.eval_assertions import evaluate_trace_assertions
from openabm_worker.grounding import (
    claims_from_text,
    evaluate_grounding_claims,
    extract_grounding_claims_with_model,
)
from openabm_worker.investigation import assist_investigation
from openabm_worker.investigation_workflow import run_investigation_workflow
from openabm_worker.judge_drafts import draft_judge_from_request
from openabm_worker.judges import run_rubric_judge
from openabm_worker.model_runtime import (
    ModelCallsDisabled,
    ModelConfigurationError,
    model_provider_from_settings,
)
from openabm_worker.novelty import (
    detect_novel_behavior_candidates,
    group_novel_behavior_candidates_with_model,
)
from openabm_worker.offline_eval import run_eval
from openabm_worker.similarity import rank_similar_traces

from openabm_api.auth import SESSION_COOKIE_POLICY, auth_contract, require_api_key, role_matrix
from openabm_api.classification import classify_payload, normalize_classification, redact_if_needed
from openabm_api.docs_search import search_public_docs
from openabm_api.ids import new_id
from openabm_api.ingest_policy import (
    IngestPolicyReport,
    apply_ingest_batch_policy,
    apply_ingest_span_policy,
)
from openabm_api.metrics import Metrics
from openabm_api.prompts import render_prompt
from openabm_api.reconstruction import reconstruct_trace
from openabm_api.schemas import SchemaValidationFailure, validate_payload
from openabm_api.secret_management import (
    LocalSecretCipher,
    SecretDecryptionError,
    secret_backend_status,
)
from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore
from openabm_api.time import utc_now

ISSUE_LINK_TARGET_TYPES = {
    "trace",
    "span",
    "investigation_run",
    "impact_report",
    "affected_entity",
    "behavior",
    "judge",
    "dataset",
    "dataset_example",
    "eval_run",
    "review_task",
    "context_pack",
    "grounding_check",
    "novelty_run",
    "automation",
    "payload_object",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    store.ensure_auth_bootstrap(settings.dev_api_key)
    metrics = Metrics()
    secret_cipher = LocalSecretCipher(settings)

    app = FastAPI(title="OpenABM API", version="0.0.0")
    app.state.settings = settings
    app.state.store = store
    app.state.metrics = metrics

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def collect_api_metrics(request: Request, call_next: Callable[[Request], Any]) -> Any:
        started = time.perf_counter()
        status_code = 500
        errored = False
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            errored = True
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            route = getattr(request.scope.get("route"), "path", request.url.path)
            route_metric = f"api.route.{request.method.lower()}.{route}.requests"
            metrics.increment("api.requests")
            metrics.increment(route_metric)
            metrics.increment(f"api.status.{status_code}")
            metrics.observe("api.request_latency_ms", elapsed_ms)
            metrics.observe(f"api.route.{request.method.lower()}.{route}.latency_ms", elapsed_ms)
            if errored or status_code >= 500:
                metrics.increment("api.errors")

    def auth_dependency(scopes: list[str]) -> Callable[[str | None], dict[str, object]]:
        def dependency(authorization: str | None = Header(default=None)) -> dict[str, object]:
            return require_api_key(settings, store, scopes, authorization)

        return dependency

    @app.exception_handler(SchemaValidationFailure)
    async def schema_error_handler(
        request: Request, exc: SchemaValidationFailure
    ) -> JSONResponse:
        del request
        metrics.increment("api.schema_invalid")
        return JSONResponse(
            status_code=400,
            content=_error(exc.code, exc.message, path=exc.path, retryable=False),
        )

    def link_issue_artifact_or_404(**kwargs: Any) -> dict[str, Any] | None:
        try:
            return store.link_issue_artifact(**kwargs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "service": "openabm-api", "details": {"env": settings.environment}}

    @app.get("/ready")
    def ready() -> dict[str, object]:
        try:
            store.list_projects()
        except Exception as exc:  # pragma: no cover - defensive readiness surface
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ready", "service": "openabm-api", "details": {"store": "sqlite"}}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics_endpoint() -> str:
        _refresh_observability_gauges(metrics, store, "proj_demo")
        return metrics.render_text()

    @app.get("/api/auth/contract")
    def get_auth_contract() -> dict[str, object]:
        return auth_contract(settings, store.list_auth_decision_records())

    @app.get("/api/auth/me")
    def get_auth_actor(
        actor: dict[str, object] = Depends(auth_dependency(["projects:read"])),
    ) -> dict[str, object]:
        return {
            "actor": actor,
            "role_scopes": role_matrix().get(str(actor.get("role") or "viewer"), []),
        }

    @app.get("/api/auth/api-keys")
    def list_api_keys(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["api_keys:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_api_keys(project_id)}

    @app.post("/api/auth/api-keys", status_code=201)
    def create_api_key(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["api_keys:write"])),
    ) -> dict[str, object]:
        for key in ["project_id", "name", "role"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            return store.create_api_key(request, actor_id=str(actor.get("actor_id") or "unknown"))
        except ValueError as exc:
            raise SchemaValidationFailure("schema_validation_failed", str(exc), "/role") from exc

    @app.post("/api/auth/api-keys/{api_key_id}/revoke")
    def revoke_api_key(
        api_key_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["api_keys:write"])),
    ) -> dict[str, object]:
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        try:
            return store.revoke_api_key(
                project_id,
                api_key_id,
                actor_id=str(actor.get("actor_id") or "unknown"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc

    @app.get("/api/auth/users")
    def list_auth_users(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["org_users:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_auth_users(project_id)}

    @app.post("/api/auth/users", status_code=201)
    def create_auth_user(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["org_users:write"])),
    ) -> dict[str, object]:
        for key in ["project_id", "email"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        user = store.create_auth_user(request)
        if request.get("role"):
            try:
                membership = store.upsert_project_membership(
                    {
                        "project_id": request["project_id"],
                        "user_id": user["user_id"],
                        "role": request["role"],
                    }
                )
                user = {**user, "membership": membership}
            except (KeyError, ValueError) as exc:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    str(exc),
                    "/role",
                ) from exc
        store.append_audit(
            "create_auth_user",
            "auth_user",
            request["project_id"],
            user["user_id"],
            {"email": user["email"]},
            actor_id=str(actor.get("actor_id") or "unknown"),
        )
        return user

    @app.get("/api/auth/project-memberships")
    def list_project_memberships(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["org_users:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_project_memberships(project_id)}

    @app.post("/api/auth/project-memberships", status_code=201)
    def upsert_project_membership(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["org_users:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "user_id", "role"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            return store.upsert_project_membership(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        except ValueError as exc:
            raise SchemaValidationFailure("schema_validation_failed", str(exc), "/role") from exc

    @app.get("/api/auth/invites")
    def list_auth_invites(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["invites:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_auth_invites(project_id)}

    @app.post("/api/auth/invites", status_code=201)
    def create_auth_invite(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["invites:write"])),
    ) -> dict[str, object]:
        for key in ["project_id", "email", "role"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            return store.create_auth_invite(
                request,
                actor_id=str(actor.get("actor_id") or "unknown"),
            )
        except ValueError as exc:
            raise SchemaValidationFailure("schema_validation_failed", str(exc), "/role") from exc

    @app.get("/api/auth/sessions")
    def list_auth_sessions(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["sessions:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_auth_sessions(project_id)}

    @app.post("/api/auth/sessions", status_code=201)
    def create_auth_session(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["sessions:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "user_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            return store.create_auth_session(request, cookie_policy=SESSION_COOKIE_POLICY)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc

    @app.post("/api/auth/sessions/{auth_session_id}/revoke")
    def revoke_auth_session(
        auth_session_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["sessions:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        try:
            return store.revoke_auth_session(project_id, auth_session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc

    @app.get("/api/auth/decision-records")
    def list_auth_decision_records(
        actor: dict[str, object] = Depends(auth_dependency(["auth:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_auth_decision_records()}

    @app.get("/api/secrets/backend")
    def get_secret_backend(
        actor: dict[str, object] = Depends(auth_dependency(["secrets:read"])),
    ) -> dict[str, object]:
        del actor
        return secret_backend_status(settings)

    @app.get("/api/secrets")
    def list_secret_refs(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["secrets:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_secret_refs(project_id)}

    @app.post("/api/secrets", status_code=201)
    def create_secret_ref(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["secrets:write"])),
    ) -> dict[str, object]:
        for key in ["project_id", "purpose", "value"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        if not isinstance(request["value"], str) or not request["value"]:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "value must be a non-empty string",
                "/value",
            )
        encrypted = secret_cipher.encrypt(request["value"])
        try:
            return store.create_secret_ref(
                request,
                ciphertext=encrypted.ciphertext,
                ciphertext_sha256=encrypted.ciphertext_sha256,
                encryption_mode=encrypted.encryption_mode,
                actor_id=str(actor.get("actor_id") or "unknown"),
            )
        except sqlite3.IntegrityError as exc:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "secret_ref already exists",
                "/secret_ref",
            ) from exc

    @app.post("/api/secrets/{secret_ref}/resolve")
    def resolve_secret_ref(
        secret_ref: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["secrets:read"])),
    ) -> dict[str, object]:
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        secret = store.get_secret_ref(project_id, secret_ref, include_ciphertext=True)
        if secret is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Secret not found."))
        try:
            plaintext = secret_cipher.decrypt(str(secret["ciphertext"]))
        except SecretDecryptionError as exc:
            raise HTTPException(
                status_code=500,
                detail=_error("secret_decryption_failed", str(exc)),
            ) from exc
        access_id = store.append_secret_access(
            project_id,
            secret_ref,
            action="resolve",
            purpose=request.get("purpose") or secret.get("purpose"),
            actor_id=str(actor.get("actor_id") or "unknown"),
        )
        return {
            "secret_ref": secret_ref,
            "project_id": project_id,
            "value": plaintext,
            "access_audit_id": access_id,
        }

    @app.post("/api/secrets/{secret_ref}/rotate")
    def rotate_secret_ref(
        secret_ref: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["secrets:write"])),
    ) -> dict[str, object]:
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        value = request.get("value")
        if not isinstance(value, str) or not value:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "value must be a non-empty string",
                "/value",
            )
        encrypted = secret_cipher.encrypt(value)
        try:
            return store.rotate_secret_ref(
                project_id,
                secret_ref,
                ciphertext=encrypted.ciphertext,
                ciphertext_sha256=encrypted.ciphertext_sha256,
                encryption_mode=encrypted.encryption_mode,
                rotation_due_at=request.get("rotation_due_at"),
                actor_id=str(actor.get("actor_id") or "unknown"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc

    @app.get("/api/secrets/{secret_ref}/access-log")
    def list_secret_access_log(
        secret_ref: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["secrets:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_secret_access_log(project_id, secret_ref)}

    @app.get("/api/ops/status")
    def get_ops_status(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["ops:read"])),
    ) -> dict[str, object]:
        del actor
        _refresh_observability_gauges(metrics, store, project_id)
        status = store.ops_status(project_id)
        status["metrics"] = metrics.snapshot()
        return status

    @app.post("/api/ops/worker-heartbeats", status_code=201)
    def record_worker_heartbeat(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["ops:write"])),
    ) -> dict[str, object]:
        if "project_id" not in request:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        heartbeat = store.record_worker_heartbeat(request)
        store.append_audit(
            "record_worker_heartbeat",
            "worker_heartbeat",
            request["project_id"],
            heartbeat["worker_id"],
            {
                "worker_type": heartbeat["worker_type"],
                "status": heartbeat["status"],
                "queue_depth": heartbeat["queue_depth"],
            },
            actor_id=str(actor.get("actor_id") or "unknown"),
        )
        return heartbeat

    @app.get("/api/ops/mcp-tool-observations")
    def list_mcp_tool_observations(
        project_id: str,
        limit: int = 50,
        actor: dict[str, object] = Depends(auth_dependency(["ops:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_mcp_tool_observations(project_id, limit=limit)}

    @app.post("/api/ops/mcp-tool-observations", status_code=201)
    def record_mcp_tool_observation(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["ops:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "tool_name", "status", "latency_ms"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        observation = store.record_mcp_tool_observation(request)
        metrics.increment("mcp.tool.calls")
        metrics.increment(f"mcp.tool.{observation['tool_name']}.calls")
        metrics.observe("mcp.tool.latency_ms", observation["latency_ms"])
        metrics.observe(
            f"mcp.tool.{observation['tool_name']}.latency_ms",
            observation["latency_ms"],
        )
        if observation["status"] == "failed":
            metrics.increment("mcp.tool.errors")
            metrics.increment(f"mcp.tool.{observation['tool_name']}.errors")
        return observation

    @app.get("/api/ops/dead-letter")
    def list_dead_letters(
        project_id: str,
        limit: int = 25,
        actor: dict[str, object] = Depends(auth_dependency(["ops:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_dead_letter_runs(project_id, limit=limit)}

    @app.post("/api/ingest/traces", status_code=202)
    def ingest_trace(
        trace: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:write"])),
    ) -> dict[str, str | None]:
        del actor
        validate_payload("trace-envelope.schema.json", trace)
        trace_id = store.upsert_trace(trace)
        metrics.increment("ingest.traces")
        store.append_audit("ingest_trace", "trace", trace["project_id"], trace_id)
        return {"status": "accepted", "server_id": trace_id}

    @app.post("/api/ingest/spans", status_code=202)
    def ingest_span(
        span: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        actor: dict[str, object] = Depends(auth_dependency(["traces:write"])),
    ) -> dict[str, str | None]:
        del actor
        span, policy_report = apply_ingest_span_policy(
            span,
            inline_payload_max_bytes=settings.ingest_inline_payload_max_bytes,
            max_events_per_span=settings.ingest_max_events_per_span,
            stream_event_sample_rate=settings.ingest_stream_event_sample_rate,
        )
        _record_ingest_policy_metrics(metrics, policy_report)
        validate_payload("span-envelope.schema.json", span)
        span_id = store.upsert_span(span, idempotency_key=idempotency_key)
        metrics.increment("ingest.spans")
        store.append_audit("ingest_span", "span", span["project_id"], span_id)
        return {"status": "accepted", "server_id": span_id}

    @app.post("/api/ingest/events", status_code=202)
    def ingest_event(
        payload: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:write"])),
    ) -> dict[str, str | None]:
        del actor
        event = payload.get("event")
        if not isinstance(event, dict):
            raise SchemaValidationFailure("schema_validation_failed", "event is required", "/event")
        validate_payload("trace-event.schema.json", event)
        span_id = store.append_event(
            payload["project_id"],
            payload["trace_id"],
            payload["span_id"],
            event,
        )
        metrics.increment("ingest.events")
        return {"status": "accepted", "server_id": span_id}

    @app.post("/api/ingest/feedback", status_code=202)
    def ingest_feedback(
        feedback: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["feedback:write"])),
    ) -> dict[str, str | None]:
        del actor
        required = ["project_id", "trace_id", "feedback_type"]
        for key in required:
            if key not in feedback:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        audit_id = store.append_audit(
            "ingest_feedback",
            "trace",
            feedback["project_id"],
            feedback["trace_id"],
            {"feedback": feedback},
        )
        metrics.increment("ingest.feedback")
        return {"status": "accepted", "server_id": audit_id}

    @app.post("/api/ingest/payloads", status_code=202)
    def ingest_payload(
        payload: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["payloads:write"])),
    ) -> dict[str, str | None]:
        del actor
        payload_metadata = payload.get("payload", payload)
        if not isinstance(payload_metadata, dict):
            raise SchemaValidationFailure(
                "schema_validation_failed", "payload metadata is required", "/payload"
            )
        validate_payload("payload-object.schema.json", payload_metadata)
        payload_id = store.put_payload(payload_metadata)
        metrics.increment("ingest.payloads")
        return {"status": "accepted", "server_id": payload_id}

    @app.post("/api/ingest/batch", status_code=207)
    def ingest_batch(
        batch: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:write"])),
    ) -> dict[str, object]:
        del actor
        batch, policy_report = apply_ingest_batch_policy(
            batch,
            max_batch_items=settings.ingest_max_batch_items,
            retryable_batch_items=settings.ingest_retryable_backpressure_items,
            inline_payload_max_bytes=settings.ingest_inline_payload_max_bytes,
            max_events_per_span=settings.ingest_max_events_per_span,
            stream_event_sample_rate=settings.ingest_stream_event_sample_rate,
        )
        _record_ingest_policy_metrics(metrics, policy_report)
        if policy_report.backpressure_retry:
            metrics.increment("ingest.backpressure.retryable_rejections")
            raise HTTPException(
                status_code=429,
                detail=_error(
                    "ingest_backpressure",
                    (
                        "Batch exceeds the retryable backpressure item limit and does "
                        "not contain an always-keep trace."
                    ),
                    retryable=True,
                ),
                headers={"Retry-After": str(policy_report.retry_after_seconds)},
            )
        items: list[dict[str, Any]] = []
        accepted = 0
        rejected = 0

        def accept(client_item_id: str, server_id: str | None) -> None:
            nonlocal accepted
            accepted += 1
            items.append(
                {"client_item_id": client_item_id, "status": "accepted", "server_id": server_id}
            )

        def reject(client_item_id: str, exc: Exception) -> None:
            nonlocal rejected
            rejected += 1
            if isinstance(exc, SchemaValidationFailure):
                error = {"code": exc.code, "path": exc.path, "message": exc.message}
            else:
                error = {"code": "ingest_failed", "path": None, "message": str(exc)}
            items.append(
                {"client_item_id": client_item_id, "status": "rejected", "error": error}
            )

        for index, trace in enumerate(batch.get("traces", [])):
            client_id = trace.get("trace_id", f"trace_{index}")
            try:
                validate_payload("trace-envelope.schema.json", trace)
                accept(client_id, store.upsert_trace(trace))
            except Exception as exc:  # noqa: BLE001 - partial-success contract
                reject(client_id, exc)

        for index, span in enumerate(batch.get("spans", [])):
            client_id = span.get("span_id", f"span_{index}")
            try:
                validate_payload("span-envelope.schema.json", span)
                accept(client_id, store.upsert_span(span))
            except Exception as exc:  # noqa: BLE001 - partial-success contract
                reject(client_id, exc)

        for index, event_payload in enumerate(batch.get("events", [])):
            client_id = event_payload.get("client_item_id", f"event_{index}")
            try:
                event = event_payload.get("event")
                if not isinstance(event, dict):
                    raise SchemaValidationFailure(
                        "schema_validation_failed",
                        "event is required",
                        "/event",
                    )
                validate_payload("trace-event.schema.json", event)
                accept(
                    client_id,
                    store.append_event(
                        event_payload["project_id"],
                        event_payload["trace_id"],
                        event_payload["span_id"],
                        event,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - partial-success contract
                reject(client_id, exc)

        for index, feedback in enumerate(batch.get("feedback", [])):
            client_id = feedback.get("client_item_id", f"feedback_{index}")
            try:
                for key in ["project_id", "trace_id", "feedback_type"]:
                    if key not in feedback:
                        raise SchemaValidationFailure(
                            "schema_validation_failed",
                            f"{key} is required",
                            f"/{key}",
                        )
                accept(
                    client_id,
                    store.append_audit(
                        "ingest_feedback",
                        "trace",
                        feedback["project_id"],
                        feedback["trace_id"],
                        {"feedback": feedback},
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - partial-success contract
                reject(client_id, exc)

        for index, payload in enumerate(batch.get("payloads", [])):
            payload_metadata = payload.get("payload", payload)
            client_id = payload_metadata.get("payload_id", f"payload_{index}")
            try:
                if not isinstance(payload_metadata, dict):
                    raise SchemaValidationFailure(
                        "schema_validation_failed",
                        "payload metadata is required",
                        "/payload",
                    )
                validate_payload("payload-object.schema.json", payload_metadata)
                accept(client_id, store.put_payload(payload_metadata))
            except Exception as exc:  # noqa: BLE001 - partial-success contract
                reject(client_id, exc)

        status = "success" if rejected == 0 else "partial_success" if accepted else "failed"
        metrics.increment("ingest.batch")
        response: dict[str, object] = {
            "status": status,
            "accepted": accepted,
            "rejected": rejected,
            "items": items,
        }
        if policy_report.changed:
            response["backpressure"] = policy_report.to_dict()
        return response

    @app.get("/api/projects")
    def list_projects(
        actor: dict[str, object] = Depends(auth_dependency(["projects:read"])),
        limit: int = 50,
    ) -> dict[str, object]:
        del actor
        data = store.list_projects()[:limit]
        return {"data": data, "page": {"limit": limit, "next_cursor": None, "has_more": False}}

    @app.get("/api/traces")
    def list_traces(
        project_id: str,
        environment: str | None = None,
        status: str | None = None,
        limit: int = 50,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        filters = {
            key: value
            for key, value in {"environment": environment, "status": status}.items()
            if value
        }
        data = store.search_traces(project_id, filters=filters, limit=limit)
        return {"data": data, "page": {"limit": limit, "next_cursor": None, "has_more": False}}

    @app.get("/api/traces/{trace_id}")
    def get_trace(
        trace_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        trace = store.get_trace(project_id, trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Trace not found."))
        spans = store.list_spans(project_id, trace_id)
        return {
            "trace": trace,
            "spans": spans,
            "reconstruction": reconstruct_trace(
                trace, spans, settings.incomplete_threshold_seconds
            ),
        }

    @app.delete("/api/traces/{trace_id}")
    def delete_trace(
        trace_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:delete"])),
    ) -> dict[str, object]:
        del actor
        try:
            result = store.tombstone_trace(project_id, trace_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Trace not found."),
            ) from exc
        store.append_audit(
            "tombstone_trace",
            "trace",
            project_id,
            trace_id,
            {"effects": result["effects"]},
        )
        return result

    @app.get("/api/traces/{trace_id}/spans")
    def list_trace_spans(
        trace_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_spans(project_id, trace_id)}

    @app.get("/api/spans/{span_id}")
    def get_span(
        span_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        span = store.get_span(project_id, span_id)
        if span is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Span not found."))
        return span

    @app.get("/api/sessions")
    def list_sessions(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
        limit: int = 50,
    ) -> dict[str, object]:
        del actor
        traces = store.search_traces(project_id, limit=limit)
        sessions: dict[str, dict[str, object]] = {}
        for trace in traces:
            session_id = trace.get("session_id")
            if not session_id:
                continue
            session = sessions.setdefault(
                str(session_id), {"session_id": session_id, "trace_count": 0, "trace_ids": []}
            )
            session["trace_count"] = int(session["trace_count"]) + 1
            session["trace_ids"].append(trace["trace_id"])
        return {
            "data": list(sessions.values()),
            "page": {"limit": limit, "next_cursor": None, "has_more": False},
        }

    @app.get("/api/sessions/{session_id}")
    def get_session(
        session_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
        limit: int = 100,
    ) -> dict[str, object]:
        del actor
        traces = store.search_traces(project_id, filters={"session_id": session_id}, limit=limit)
        if not traces:
            raise HTTPException(status_code=404, detail=_error("not_found", "Session not found."))
        return {
            "session_id": session_id,
            "trace_count": len(traces),
            "trace_ids": [trace["trace_id"] for trace in traces],
            "traces": traces,
        }

    @app.post("/api/search/traces")
    def search_traces(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        project_id = request["project_id"]
        limit = int(request.get("limit", 50))
        data = store.search_traces(
            project_id,
            filters=request.get("filters") or {},
            full_text_query=request.get("full_text_query"),
            limit=limit,
        )
        return {
            "data": data,
            "applied_filters": request.get("filters") or {},
            "page": {"limit": limit, "next_cursor": None, "has_more": False},
        }

    @app.post("/api/search/spans")
    def search_spans(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        project_id = request["project_id"]
        traces = store.search_traces(
            project_id,
            filters=request.get("filters") or {},
            full_text_query=request.get("full_text_query"),
            limit=int(request.get("limit", 50)),
        )
        spans = []
        for trace in traces:
            spans.extend(store.list_spans(project_id, trace["trace_id"]))
        return {
            "data": spans[: int(request.get("limit", 50))],
            "page": {
                "limit": int(request.get("limit", 50)),
                "next_cursor": None,
                "has_more": False,
            },
        }

    @app.post("/api/search/similar")
    async def search_similar(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        project_id = request["project_id"]
        source_id = request["source_id"]
        source_type = request.get("source_type", "trace")
        limit = int(request.get("limit", 20))
        if source_type != "trace":
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "Only trace similarity is currently supported.",
                "/source_type",
            )
        source_trace = store.get_trace(project_id, source_id)
        if source_trace is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Trace not found."))
        try:
            provider = _observed_model_provider(settings, metrics)
        except ModelConfigurationError as exc:
            return {
                "data": [],
                "disabled": True,
                "reason": str(exc),
                "representation_version": None,
                "request": request,
                "page": {"limit": limit, "next_cursor": None, "has_more": False},
            }
        candidates = [
            trace
            for trace in store.search_traces(
                project_id,
                filters=request.get("filters") or {},
                limit=50,
            )
            if trace["trace_id"] != source_id
        ]
        candidate_spans = {
            trace["trace_id"]: store.list_spans(project_id, trace["trace_id"])
            for trace in candidates
        }
        try:
            result = await rank_similar_traces(
                provider,
                source_trace=source_trace,
                source_spans=store.list_spans(project_id, source_id),
                candidates=candidates,
                candidate_spans=candidate_spans,
                limit=limit,
            )
        except ModelCallsDisabled as exc:
            return {
                "data": [],
                "disabled": True,
                "reason": str(exc),
                "representation_version": None,
                "request": request,
                "page": {"limit": limit, "next_cursor": None, "has_more": False},
            }
        return {
            "data": result["matches"],
            "disabled": False,
            "reason": result.get("uncertainty"),
            "representation_version": "model_semantic_similarity_v1",
            "model_metadata": result["model_metadata"],
            "request": request,
            "page": {"limit": limit, "next_cursor": None, "has_more": False},
        }

    @app.get("/api/scores")
    def list_scores(
        project_id: str,
        trace_id: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["scores:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_scores(project_id, trace_id=trace_id)}

    @app.get("/api/judges")
    def list_judges(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["judges:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_judges(project_id)}

    @app.get("/api/judges/{judge_id}")
    def get_judge(
        judge_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["judges:read"])),
    ) -> dict[str, object]:
        del actor
        judge = store.get_judge(project_id, judge_id)
        if judge is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Judge not found."))
        return judge

    @app.get("/api/judges/{judge_id}/calibration-report")
    def get_judge_calibration_report(
        judge_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["judges:read"])),
    ) -> dict[str, object]:
        del actor
        try:
            return store.build_judge_calibration_report(project_id, judge_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc

    @app.post("/api/judges/{judge_id}/promote")
    def promote_judge(
        judge_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["judges:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        try:
            result = store.promote_judge(
                project_id,
                judge_id,
                policy=request.get("promotion_policy") or {},
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        store.append_audit(
            "promote_judge",
            "judge",
            project_id,
            judge_id,
            {
                "status": result["status"],
                "blocking_reasons": result["blocking_reasons"],
            },
        )
        return result

    @app.post("/api/judges/drafts", status_code=201)
    async def create_judge_draft(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["judges:write"])),
    ) -> dict[str, object]:
        del actor
        if "project_id" not in request:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        if "definition" in request:
            judge_type = request.get("judge_type") or request["definition"].get("judge_type")
            if not judge_type:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    "judge_type is required for explicit judge definitions",
                    "/judge_type",
                )
            draft = {
                "name": request.get("name") or request["definition"].get("name") or "Draft judge",
                "description": request.get("description")
                or request["definition"].get("description"),
                "judge_type": judge_type,
                "definition": request["definition"],
            }
        else:
            try:
                provider = _observed_model_provider(settings, metrics)
            except ModelConfigurationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
            trace = None
            spans = []
            if request.get("trace_id"):
                trace = store.get_trace(request["project_id"], request["trace_id"])
                if trace is None:
                    raise HTTPException(
                        status_code=404,
                        detail=_error("not_found", "Trace not found."),
                    )
                spans = (
                    store.list_spans(request["project_id"], request["trace_id"]) if trace else []
                )
            try:
                draft = await draft_judge_from_request(
                    provider,
                    request=request,
                    trace=trace,
                    spans=spans,
                )
            except ModelCallsDisabled as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
            if draft["status"] != "succeeded":
                raise HTTPException(
                    status_code=422,
                    detail=_error("invalid_model_output", "Judge draft model output was invalid."),
                )
        judge = store.create_judge(
            {
                "project_id": request["project_id"],
                "name": draft["name"],
                "description": draft.get("description"),
                "judge_type": draft["judge_type"],
                "status": "draft",
            },
            definition=draft["definition"],
            created_by=request.get("created_by"),
        )
        if draft.get("model_metadata"):
            judge["model_metadata"] = draft["model_metadata"]
        store.create_review_task(
            {
                "project_id": request["project_id"],
                "task_type": "judge_output",
                "source_entity_type": "judge",
                "source_entity_id": judge["judge_id"],
                "evidence_ids": [request["trace_id"]] if request.get("trace_id") else [],
            }
        )
        store.append_audit(
            "create_judge_draft",
            "judge",
            request["project_id"],
            judge["judge_id"],
        )
        return judge

    @app.post("/api/judges/{judge_id}/versions", status_code=201)
    def commit_judge_version(
        judge_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["judges:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "definition"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            version = store.commit_judge_version(
                request["project_id"],
                judge_id,
                definition=request["definition"],
                created_by=request.get("created_by"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        store.append_audit(
            "commit_judge_version",
            "judge",
            request["project_id"],
            judge_id,
            {"judge_version_id": version["judge_version_id"]},
        )
        return version

    @app.post("/api/judges/rubric/run", status_code=201)
    async def run_rubric_judge_endpoint(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["scores:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "trace_id", "judge"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        trace = store.get_trace(request["project_id"], request["trace_id"])
        if trace is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Trace not found."))
        try:
            provider = _observed_model_provider(settings, metrics)
        except ModelConfigurationError as exc:
            raise HTTPException(
                status_code=503,
                detail=_error("model_unavailable", str(exc), retryable=True),
            ) from exc
        spans = store.list_spans(request["project_id"], request["trace_id"])
        try:
            judge_started = time.perf_counter()
            score = await run_rubric_judge(
                provider,
                trace,
                spans,
                request["judge"],
                token_budget=settings.max_trace_tokens_for_judge,
            )
        except ModelCallsDisabled as exc:
            metrics.increment("judge.failures")
            raise HTTPException(
                status_code=503,
                detail=_error("model_unavailable", str(exc), retryable=True),
            ) from exc
        judge_elapsed_ms = (time.perf_counter() - judge_started) * 1000
        metrics.observe("judge.job_latency_ms", judge_elapsed_ms)
        if score["status"] == "invalid_output":
            metrics.increment("judge.invalid_output")
        if score.get("latency_ms") is None:
            score["latency_ms"] = int(judge_elapsed_ms)
        store.record_score(request["project_id"], score)
        store.append_audit(
            "run_rubric_judge",
            "score",
            request["project_id"],
            score["score_id"],
            {"trace_id": request["trace_id"], "judge_id": request["judge"]["judge_id"]},
        )
        return score

    @app.get("/api/behaviors")
    def list_behaviors(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_behaviors(project_id)}

    @app.post("/api/behaviors", status_code=201)
    def create_behavior(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "name"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        detector = request.get("detector") or {"type": "manual_label"}
        if detector.get("type") not in {
            "manual_label",
            "rule",
            "judge",
            "cluster_experiment",
            "external_signal",
        }:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "detector.type is invalid",
                "/detector/type",
            )
        behavior = store.create_behavior({**request, "detector": detector})
        store.append_audit(
            "create_behavior",
            "behavior",
            request["project_id"],
            behavior["behavior_id"],
        )
        issue_link = link_issue_artifact_or_404(
            project_id=request["project_id"],
            issue_id=request.get("issue_id_nullable"),
            target_type="behavior",
            target_id=behavior["behavior_id"],
            relation="proposed_behavior",
            source="behavior_create",
            evidence_trace_ids=request.get("evidence_trace_ids") or [],
            evidence_span_ids=request.get("evidence_span_ids") or [],
        )
        if issue_link:
            behavior["issue_link"] = issue_link
        return behavior

    @app.get("/api/behaviors/{behavior_id}")
    def get_behavior(
        behavior_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:read"])),
    ) -> dict[str, object]:
        del actor
        behavior = store.get_behavior(project_id, behavior_id)
        if behavior is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Behavior not found."),
            )
        return behavior

    @app.get("/api/behavior-matches")
    def list_behavior_matches(
        project_id: str,
        trace_id: str | None = None,
        behavior_id: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:read"])),
    ) -> dict[str, object]:
        del actor
        return {
            "data": store.list_behavior_matches(
                project_id,
                trace_id=trace_id,
                behavior_id=behavior_id,
            )
        }

    @app.post("/api/traces/{trace_id}/behavior-labels", status_code=201)
    def label_trace_behavior(
        trace_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "behavior_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            result = store.label_trace_behavior(
                request["project_id"],
                trace_id,
                request["behavior_id"],
                span_id=request.get("span_id_nullable"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        store.append_audit(
            "label_trace_behavior",
            "behavior_match",
            request["project_id"],
            result["behavior_match"]["behavior_match_id"],
            {
                "trace_id": trace_id,
                "behavior_id": request["behavior_id"],
                "span_id": request.get("span_id_nullable"),
            },
        )
        return result

    @app.post("/api/traces/{trace_id}/assertions/check")
    def check_trace_assertions(
        trace_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "assertions"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        trace = store.get_trace(request["project_id"], trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Trace not found."))
        result = evaluate_trace_assertions(
            store.list_spans(request["project_id"], trace_id),
            request["assertions"],
        )
        store.append_audit(
            "check_trace_assertions",
            "trace",
            request["project_id"],
            trace_id,
            {"status": result["status"], "failure_count": len(result["failures"])},
        )
        return result

    @app.post("/api/behaviors/{behavior_id}/backtest")
    def backtest_behavior_endpoint(
        behavior_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        behavior = store.get_behavior(project_id, behavior_id)
        if behavior is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Behavior not found."),
            )
        traces = store.search_traces(
            project_id,
            filters=request.get("filters") or {},
            full_text_query=request.get("query"),
            limit=int(request.get("limit", 100)),
        )
        spans_by_trace = {
            trace["trace_id"]: store.list_spans(project_id, trace["trace_id"])
            for trace in traces
        }
        scores_by_trace = {
            trace["trace_id"]: store.list_scores(project_id, trace["trace_id"])
            for trace in traces
        }
        result = backtest_behavior(
            behavior,
            traces,
            spans_by_trace,
            scores_by_trace,
            sample_limit=int(request.get("sample_limit", 10)),
        )
        persisted_matches = store.replace_behavior_backtest_matches(
            project_id,
            behavior_id,
            result["positive_examples"],
        )
        result["persisted_behavior_matches"] = persisted_matches
        if result["review_required"]:
            review_task = store.create_review_task(
                {
                    "project_id": project_id,
                    "task_type": "behavior_candidate",
                    "source_entity_type": "behavior",
                    "source_entity_id": behavior_id,
                    "evidence_ids": _behavior_backtest_evidence_ids(result),
                }
            )
            result["review_task"] = review_task
        store.append_audit(
            "backtest_behavior",
            "behavior",
            project_id,
            behavior_id,
            {"positive_count": result["positive_count"], "trace_count": result["trace_count"]},
        )
        return result

    @app.get("/api/datasets")
    def list_datasets(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["datasets:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_datasets(project_id)}

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(
        dataset_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["datasets:read"])),
    ) -> dict[str, object]:
        del actor
        dataset = store.get_dataset(project_id, dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Dataset not found."))
        return dataset

    @app.post("/api/datasets", status_code=201)
    def create_dataset(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["datasets:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "name"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        dataset = store.create_dataset(
            request["project_id"],
            request["name"],
            request.get("description"),
        )
        store.append_audit(
            "create_dataset",
            "dataset",
            request["project_id"],
            dataset["dataset_id"],
        )
        issue_link = link_issue_artifact_or_404(
            project_id=request["project_id"],
            issue_id=request.get("issue_id_nullable"),
            target_type="dataset",
            target_id=dataset["dataset_id"],
            relation="regression_dataset",
            source="dataset_create",
        )
        if issue_link:
            dataset["issue_link"] = issue_link
        return dataset

    @app.get("/api/datasets/{dataset_id}/examples")
    def list_dataset_examples(
        dataset_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["datasets:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_dataset_examples(project_id, dataset_id)}

    @app.post("/api/datasets/{dataset_id}/examples/from-trace", status_code=201)
    def add_trace_to_dataset(
        dataset_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["datasets:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "trace_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        example = store.add_trace_to_dataset(
            request["project_id"],
            dataset_id,
            request["trace_id"],
            labels=request.get("labels") or [],
        )
        store.append_audit(
            "add_trace_to_dataset",
            "dataset_example",
            request["project_id"],
            example["dataset_example_id"],
            {"dataset_id": dataset_id, "trace_id": request["trace_id"]},
        )
        issue_link = link_issue_artifact_or_404(
            project_id=request["project_id"],
            issue_id=request.get("issue_id_nullable"),
            target_type="dataset_example",
            target_id=example["dataset_example_id"],
            relation="evidence_example",
            source="dataset_example_create",
            evidence_trace_ids=[request["trace_id"]],
        )
        if issue_link:
            example["issue_link"] = issue_link
        return example

    @app.get("/api/evals")
    def list_eval_runs(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["evals:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_eval_runs(project_id)}

    @app.get("/api/evals/analytics")
    def get_eval_run_analytics(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["evals:read"])),
    ) -> dict[str, object]:
        del actor
        return store.eval_run_analytics(project_id)

    @app.post("/api/evals/run", status_code=201)
    async def run_eval_endpoint(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["evals:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "dataset_version_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        judges = _eval_judges_from_request(store, request)
        if not judges:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "At least one judge or judge_id is required",
                "/judges",
            )
        provider = None
        if any(judge.get("judge_type") == "rubric_judge" for judge in judges):
            try:
                provider = _observed_model_provider(settings, metrics)
            except ModelConfigurationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
        try:
            eval_started = time.perf_counter()
            run = await run_eval(
                store,
                project_id=request["project_id"],
                dataset_version_id=request["dataset_version_id"],
                judges=judges,
                runner=request.get("runner"),
                provider=provider,
                token_budget=settings.max_trace_tokens_for_judge,
                baseline_eval_run_id=request.get("baseline_eval_run_id"),
                prompt_version_id=request.get("prompt_version_id"),
                agent_config_version_id=request.get("agent_config_version_id"),
                runtime_context=request.get("runtime_context") or {},
            )
        except ModelCallsDisabled as exc:
            metrics.increment("eval.failures")
            raise HTTPException(
                status_code=503,
                detail=_error("model_unavailable", str(exc), retryable=True),
            ) from exc
        eval_elapsed_ms = (time.perf_counter() - eval_started) * 1000
        metrics.observe("eval.job_latency_ms", eval_elapsed_ms)
        metrics.observe("worker.job_latency_ms", eval_elapsed_ms)
        store.append_audit(
            "run_eval",
            "eval_run",
            request["project_id"],
            run["eval_run_id"],
            {"dataset_version_id": request["dataset_version_id"]},
        )
        issue_link = link_issue_artifact_or_404(
            project_id=request["project_id"],
            issue_id=request.get("issue_id_nullable"),
            target_type="eval_run",
            target_id=run["eval_run_id"],
            relation="regression_eval",
            source="eval_run",
            metadata={"dataset_version_id": request["dataset_version_id"]},
        )
        if issue_link:
            run["issue_link"] = issue_link
        return run

    @app.get("/api/evals/{eval_run_id}")
    def get_eval_run(
        eval_run_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["evals:read"])),
    ) -> dict[str, object]:
        del actor
        run = store.get_eval_run(project_id, eval_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Eval run not found."))
        return run

    @app.get("/api/evals/{eval_run_id}/results")
    def list_eval_results(
        eval_run_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["evals:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_eval_results(project_id, eval_run_id)}

    @app.post("/api/evals/compare")
    def compare_eval_runs(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["evals:read"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "baseline_eval_run_id", "candidate_eval_run_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            comparison_started = time.perf_counter()
            comparison = store.compare_eval_runs(
                request["project_id"],
                request["baseline_eval_run_id"],
                request["candidate_eval_run_id"],
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        metrics.observe(
            "root_cause.comparison_latency_ms",
            (time.perf_counter() - comparison_started) * 1000,
        )
        return comparison

    @app.post("/api/docs/search")
    def search_docs(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["docs:read"])),
    ) -> dict[str, object]:
        del actor
        if "query" not in request:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "query is required",
                "/query",
            )
        return search_public_docs(str(request["query"]), limit=int(request.get("limit", 20)))

    @app.get("/api/saved-searches")
    def list_saved_searches(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_saved_searches(project_id)}

    @app.post("/api/saved-searches", status_code=201)
    def create_saved_search(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "name", "query"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        item = store.create_saved_search(
            request["project_id"],
            request["name"],
            request["query"],
            owner_user_id=request.get("owner_user_id"),
            visibility=request.get("visibility", "project"),
        )
        store.append_audit(
            "create_saved_search",
            "saved_search",
            request["project_id"],
            item["saved_search_id"],
        )
        return item

    @app.get("/api/saved-searches/{saved_search_id}")
    def get_saved_search(
        saved_search_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        item = store.get_saved_search(project_id, saved_search_id)
        if item is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Saved search not found."),
            )
        return item

    @app.get("/api/prompts")
    def list_prompts(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["prompts:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_prompts(project_id)}

    @app.post("/api/prompts", status_code=201)
    def create_prompt(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["prompts:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "name"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        item = store.create_prompt(request)
        store.append_audit("create_prompt", "prompt", request["project_id"], item["prompt_id"])
        return item

    @app.get("/api/prompts/{prompt_id}")
    def get_prompt(
        prompt_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["prompts:read"])),
    ) -> dict[str, object]:
        del actor
        item = store.get_prompt(project_id, prompt_id)
        if item is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Prompt not found."))
        return item

    @app.post("/api/prompts/{prompt_id}/versions", status_code=201)
    def commit_prompt_version(
        prompt_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["prompts:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "template_text", "variables_schema"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            version = store.commit_prompt_version(
                request["project_id"],
                prompt_id,
                template_text=request["template_text"],
                variables_schema=request["variables_schema"],
                metadata=request.get("metadata"),
                parent_commit_id=request.get("parent_commit_id"),
                tag=request.get("tag"),
            )
        except (KeyError, ValueError) as exc:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                str(exc),
                "/template_text",
            ) from exc
        store.append_audit(
            "commit_prompt_version",
            "prompt",
            request["project_id"],
            prompt_id,
            {"commit_id": version["commit_id"], "tag": request.get("tag")},
        )
        return version

    @app.post("/api/prompts/{prompt_id}/render")
    def render_prompt_endpoint(
        prompt_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["prompts:read"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "commit_id", "variables"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        version = store.get_prompt_version_by_commit(
            request["project_id"],
            prompt_id,
            request["commit_id"],
        )
        if version is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Prompt version not found."),
            )
        try:
            rendered = render_prompt(version["template_text"], request["variables"])
        except (KeyError, ValueError) as exc:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                str(exc),
                "/variables",
            ) from exc
        return {"prompt_id": prompt_id, "commit_id": request["commit_id"], "rendered": rendered}

    @app.post("/api/prompts/{prompt_id}/diff")
    def diff_prompt_versions(
        prompt_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["prompts:read"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "old_commit_id", "new_commit_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            return store.diff_prompt_versions(
                request["project_id"],
                prompt_id,
                request["old_commit_id"],
                request["new_commit_id"],
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", str(exc)),
            ) from exc

    @app.get("/api/agent-configs")
    def list_agent_configs(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["agent_configs:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_agent_configs(project_id)}

    @app.post("/api/agent-configs", status_code=201)
    def create_agent_config(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["agent_configs:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "name", "config_type"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        item = store.create_agent_config(request)
        store.append_audit(
            "create_agent_config",
            "agent_config",
            request["project_id"],
            item["agent_config_id"],
        )
        return item

    @app.get("/api/agent-configs/{agent_config_id}")
    def get_agent_config(
        agent_config_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["agent_configs:read"])),
    ) -> dict[str, object]:
        del actor
        item = store.get_agent_config(project_id, agent_config_id)
        if item is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Agent config not found."),
            )
        return item

    @app.post("/api/agent-configs/{agent_config_id}/versions", status_code=201)
    def commit_agent_config_version(
        agent_config_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["agent_configs:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "content"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            version = store.commit_agent_config_version(
                request["project_id"],
                agent_config_id,
                content=request["content"],
                metadata=request.get("metadata"),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", str(exc)),
            ) from exc
        store.append_audit(
            "commit_agent_config_version",
            "agent_config",
            request["project_id"],
            agent_config_id,
            {"commit_id": version["commit_id"]},
        )
        return version

    @app.post("/api/agent-configs/{agent_config_id}/compare")
    def compare_agent_configs(
        agent_config_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["agent_configs:read"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "old_commit_id", "new_commit_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            return store.compare_agent_config_versions(
                request["project_id"],
                agent_config_id,
                request["old_commit_id"],
                request["new_commit_id"],
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", str(exc)),
            ) from exc

    @app.get("/api/trace-dimensions")
    def list_trace_dimensions(
        project_id: str,
        trace_id: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_trace_dimensions(project_id, trace_id)}

    @app.post("/api/trace-dimensions", status_code=201)
    def create_trace_dimension(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "trace_id", "key", "value"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        item = store.add_trace_dimension(
            request["project_id"],
            request["trace_id"],
            request["key"],
            str(request["value"]),
            value_type=request.get("value_type", "string"),
            source=request.get("source", "manual"),
        )
        store.append_audit(
            "create_trace_dimension",
            "trace_dimension",
            request["project_id"],
            item["trace_dimension_id"],
        )
        return item

    @app.get("/api/issues")
    def list_issues(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["issues:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_issues(project_id)}

    @app.post("/api/issues", status_code=201)
    def create_issue(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["issues:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "title"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        item = store.create_issue(request)
        store.append_audit("create_issue", "issue", request["project_id"], item["issue_id"])
        return item

    @app.get("/api/issues/{issue_id}")
    def get_issue(
        issue_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["issues:read"])),
    ) -> dict[str, object]:
        del actor
        issue = store.get_issue(project_id, issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Issue not found."))
        return issue

    @app.get("/api/issues/{issue_id}/links")
    def list_issue_links(
        issue_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["issues:read"])),
    ) -> dict[str, object]:
        del actor
        if store.get_issue(project_id, issue_id) is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Issue not found."))
        return {"data": store.list_issue_links(project_id, issue_id)}

    @app.post("/api/issues/{issue_id}/links", status_code=201)
    def create_issue_link(
        issue_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["issues:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "target_type", "target_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        if request["target_type"] not in ISSUE_LINK_TARGET_TYPES:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "target_type is invalid",
                "/target_type",
            )
        try:
            link = store.create_issue_link(
                {
                    **request,
                    "issue_id": issue_id,
                    "relation": request.get("relation", "related_to"),
                    "source": request.get("source", "manual"),
                    "evidence_trace_ids": request.get("evidence_trace_ids") or [],
                    "evidence_span_ids": request.get("evidence_span_ids") or [],
                    "metadata": request.get("metadata") or {},
                }
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        store.append_audit(
            "create_issue_link",
            "issue_link",
            request["project_id"],
            link["issue_link_id"],
            {
                "issue_id": issue_id,
                "target_type": link["target_type"],
                "target_id": link["target_id"],
                "relation": link["relation"],
            },
        )
        return link

    @app.post("/api/issues/from-screenshot", status_code=201)
    def create_issue_from_screenshot(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["issues:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "title", "screenshot_payload_id_nullable"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        issue = store.create_issue(
            {
                **request,
                "source_type": "screenshot",
                "description": request.get("description")
                or request.get("reporter_text")
                or "Screenshot issue report.",
            }
        )
        intake_evidence = _normalize_screenshot_intake_evidence(request)
        _link_screenshot_intake_payloads(store, issue, intake_evidence)
        candidates = _screenshot_seed_trace_candidates(store, request, intake_evidence)
        store.append_audit(
            "create_issue_from_screenshot",
            "issue",
            request["project_id"],
            issue["issue_id"],
            {
                "candidate_trace_ids": [candidate["trace_id"] for candidate in candidates],
                "intake_evidence": intake_evidence,
            },
        )
        return {**issue, "candidate_seed_traces": candidates, "intake_evidence": intake_evidence}

    @app.post("/api/chatops/investigate", status_code=201)
    def chatops_investigate(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["investigations:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "message"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        issue = store.create_issue(
            {
                "project_id": request["project_id"],
                "source_type": "chat",
                "source_ref_nullable": request.get("source_ref_nullable"),
                "reporter_nullable": request.get("reporter_nullable"),
                "title": request.get("title") or request["message"][:80],
                "description": request["message"],
                "seed_trace_id_nullable": request.get("seed_trace_id_nullable"),
                "seed_session_id_nullable": request.get("seed_session_id_nullable"),
            }
        )
        run = store.start_investigation(
            {
                "project_id": request["project_id"],
                "issue_id_nullable": issue["issue_id"],
                "seed_trace_id_nullable": request.get("seed_trace_id_nullable"),
                "seed_session_id_nullable": request.get("seed_session_id_nullable"),
                "natural_language_problem_nullable": request["message"],
                "filters": request.get("filters") or {},
            }
        )
        store.append_audit(
            "chatops_investigate",
            "investigation_run",
            request["project_id"],
            run["investigation_run_id"],
            {"issue_id": issue["issue_id"]},
        )
        return {
            "status": "created",
            "response": (
                "Created issue and investigation run. "
                "Review canonical artifacts in OpenABM."
            ),
            "issue": issue,
            "investigation_run": run,
            "links": {
                "issue": f"issue://{issue['issue_id']}",
                "investigation_run": f"investigation-run://{run['investigation_run_id']}",
            },
        }

    @app.get("/api/data-classification-policies")
    def list_data_classification_policies(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["policies:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_data_classification_policies(project_id)}

    @app.post("/api/data-classification-policies", status_code=201)
    def create_data_classification_policy(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["policies:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "default_classification", "rules"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            normalize_classification(request["default_classification"])
        except ValueError as exc:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                str(exc),
                "/default_classification",
            ) from exc
        item = store.create_data_classification_policy(request)
        store.append_audit(
            "create_data_classification_policy",
            "data_classification_policy",
            request["project_id"],
            item["policy_id"],
        )
        return item

    @app.get("/api/retention-policies")
    def list_retention_policies(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["policies:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_retention_policies(project_id)}

    @app.post("/api/retention-policies", status_code=201)
    def create_retention_policy(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["policies:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "name", "rules"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        item = store.create_retention_policy(request)
        store.append_audit(
            "create_retention_policy",
            "retention_policy",
            request["project_id"],
            item["retention_policy_id"],
        )
        return item

    @app.post("/api/retention-policies/{retention_policy_id}/apply")
    def apply_retention_policy(
        retention_policy_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["policies:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        try:
            result = store.apply_retention_policy(
                project_id,
                retention_policy_id,
                dry_run=bool(request.get("dry_run", True)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        except ValueError as exc:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                str(exc),
                "/status",
            ) from exc
        store.append_audit(
            "apply_retention_policy",
            "retention_policy",
            project_id,
            retention_policy_id,
            {
                "dry_run": result["dry_run"],
                "candidate_count": len(result["candidate_trace_ids"]),
                "deleted_count": len(result["deleted_trace_ids"]),
            },
        )
        return result

    @app.post("/api/exports/project")
    def export_project(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["exports:read"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        bundle = store.export_project_bundle(
            project_id,
            include_payloads=bool(request.get("include_payloads", False)),
        )
        store.append_audit(
            "export_project",
            "project",
            project_id,
            project_id,
            {"export_id": bundle["manifest"]["export_id"]},
        )
        return bundle

    @app.post("/api/data-classification/classify")
    def classify_data(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["policies:read"])),
    ) -> dict[str, object]:
        del actor
        for key in ["payload", "policy"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        try:
            result = classify_payload(request["payload"], request["policy"])
        except ValueError as exc:
            raise SchemaValidationFailure("schema_validation_failed", str(exc), "/policy") from exc
        max_classification = request.get("max_classification")
        if max_classification:
            try:
                result["payload"] = redact_if_needed(
                    request["payload"],
                    result["classification"],
                    max_classification,
                )
            except ValueError as exc:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    str(exc),
                    "/max_classification",
                ) from exc
        return result

    @app.get("/api/review-tasks")
    def list_review_tasks(
        project_id: str,
        status: str | None = None,
        task_type: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["reviews:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_review_tasks(project_id, status=status, task_type=task_type)}

    @app.post("/api/review-tasks", status_code=201)
    def create_review_task(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["reviews:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "task_type", "source_entity_type", "source_entity_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        task = store.create_review_task(request)
        store.append_audit(
            "create_review_task",
            "review_task",
            task["project_id"],
            task["review_task_id"],
        )
        return task

    @app.patch("/api/review-tasks/{review_task_id}")
    def update_review_task(
        review_task_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["reviews:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        task = store.update_review_task(project_id, review_task_id, request)
        store.append_audit(
            "update_review_task",
            "review_task",
            project_id,
            review_task_id,
            {"status": task["status"], "decision": task["decision_nullable"]},
        )
        return task

    @app.get("/api/notification-targets")
    def list_notification_targets(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["notifications:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_notification_targets(project_id)}

    @app.post("/api/notification-targets", status_code=201)
    def create_notification_target(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["notifications:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "type", "display_name"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        _validate_notification_target_request(request)
        target = store.create_notification_target(request)
        store.append_audit(
            "create_notification_target",
            "notification_target",
            target["project_id"],
            target["target_id"],
        )
        return target

    @app.get("/api/automations")
    def list_automations(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["automations:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_automations(project_id)}

    @app.post("/api/automations", status_code=201)
    def create_automation(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["automations:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "name", "trigger", "actions"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        automation = store.create_automation(request)
        store.append_audit(
            "create_automation",
            "automation",
            request["project_id"],
            automation["automation_id"],
        )
        return automation

    @app.get("/api/automations/{automation_id}")
    def get_automation(
        automation_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["automations:read"])),
    ) -> dict[str, object]:
        del actor
        automation = store.get_automation(project_id, automation_id)
        if automation is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Automation not found."),
            )
        return automation

    @app.get("/api/automations/{automation_id}/runs")
    def list_automation_runs(
        automation_id: str,
        project_id: str,
        limit: int = 25,
        actor: dict[str, object] = Depends(auth_dependency(["automations:read"])),
    ) -> dict[str, object]:
        del actor
        if store.get_automation(project_id, automation_id) is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Automation not found."),
            )
        return {"data": store.list_automation_runs(project_id, automation_id, limit=limit)}

    @app.post("/api/automations/{automation_id}/preview")
    def preview_automation_matches(
        automation_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["automations:read"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        automation = store.get_automation(project_id, automation_id)
        if automation is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Automation not found."),
            )
        traces = store.search_traces(
            project_id,
            filters=request.get("filters") or {},
            full_text_query=request.get("query"),
            limit=int(request.get("limit", 100)),
        )
        matches = []
        for trace in traces:
            spans = store.list_spans(project_id, trace["trace_id"])
            condition_result = evaluate_automation_conditions(automation, trace, spans)
            if condition_result["passed"]:
                matches.append(
                    {
                        "trace_id": trace["trace_id"],
                        "session_id": trace.get("session_id"),
                        "status": trace.get("status"),
                        "started_at": trace.get("started_at"),
                        "condition_result": condition_result,
                    }
                )
        return {
            "automation_id": automation_id,
            "project_id": project_id,
            "trace_count": len(traces),
            "match_count": len(matches),
            "matches": matches,
        }

    @app.post("/api/automations/{automation_id}/run", status_code=201)
    def run_automation(
        automation_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["automations:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        trace_id = request.get("trace_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        automation = store.get_automation(project_id, automation_id)
        if automation is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Automation not found."),
            )
        idempotency_key = request.get("idempotency_key") or (
            f"{automation_id}:{trace_id}" if trace_id else None
        )
        if idempotency_key:
            existing = store.get_automation_run_by_idempotency(
                project_id,
                automation_id,
                idempotency_key,
            )
            if existing is not None:
                return {**existing, "duplicate": True}
        trace = store.get_trace(project_id, trace_id) if trace_id else None
        spans = store.list_spans(project_id, trace_id) if trace_id else []
        condition_result = evaluate_automation_conditions(automation, trace, spans)
        planned = planned_automation_actions(automation, trace_id=trace_id)
        now = utc_now()
        cooldown_plan = plan_automation_cooldown(
            automation,
            project_id=project_id,
            trace_id=trace_id,
        )
        latest_cooldown_run = (
            store.get_latest_automation_run_for_cooldown(
                project_id,
                automation_id,
                cooldown_plan["cooldown_key"],
            )
            if cooldown_plan.get("cooldown_key")
            else None
        )
        cooldown_result = evaluate_automation_cooldown(
            cooldown_plan,
            latest_cooldown_run,
            now=now,
        )
        if not condition_result["passed"]:
            action_results = []
            status = "skipped_conditions"
        elif cooldown_result.get("active"):
            action_results = []
            status = "skipped_cooldown"
        else:
            action_results = _execute_automation_actions(
                store,
                settings,
                secret_cipher,
                project_id,
                planned,
                trace_id,
            )
            status = _automation_run_status(action_results)
        run = store.record_automation_run(
            {
                "automation_run_id": new_id("automation_run"),
                "automation_id": automation_id,
                "project_id": project_id,
                "trigger_entity_type": "trace" if trace_id else None,
                "trigger_entity_id": trace_id,
                "idempotency_key": idempotency_key,
                "cooldown_key": cooldown_result.get("cooldown_key"),
                "status": status,
                "condition_result": condition_result,
                "cooldown_result": cooldown_result,
                "action_results": action_results,
                "started_at": now,
                "completed_at": now,
            }
        )
        store.append_audit(
            "run_automation",
            "automation",
            project_id,
            automation_id,
            {"automation_run_id": run["automation_run_id"], "status": run["status"]},
        )
        return run

    @app.get("/api/context-packs")
    def list_context_packs(
        project_id: str,
        issue_id: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["context_packs:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_agent_context_packs(project_id, issue_id=issue_id)}

    @app.get("/api/context-packs/{context_pack_id}")
    def get_context_pack(
        context_pack_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["context_packs:read"])),
    ) -> dict[str, object]:
        del actor
        item = store.get_agent_context_pack(project_id, context_pack_id)
        if item is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Context pack not found."),
            )
        return item

    @app.post("/api/context-packs", status_code=201)
    async def create_context_pack(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["context_packs:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "source_trace_ids"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        project_id = request["project_id"]
        traces = []
        spans_by_trace = {}
        dimensions_by_trace = {}
        for trace_id in request["source_trace_ids"]:
            trace = store.get_trace(project_id, trace_id)
            if trace is None:
                raise HTTPException(status_code=404, detail=_error("not_found", "Trace not found."))
            traces.append(trace)
            spans_by_trace[trace_id] = store.list_spans(project_id, trace_id)
            dimensions_by_trace[trace_id] = store.list_trace_dimensions(project_id, trace_id)
        issue_id = request.get("issue_id_nullable")
        issue = store.get_issue(project_id, issue_id) if issue_id else None
        try:
            provider = _observed_model_provider(settings, metrics)
            content = await build_agent_context_pack_content(
                provider,
                issue=issue,
                traces=traces,
                spans_by_trace=spans_by_trace,
                dimensions_by_trace=dimensions_by_trace,
                allowed_next_actions=request.get("allowed_next_actions")
                or ["read", "draft_behavior", "draft_judge", "create_dataset"],
                classification=request.get("classification", "internal"),
            )
        except (ModelCallsDisabled, ModelConfigurationError):
            content = _deterministic_context_pack_content(
                issue,
                traces,
                spans_by_trace,
                request["source_trace_ids"],
            )
        item = store.create_agent_context_pack(
            project_id=project_id,
            issue_id=issue_id,
            source_trace_ids=request["source_trace_ids"],
            content=content,
            classification=request.get("classification", "internal"),
        )
        store.append_audit(
            "create_context_pack",
            "agent_context_pack",
            project_id,
            item["context_pack_id"],
            {"source_trace_ids": request["source_trace_ids"]},
        )
        return item

    @app.get("/api/investigations")
    def list_investigations(
        project_id: str,
        issue_id: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["investigations:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_investigation_runs(project_id, issue_id=issue_id)}

    @app.get("/api/investigations/{investigation_run_id}")
    def get_investigation(
        investigation_run_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["investigations:read"])),
    ) -> dict[str, object]:
        del actor
        run = store.get_investigation_run(project_id, investigation_run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Investigation run not found."),
            )
        return run

    @app.post("/api/investigations", status_code=201)
    async def start_investigation(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["investigations:write"])),
    ) -> dict[str, object]:
        del actor
        if "project_id" not in request:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        if request.get("issue_id_nullable") and store.get_issue(
            request["project_id"], request["issue_id_nullable"]
        ) is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Issue not found."))
        investigation_started = time.perf_counter()
        impact_started = time.perf_counter()
        run = run_investigation_workflow(store, request)
        metrics.observe(
            "impact_report.generation_latency_ms",
            (time.perf_counter() - impact_started) * 1000,
        )
        try:
            provider = _observed_model_provider(settings, metrics)
            traces = [
                trace
                for trace_id in run["result"]["evidence_trace_ids"]
                if (trace := store.get_trace(request["project_id"], trace_id)) is not None
            ]
            spans_by_trace = {
                trace["trace_id"]: store.list_spans(request["project_id"], trace["trace_id"])
                for trace in traces
            }
            issue_id = request.get("issue_id_nullable")
            issue = store.get_issue(request["project_id"], issue_id) if issue_id else None
            assistance = await assist_investigation(
                provider,
                issue=issue,
                traces=traces,
                spans_by_trace=spans_by_trace,
                impact_report=run["result"]["impact_report"],
            )
            run["result"]["model_assistance"] = assistance
            if assistance["suspected_root_causes"]:
                run["result"]["suspected_root_causes"] = assistance["suspected_root_causes"]
            if assistance["recommended_next_actions"]:
                run["result"]["recommended_next_actions"] = assistance["recommended_next_actions"]
            run = store.update_investigation_result(
                request["project_id"],
                run["investigation_run_id"],
                run["result"],
            )
        except ModelCallsDisabled:
            run["result"]["model_assistance"] = {"status": "model_disabled"}
            run = store.update_investigation_result(
                request["project_id"],
                run["investigation_run_id"],
                run["result"],
            )
        except ModelConfigurationError as exc:
            run["result"]["model_assistance"] = {"status": "model_unavailable", "reason": str(exc)}
            run = store.update_investigation_result(
                request["project_id"],
                run["investigation_run_id"],
                run["result"],
            )
        review_tasks = _create_investigation_review_tasks(store, run)
        if review_tasks:
            run["result"]["review_task_ids"] = [
                task["review_task_id"] for task in review_tasks
            ]
            run = store.update_investigation_result(
                request["project_id"],
                run["investigation_run_id"],
                run["result"],
            )
        store.append_audit(
            "start_investigation",
            "investigation_run",
            request["project_id"],
            run["investigation_run_id"],
        )
        metrics.observe(
            "investigation.run_latency_ms",
            (time.perf_counter() - investigation_started) * 1000,
        )
        return run

    @app.get("/api/grounding-checks")
    def list_grounding_checks(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["grounding:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_grounding_checks(project_id)}

    @app.post("/api/grounding-checks", status_code=201)
    async def create_grounding_check(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["grounding:write"])),
    ) -> dict[str, object]:
        del actor
        for key in ["project_id", "trace_id"]:
            if key not in request:
                raise SchemaValidationFailure(
                    "schema_validation_failed",
                    f"{key} is required",
                    f"/{key}",
                )
        trace = store.get_trace(request["project_id"], request["trace_id"])
        if trace is None:
            raise HTTPException(status_code=404, detail=_error("not_found", "Trace not found."))
        spans = store.list_spans(request["project_id"], request["trace_id"])
        model_extraction = None
        if request.get("claims"):
            claims = request["claims"]
        elif request.get("extract_claims_with_model"):
            try:
                provider = _observed_model_provider(settings, metrics)
                model_extraction = await extract_grounding_claims_with_model(
                    provider,
                    text=request.get("text") or trace.get("summary") or "",
                    trace=trace,
                    spans=spans,
                )
            except ModelConfigurationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
            except ModelCallsDisabled as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
            if model_extraction["status"] != "succeeded":
                raise HTTPException(
                    status_code=422,
                    detail=_error(
                        "invalid_model_output",
                        "Grounding claim extraction model output was invalid.",
                    ),
                )
            claims = model_extraction["claims"]
        else:
            claims = claims_from_text(request.get("text", ""))
        result = evaluate_grounding_claims(claims, spans)
        if model_extraction is not None:
            result["model_extraction"] = {
                "possible_contradictions": model_extraction["possible_contradictions"],
                "uncertainty": model_extraction["uncertainty"],
                "model_metadata": model_extraction["model_metadata"],
            }
        check = store.create_grounding_check(
            request["project_id"],
            request["trace_id"],
            result,
            span_id=request.get("span_id_nullable"),
        )
        if check["status"] == "needs_review":
            store.create_review_task(
                {
                    "project_id": request["project_id"],
                    "task_type": "grounding_check",
                    "source_entity_type": "grounding_check",
                    "source_entity_id": check["grounding_check_id"],
                    "evidence_ids": [request["trace_id"], *check["evidence_span_ids"]],
                }
            )
        store.append_audit(
            "create_grounding_check",
            "grounding_check",
            request["project_id"],
            check["grounding_check_id"],
        )
        return check

    @app.get("/api/novelty-runs")
    def list_novelty_runs(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_novelty_runs(project_id)}

    @app.post("/api/novelty-runs", status_code=201)
    async def create_novelty_run(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        traces = store.search_traces(
            project_id,
            filters=request.get("filters") or {"status": "error"},
            full_text_query=request.get("query"),
            limit=int(request.get("limit", 100)),
        )
        spans_by_trace = {
            trace["trace_id"]: store.list_spans(project_id, trace["trace_id"])
            for trace in traces
        }
        result = detect_novel_behavior_candidates(
            traces,
            spans_by_trace,
            store.list_behaviors(project_id),
        )
        if request.get("semantic_grouping_with_model"):
            try:
                provider = _observed_model_provider(settings, metrics)
                result = await group_novel_behavior_candidates_with_model(
                    provider,
                    result,
                    traces=traces,
                    spans_by_trace=spans_by_trace,
                )
            except ModelConfigurationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
            except ModelCallsDisabled as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
            if result.get("semantic_grouping", {}).get("status") == "invalid_model_output":
                raise HTTPException(
                    status_code=422,
                    detail=_error(
                        "invalid_model_output",
                        "Novelty grouping model output was invalid.",
                    ),
                )
        run = store.create_novelty_run(project_id, request, result)
        for index, candidate in enumerate(result["new_behavior_candidates"]):
            store.create_review_task(
                {
                    "project_id": project_id,
                    "task_type": "behavior_candidate",
                    "source_entity_type": "novelty_run",
                    "source_entity_id": f"{run['novelty_run_id']}#candidate:{index}",
                    "evidence_ids": candidate["representative_positive_traces"],
                }
            )
        store.append_audit(
            "create_novelty_run",
            "novelty_run",
            project_id,
            run["novelty_run_id"],
            {"candidate_count": len(result["new_behavior_candidates"])},
        )
        return run

    @app.get("/api/impact-reports")
    def list_impact_reports(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["investigations:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_impact_reports(project_id)}

    @app.get("/api/impact-reports/{report_id}")
    def get_impact_report(
        report_id: str,
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["investigations:read"])),
    ) -> dict[str, object]:
        del actor
        report = store.get_impact_report(project_id, report_id)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", "Impact report not found."),
            )
        return report

    @app.get("/api/affected-entities")
    def list_affected_entities(
        project_id: str,
        issue_id: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["investigations:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_affected_entities(project_id, issue_id=issue_id)}

    @app.patch("/api/affected-entities/{affected_entity_id}")
    def update_affected_entity(
        affected_entity_id: str,
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["investigations:write"])),
    ) -> dict[str, object]:
        del actor
        project_id = request.get("project_id")
        if not project_id:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "project_id is required",
                "/project_id",
            )
        try:
            entity = store.update_affected_entity(project_id, affected_entity_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
        except ValueError as exc:
            raise SchemaValidationFailure(
                "schema_validation_failed",
                str(exc),
                "/status",
            ) from exc
        store.append_audit(
            "update_affected_entity",
            "affected_entity",
            project_id,
            affected_entity_id,
            {"status": entity["status"], "issue_id": entity["issue_id"]},
        )
        return entity

    _register_v1_aliases(app)
    return app


def _register_v1_aliases(app: FastAPI) -> None:
    routes = list(app.routes)
    for route in routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        app.add_api_route(
            route.path.replace("/api", "/v1", 1),
            route.endpoint,
            methods=list(route.methods or []),
            status_code=route.status_code,
            response_class=route.response_class,
            name=f"v1_{route.name}",
            include_in_schema=True,
        )


class _ObservedModelProvider:
    def __init__(self, provider: Any, metrics: Metrics) -> None:
        self._provider = provider
        self._metrics = metrics
        self.adapter_name = str(getattr(provider, "adapter_name", "unknown"))
        self.supported_capabilities = list(getattr(provider, "supported_capabilities", []))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def health_check(self) -> Any:
        return self._provider.health_check()

    async def chat_completion(
        self,
        request: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        kwargs = {}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        return await self._observe(
            "chat_completion",
            self._provider.chat_completion,
            request,
            **kwargs,
        )

    async def structured_completion(
        self,
        request: dict[str, Any],
        schema: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        kwargs = {}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        return await self._observe(
            "structured_completion",
            self._provider.structured_completion,
            request,
            schema,
            **kwargs,
        )

    async def tool_completion(
        self,
        request: dict[str, Any],
        tools: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        kwargs = {}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        return await self._observe(
            "tool_completion",
            self._provider.tool_completion,
            request,
            tools,
            **kwargs,
        )

    async def _observe(
        self,
        method: str,
        call: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = await call(*args, **kwargs)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._metrics.increment("model_provider.errors")
            self._metrics.increment(f"model_provider.{self.adapter_name}.{method}.errors")
            self._metrics.observe("model_provider.latency_ms", elapsed_ms)
            self._metrics.observe(
                f"model_provider.{self.adapter_name}.{method}.latency_ms",
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._metrics.observe("model_provider.latency_ms", elapsed_ms)
        self._metrics.observe(
            f"model_provider.{self.adapter_name}.{method}.latency_ms",
            elapsed_ms,
        )
        if result.get("status") == "invalid_output":
            self._metrics.increment("model_provider.invalid_output")
            self._metrics.increment(
                f"model_provider.{self.adapter_name}.{method}.invalid_output"
            )
        return result


def _observed_model_provider(settings: Settings, metrics: Metrics) -> _ObservedModelProvider:
    try:
        provider = model_provider_from_settings(settings)
    except ModelConfigurationError:
        metrics.increment("model_provider.configuration_errors")
        raise
    return _ObservedModelProvider(provider, metrics)


def _refresh_observability_gauges(
    metrics: Metrics,
    store: SQLiteStore,
    project_id: str,
) -> None:
    try:
        status = store.ops_status(project_id)
    except Exception:
        metrics.increment("ops.metrics_refresh_errors")
        return

    for table, count in status["storage_growth"].items():
        metrics.set_gauge(f"storage.{table}.rows", count)

    payload_growth = status["payload_store_growth"]
    metrics.set_gauge("payload_store.objects", payload_growth["object_count"])
    metrics.set_gauge("payload_store.bytes", payload_growth["total_bytes"])

    queue_depth = status["queue_depth"]
    for queue_name, depth in queue_depth.items():
        metrics.set_gauge(f"queue.{queue_name}", depth)

    metrics.set_gauge("automation.action_failures", status["automation_action_failures"])
    metrics.set_gauge("dead_letter.count", status["dead_letter_count"])
    metrics.set_gauge("worker.heartbeats", len(status["worker_heartbeats"]))
    metrics.set_gauge(
        "retention.last_job_present",
        1 if status["retention_job_status"] else 0,
    )

    for heartbeat in status["worker_heartbeats"]:
        worker_id = heartbeat["worker_id"]
        metrics.set_gauge(f"worker.{worker_id}.queue_depth", heartbeat["queue_depth"])

    mcp_summary = status["mcp_tool_observability"]
    metrics.set_gauge("mcp.tool.total_calls", mcp_summary["total_calls"])
    metrics.set_gauge("mcp.tool.error_count", mcp_summary["error_count"])
    for tool in mcp_summary["tools"]:
        tool_name = tool["tool_name"]
        metrics.set_gauge(f"mcp.tool.{tool_name}.avg_latency_ms", tool["avg_latency_ms"])


def _record_ingest_policy_metrics(metrics: Metrics, report: IngestPolicyReport) -> None:
    if report.payloads_omitted:
        metrics.increment("ingest.payloads_omitted", report.payloads_omitted)
        metrics.increment("ingest.payload_bytes_omitted", report.payload_bytes_omitted)
    if report.events_omitted:
        metrics.increment("ingest.events_omitted", report.events_omitted)
    if report.stream_events_omitted:
        metrics.increment("ingest.stream_events_omitted", report.stream_events_omitted)


def _behavior_backtest_evidence_ids(result: dict[str, Any]) -> list[str]:
    evidence_ids: list[str] = []
    for example in result.get("positive_examples", []):
        evidence_ids.append(example["trace_id"])
        evidence_ids.extend(example.get("evidence_span_ids", []))
    return sorted(set(evidence_ids))


def _eval_judges_from_request(store: SQLiteStore, request: dict[str, Any]) -> list[dict[str, Any]]:
    judges = [dict(judge) for judge in request.get("judges", [])]
    for judge_id in request.get("judge_ids", []):
        judge = store.get_judge(request["project_id"], judge_id)
        if judge is None or not judge.get("versions"):
            raise HTTPException(
                status_code=404,
                detail=_error("not_found", f"Judge not found or has no versions: {judge_id}"),
            )
        version = judge["versions"][0]
        definition = dict(version["definition"])
        definition.setdefault("judge_id", judge["judge_id"])
        definition.setdefault("judge_version_id", version["judge_version_id"])
        definition.setdefault("project_id", judge["project_id"])
        definition.setdefault("name", judge["name"])
        definition.setdefault("description", judge.get("description"))
        definition.setdefault("judge_type", judge["judge_type"])
        judges.append(definition)
    return judges


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_screenshot_intake_evidence(request: dict[str, Any]) -> dict[str, object]:
    attachments_raw = request.get("attachments") or []
    if not isinstance(attachments_raw, list):
        raise SchemaValidationFailure(
            "schema_validation_failed",
            "attachments must be an array",
            "/attachments",
        )

    source_payloads: list[dict[str, object]] = []
    text_sources: list[dict[str, str]] = []
    payload_ids: list[str] = []

    def add_payload(
        *,
        payload_id: str | None,
        source: str,
        content_type: str | None,
        index: int | None = None,
    ) -> None:
        if payload_id is None or payload_id in payload_ids:
            return
        payload_ids.append(payload_id)
        source_payloads.append(
            {
                "payload_id": payload_id,
                "source": source,
                "content_type": content_type or "unknown",
                "index": index,
            }
        )

    def add_text(source: str, field: str, value: Any, payload_id: str | None = None) -> None:
        text = _text_or_none(value)
        if text is None:
            return
        text_sources.append(
            {
                "source": source,
                "field": field,
                "text": text,
                "payload_id": payload_id or "",
            }
        )

    screenshot_payload_id = _text_or_none(request.get("screenshot_payload_id_nullable"))
    add_payload(
        payload_id=screenshot_payload_id,
        source="screenshot",
        content_type=_text_or_none(request.get("screenshot_content_type")) or "image/*",
    )
    add_text("issue_report", "title", request.get("title"))
    add_text("issue_report", "description", request.get("description"))
    add_text("issue_report", "reporter_text", request.get("reporter_text"))
    add_text("screenshot", "extracted_text", request.get("extracted_text"), screenshot_payload_id)

    for index, attachment_raw in enumerate(attachments_raw):
        if not isinstance(attachment_raw, dict):
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "attachments entries must be objects",
                f"/attachments/{index}",
            )
        payload_id = _text_or_none(attachment_raw.get("payload_id") or attachment_raw.get("id"))
        content_type = _text_or_none(attachment_raw.get("content_type"))
        add_payload(
            payload_id=payload_id,
            source=_text_or_none(attachment_raw.get("source")) or "attachment",
            content_type=content_type,
            index=index,
        )
        for field in ("filename", "name", "extracted_text", "text", "content_text", "summary"):
            add_text("attachment", field, attachment_raw.get(field), payload_id)

    seen_text: set[str] = set()
    query_parts: list[str] = []
    for source in text_sources:
        text = source["text"]
        if text in seen_text:
            continue
        seen_text.add(text)
        query_parts.append(text)

    return {
        "screenshot_payload_id": screenshot_payload_id,
        "attachment_payload_ids": payload_ids,
        "source_payloads": source_payloads,
        "text_sources": text_sources,
        "query": " ".join(query_parts),
        "source_counts": {
            "payloads": len(source_payloads),
            "attachments": len(attachments_raw),
            "text_sources": len(text_sources),
        },
    }


def _link_screenshot_intake_payloads(
    store: SQLiteStore,
    issue: dict[str, Any],
    intake_evidence: dict[str, object],
) -> None:
    source_payloads = intake_evidence.get("source_payloads")
    if not isinstance(source_payloads, list):
        return
    for source_payload in source_payloads:
        if not isinstance(source_payload, dict):
            continue
        payload_id = _text_or_none(source_payload.get("payload_id"))
        if payload_id is None:
            continue
        source = _text_or_none(source_payload.get("source")) or "attachment"
        relation = "screenshot_payload" if source == "screenshot" else "source_attachment"
        store.create_issue_link(
            {
                "project_id": issue["project_id"],
                "issue_id": issue["issue_id"],
                "target_type": "payload_object",
                "target_id": payload_id,
                "relation": relation,
                "source": "screenshot_intake",
                "metadata": {
                    "source": source,
                    "content_type": source_payload.get("content_type") or "unknown",
                    "index": source_payload.get("index"),
                },
            }
        )


def _screenshot_seed_trace_candidates(
    store: SQLiteStore,
    request: dict[str, Any],
    intake_evidence: dict[str, object],
) -> list[dict[str, object]]:
    project_id = request["project_id"]
    filters = request.get("filters") or {}
    limit = int(request.get("limit", 5))
    text_queries: list[str] = []
    text_sources = intake_evidence.get("text_sources")
    if isinstance(text_sources, list):
        for source in text_sources:
            if not isinstance(source, dict):
                continue
            text = _text_or_none(source.get("text"))
            if text is not None and text not in text_queries:
                text_queries.append(text)
    traces_by_id: dict[str, dict[str, Any]] = {}
    matched_queries_by_trace: dict[str, list[str]] = {}
    for text_query in text_queries:
        for trace in store.search_traces(
            project_id,
            filters=filters,
            full_text_query=text_query,
            limit=limit,
        ):
            trace_id = trace["trace_id"]
            traces_by_id.setdefault(trace_id, trace)
            matched_queries_by_trace.setdefault(trace_id, []).append(text_query)
        if len(traces_by_id) >= limit:
            break
    traces = list(traces_by_id.values())[:limit]
    if not traces and request.get("session_id_hint"):
        traces = store.search_traces(
            project_id,
            filters={"session_id": request["session_id_hint"]},
            limit=limit,
        )
    candidates = []
    for trace in traces:
        reasons = []
        matched_queries = matched_queries_by_trace.get(trace["trace_id"], [])
        if matched_queries:
            reasons.append("matched screenshot or attachment intake text")
        if request.get("session_id_hint") and trace.get("session_id") == request["session_id_hint"]:
            reasons.append("matched session hint")
        candidates.append(
            {
                "trace_id": trace["trace_id"],
                "session_id": trace.get("session_id"),
                "status": trace.get("status"),
                "confidence": "low" if not reasons else "medium",
                "reasons": reasons or ["candidate from structured filters"],
                "matched_queries": matched_queries[:3],
            }
        )
    return candidates


def _create_investigation_review_tasks(
    store: SQLiteStore,
    run: dict[str, Any],
) -> list[dict[str, Any]]:
    project_id = run["project_id"]
    result = run.get("result", {})
    tasks = []
    for index, candidate in enumerate(result.get("suspected_root_causes", [])):
        tasks.append(
            store.create_review_task(
                {
                    "project_id": project_id,
                    "task_type": "root_cause_candidate",
                    "source_entity_type": "investigation_run",
                    "source_entity_id": f"{run['investigation_run_id']}#root_cause:{index}",
                    "evidence_ids": _candidate_evidence_ids(candidate),
                }
            )
        )
    assistance = result.get("model_assistance", {})
    for draft in assistance.get("behavior_drafts", []):
        source_name = draft.get("name") or "behavior_draft"
        tasks.append(
            store.create_review_task(
                {
                    "project_id": project_id,
                    "task_type": "behavior_candidate",
                    "source_entity_type": "investigation_run",
                    "source_entity_id": f"{run['investigation_run_id']}#behavior:{source_name}",
                    "evidence_ids": sorted(
                        set(
                            draft.get("positive_trace_ids", [])
                            + draft.get("negative_trace_ids", [])
                        )
                    ),
                }
            )
        )
    return tasks


def _execute_automation_actions(
    store: SQLiteStore,
    settings: Settings,
    secret_cipher: LocalSecretCipher,
    project_id: str,
    planned_actions: list[dict[str, Any]],
    trace_id: str | None,
) -> list[dict[str, Any]]:
    results = []
    halted = False
    for planned in planned_actions:
        if halted:
            results.append(
                {
                    **planned,
                    "status": "skipped",
                    "reason": "previous action failure stopped execution",
                }
            )
            continue
        result = _execute_automation_action_with_retries(
            store,
            settings,
            secret_cipher,
            project_id,
            planned,
            trace_id,
        )
        results.append(result)
        if _is_action_failure(result):
            behavior = _failure_behavior(planned["action"].get("on_failure"))
            result["partial_failure_behavior"] = behavior
            if behavior != "continue":
                if behavior == "compensate":
                    compensation_results = _execute_compensation_actions(
                        store,
                        settings,
                        secret_cipher,
                        project_id,
                        trace_id,
                        results,
                    )
                    result["compensation_results"] = compensation_results
                    result["compensation_status"] = _compensation_status(
                        compensation_results
                    )
                halted = True
    return results


def _execute_automation_action_with_retries(
    store: SQLiteStore,
    settings: Settings,
    secret_cipher: LocalSecretCipher,
    project_id: str,
    planned: dict[str, Any],
    trace_id: str | None,
) -> dict[str, Any]:
    attempts = _retry_attempts(planned["action"])
    attempt_results = []
    result = planned
    for attempt in range(1, attempts + 1):
        result = _execute_automation_action_once(
            store,
            settings,
            secret_cipher,
            project_id,
            planned,
            trace_id,
        )
        attempt_results.append(
            {
                "attempt": attempt,
                "status": result["status"],
                "reason": result.get("reason"),
            }
        )
        if not _is_action_failure(result):
            break
    result = {**result, "attempts": len(attempt_results), "attempt_results": attempt_results}
    if _is_action_failure(result):
        return {
            **result,
            "status": "dead_lettered",
            "dead_lettered": True,
            "original_status": result["status"],
        }
    return result


def _execute_automation_action_once(
    store: SQLiteStore,
    settings: Settings,
    secret_cipher: LocalSecretCipher,
    project_id: str,
    planned: dict[str, Any],
    trace_id: str | None,
) -> dict[str, Any]:
    try:
        action = planned["action"]
        action_type = planned["type"]
        if action_type == "add_to_dataset":
            if not trace_id or not action.get("dataset_id"):
                return {
                    **planned,
                    "status": "skipped",
                    "reason": "missing trace or dataset",
                }
            example = store.add_trace_to_dataset(
                project_id,
                action["dataset_id"],
                trace_id,
                labels=action.get("labels"),
                created_from="automation",
            )
            return {**planned, "status": "succeeded", "result": example}
        if action_type == "create_review_task":
            task = store.create_review_task(
                {
                    "project_id": project_id,
                    "task_type": action.get("task_type", "behavior_candidate"),
                    "source_entity_type": action.get("source_entity_type", "trace"),
                    "source_entity_id": action.get("source_entity_id") or trace_id or "unknown",
                    "evidence_ids": [trace_id] if trace_id else [],
                    "notes_nullable": action.get("notes"),
                }
            )
            return {**planned, "status": "succeeded", "result": task}
        if action_type == "rollback_review_task":
            review_task_id = _rollback_review_task_id(planned)
            if review_task_id is None:
                return {
                    **planned,
                    "status": "skipped",
                    "reason": "missing review task to roll back",
                }
            task = store.update_review_task(
                project_id,
                review_task_id,
                {
                    "status": "resolved",
                    "decision": action.get("decision", "rolled_back_by_automation"),
                    "notes": action.get("notes")
                    or (
                        "Rolled back by automation compensation for "
                        f"{planned.get('idempotency_key')}."
                    ),
                },
            )
            return {
                **planned,
                "status": "succeeded",
                "result": task,
                "rollback": {
                    "target_type": "review_task",
                    "target_id": review_task_id,
                    "status": task["status"],
                    "decision": task["decision_nullable"],
                },
            }
        if action_type == "send_notification":
            return _execute_notification_action(
                store,
                settings,
                secret_cipher,
                project_id,
                planned,
                trace_id,
            )
        return {**planned, "status": "unsupported", "reason": "unsupported action type"}
    except (KeyError, ValueError, RuntimeError) as exc:
        return {**planned, "status": "failed", "reason": str(exc)}


def _execute_compensation_actions(
    store: SQLiteStore,
    settings: Settings,
    secret_cipher: LocalSecretCipher,
    project_id: str,
    trace_id: str | None,
    action_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results = []
    for planned in _planned_compensation_actions(action_results):
        results.append(
            _execute_automation_action_with_retries(
                store,
                settings,
                secret_cipher,
                project_id,
                planned,
                trace_id,
            )
        )
    return results


def _planned_compensation_actions(action_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    for result in reversed(action_results):
        action = result.get("action") if isinstance(result.get("action"), dict) else {}
        for offset, compensation in enumerate(_compensation_actions(action)):
            if not isinstance(compensation, dict):
                continue
            source_index = result.get("index")
            planned.append(
                {
                    "index": f"compensate:{source_index}:{offset}",
                    "type": compensation.get("type"),
                    "status": "planned",
                    "idempotency_key": (
                        f"{result.get('idempotency_key')}:compensation:{offset}"
                    ),
                    "action": compensation,
                    "compensates_action_index": source_index,
                    "compensates_result": {
                        "status": result.get("status"),
                        "result": result.get("result"),
                    },
                }
            )
    return planned


def _compensation_actions(action: dict[str, Any]) -> list[dict[str, Any]]:
    value = (
        action.get("compensation_actions")
        or action.get("compensate_with")
        or action.get("compensation")
        or []
    )
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _compensation_status(results: list[dict[str, Any]]) -> str:
    if not results:
        return "not_configured"
    if any(_is_action_failure(result) for result in results):
        return "partial_failure"
    return "succeeded"


def _rollback_review_task_id(planned: dict[str, Any]) -> str | None:
    action = planned.get("action") if isinstance(planned.get("action"), dict) else {}
    explicit = action.get("review_task_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    compensated = planned.get("compensates_result")
    if not isinstance(compensated, dict):
        return None
    result = compensated.get("result")
    if not isinstance(result, dict):
        return None
    review_task_id = result.get("review_task_id")
    return review_task_id if isinstance(review_task_id, str) and review_task_id else None


def _execute_notification_action(
    store: SQLiteStore,
    settings: Settings,
    secret_cipher: LocalSecretCipher,
    project_id: str,
    planned: dict[str, Any],
    trace_id: str | None,
) -> dict[str, Any]:
    action = planned["action"]
    target_id = action.get("target_id")
    target = (
        store.get_notification_target(project_id, target_id)
        if isinstance(target_id, str)
        else None
    )
    if target is None:
        return {**planned, "status": "failed", "reason": "target not found"}
    group_key = action.get("group_key") or f"{project_id}:{target_id}:{trace_id or 'none'}"
    metadata = {
        "trace_id": trace_id,
        "message": action.get("message"),
        "group_key": group_key,
        "delivery_mode": action.get("delivery_mode", "preview"),
    }
    if action.get("delivery_mode") != "live":
        audit_id = store.append_audit(
            "preview_notification",
            "notification_target",
            project_id,
            target_id,
            metadata,
        )
        return {
            **planned,
            "status": "succeeded",
            "delivery_status": "preview_only",
            "group_key": group_key,
            "audit_id": audit_id,
        }
    if not settings.enable_external_notifications:
        return {
            **planned,
            "status": "failed",
            "delivery_status": "blocked",
            "reason": "external notifications are disabled",
            "group_key": group_key,
        }
    if target["type"] != "webhook":
        return {
            **planned,
            "status": "failed",
            "delivery_status": "unsupported_target_type",
            "reason": "live delivery currently supports webhook targets",
            "group_key": group_key,
        }
    secret_ref = _notification_secret_ref(target)
    if secret_ref is None:
        return {
            **planned,
            "status": "failed",
            "delivery_status": "missing_secret_ref",
            "reason": "webhook target has no secret ref",
            "group_key": group_key,
        }
    try:
        webhook_url = _resolve_notification_secret(store, secret_cipher, project_id, secret_ref)
    except (KeyError, SecretDecryptionError) as exc:
        return {
            **planned,
            "status": "failed",
            "delivery_status": "secret_unavailable",
            "reason": str(exc),
            "group_key": group_key,
        }
    payload = {
        "project_id": project_id,
        "target_id": target_id,
        "trace_id": trace_id,
        "message": action.get("message"),
        "group_key": group_key,
    }
    try:
        response = httpx.post(webhook_url, json=payload, timeout=10.0)
    except httpx.HTTPError as exc:
        return {
            **planned,
            "status": "failed",
            "delivery_status": "transport_error",
            "reason": str(exc),
            "group_key": group_key,
        }
    audit_id = store.append_audit(
        "deliver_notification",
        "notification_target",
        project_id,
        target_id,
        {**metadata, "http_status": response.status_code},
    )
    if response.status_code >= 400:
        return {
            **planned,
            "status": "failed",
            "delivery_status": "http_error",
            "http_status": response.status_code,
            "group_key": group_key,
            "audit_id": audit_id,
        }
    return {
        **planned,
        "status": "succeeded",
        "delivery_status": "delivered",
        "http_status": response.status_code,
        "group_key": group_key,
        "audit_id": audit_id,
    }


def _automation_run_status(action_results: list[dict[str, Any]]) -> str:
    if not action_results:
        return "succeeded"
    failures = [result for result in action_results if _is_action_failure(result)]
    successes = [result for result in action_results if result.get("status") == "succeeded"]
    if failures and successes:
        return "partial_failure"
    if failures:
        return "dead_lettered"
    return "succeeded"


def _is_action_failure(result: dict[str, Any]) -> bool:
    return result.get("status") in {"failed", "unsupported", "dead_lettered"}


def _retry_attempts(action: dict[str, Any]) -> int:
    retry = action.get("retry") or {}
    try:
        attempts = int(retry.get("attempts", 1))
    except (TypeError, ValueError):
        attempts = 1
    return min(max(attempts, 1), 5)


def _failure_behavior(value: Any) -> str:
    if value in {"continue", "compensate"}:
        return str(value)
    return "stop"


def _notification_secret_ref(target: dict[str, Any]) -> str | None:
    refs = target.get("config_secret_refs") or []
    if not refs:
        return None
    first = refs[0]
    return first if isinstance(first, str) else None


def _resolve_notification_secret(
    store: SQLiteStore,
    secret_cipher: LocalSecretCipher,
    project_id: str,
    secret_ref: str,
) -> str:
    secret = store.get_secret_ref(project_id, secret_ref, include_ciphertext=True)
    if secret is None:
        raise KeyError(f"secret ref not found: {secret_ref}")
    return secret_cipher.decrypt(str(secret["ciphertext"]))


def _validate_notification_target_request(request: dict[str, Any]) -> None:
    if "config" in request or "credentials" in request:
        raise SchemaValidationFailure(
            "schema_validation_failed",
            "Notification target configs must use config_secret_refs, not plaintext config.",
            "/config_secret_refs",
        )
    refs = request.get("config_secret_refs") or []
    if not isinstance(refs, list):
        raise SchemaValidationFailure(
            "schema_validation_failed",
            "config_secret_refs must be a list of secret references.",
            "/config_secret_refs",
        )
    if request.get("status", "active") == "active" and not refs:
        raise SchemaValidationFailure(
            "schema_validation_failed",
            "Active notification targets require at least one config_secret_ref.",
            "/config_secret_refs",
        )
    for index, ref in enumerate(refs):
        if not isinstance(ref, str) or not _looks_like_secret_ref(ref):
            raise SchemaValidationFailure(
                "schema_validation_failed",
                "Notification target config entries must be secret refs.",
                f"/config_secret_refs/{index}",
            )


def _looks_like_secret_ref(value: str) -> bool:
    return value.startswith(("secret_", "secret:", "secret://"))


def _candidate_evidence_ids(candidate: dict[str, Any]) -> list[str]:
    return sorted(
        set(
            candidate.get("evidence_trace_ids", [])
            + candidate.get("evidence_span_ids", [])
        )
    )


def _deterministic_context_pack_content(
    issue: dict[str, Any] | None,
    traces: list[dict[str, Any]],
    spans_by_trace: dict[str, list[dict[str, Any]]],
    source_trace_ids: list[str],
) -> dict[str, object]:
    return {
        "issue": issue,
        "source_trace_ids": source_trace_ids,
        "summary": {
            "issue_summary": issue.get("title") if issue else "No issue supplied.",
            "trace_summaries": [
                {
                    "trace_id": trace["trace_id"],
                    "summary": trace.get("summary") or trace["trace_id"],
                    "evidence_span_ids": [
                        span["span_id"] for span in spans_by_trace[trace["trace_id"]]
                    ][:3],
                }
                for trace in traces
            ],
            "uncertainty": "Model provider unavailable.",
        },
        "model_metadata": {"status": "model_unavailable"},
    }


def _error(
    code: str,
    message: str,
    path: str | None = None,
    retryable: bool = False,
) -> dict[str, dict[str, object | str | bool | None]]:
    return {
        "error": {
            "code": code,
            "message": message,
            "path": path,
            "request_id": new_id("req"),
            "retryable": retryable,
        }
    }


app = create_app()
