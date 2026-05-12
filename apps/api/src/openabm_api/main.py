from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from openabm_api.auth import require_api_key
from openabm_api.ids import new_id
from openabm_api.metrics import Metrics
from openabm_api.reconstruction import reconstruct_trace
from openabm_api.schemas import SchemaValidationFailure, validate_payload
from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    metrics = Metrics()

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

    def auth_dependency(scopes: list[str]) -> Callable[[str | None], dict[str, object]]:
        def dependency(authorization: str | None = Header(default=None)) -> dict[str, object]:
            return require_api_key(settings, scopes, authorization)

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
        return metrics.render_text()

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

        status = "success" if rejected == 0 else "partial_success" if accepted else "failed"
        metrics.increment("ingest.batch")
        return {"status": status, "accepted": accepted, "rejected": rejected, "items": items}

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
    def search_similar(
        request: dict[str, Any],
        actor: dict[str, object] = Depends(auth_dependency(["traces:read"])),
    ) -> dict[str, object]:
        del actor
        return {
            "data": [],
            "disabled": True,
            "reason": "Similarity search is deferred until embeddings are enabled.",
            "representation_version": None,
            "request": request,
            "page": {
                "limit": int(request.get("limit", 20)),
                "next_cursor": None,
                "has_more": False,
            },
        }

    @app.get("/api/scores")
    def list_scores(
        project_id: str,
        trace_id: str | None = None,
        actor: dict[str, object] = Depends(auth_dependency(["scores:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_scores(project_id, trace_id=trace_id)}

    @app.get("/api/behaviors")
    def list_behaviors(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["behaviors:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_behaviors(project_id)}

    return app


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
