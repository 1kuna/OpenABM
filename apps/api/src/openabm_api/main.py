from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
from openabm_worker.grounding import (
    claims_from_text,
    evaluate_grounding_claims,
    extract_grounding_claims_with_model,
)
from openabm_worker.investigation import assist_investigation
from openabm_worker.judge_drafts import draft_judge_from_request
from openabm_worker.judges import run_rubric_judge
from openabm_worker.model_runtime import (
    ModelCallsDisabled,
    ModelConfigurationError,
    model_provider_from_settings,
)
from openabm_worker.novelty import detect_novel_behavior_candidates
from openabm_worker.offline_eval import run_eval
from openabm_worker.similarity import rank_similar_traces

from openabm_api.auth import require_api_key
from openabm_api.classification import classify_payload, normalize_classification, redact_if_needed
from openabm_api.docs_search import search_public_docs
from openabm_api.ids import new_id
from openabm_api.metrics import Metrics
from openabm_api.prompts import render_prompt
from openabm_api.reconstruction import reconstruct_trace
from openabm_api.schemas import SchemaValidationFailure, validate_payload
from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore
from openabm_api.time import utc_now


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
            provider = model_provider_from_settings(settings)
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
                provider = model_provider_from_settings(settings)
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
            provider = model_provider_from_settings(settings)
        except ModelConfigurationError as exc:
            raise HTTPException(
                status_code=503,
                detail=_error("model_unavailable", str(exc), retryable=True),
            ) from exc
        spans = store.list_spans(request["project_id"], request["trace_id"])
        score = await run_rubric_judge(
            provider,
            trace,
            spans,
            request["judge"],
            token_budget=settings.max_trace_tokens_for_judge,
        )
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
        return example

    @app.get("/api/evals")
    def list_eval_runs(
        project_id: str,
        actor: dict[str, object] = Depends(auth_dependency(["evals:read"])),
    ) -> dict[str, object]:
        del actor
        return {"data": store.list_eval_runs(project_id)}

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
                provider = model_provider_from_settings(settings)
            except ModelConfigurationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error("model_unavailable", str(exc), retryable=True),
                ) from exc
        try:
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
            )
        except ModelCallsDisabled as exc:
            raise HTTPException(
                status_code=503,
                detail=_error("model_unavailable", str(exc), retryable=True),
            ) from exc
        store.append_audit(
            "run_eval",
            "eval_run",
            request["project_id"],
            run["eval_run_id"],
            {"dataset_version_id": request["dataset_version_id"]},
        )
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
            comparison = store.compare_eval_runs(
                request["project_id"],
                request["baseline_eval_run_id"],
                request["candidate_eval_run_id"],
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_error("not_found", str(exc))) from exc
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
        candidates = _screenshot_seed_trace_candidates(store, request)
        store.append_audit(
            "create_issue_from_screenshot",
            "issue",
            request["project_id"],
            issue["issue_id"],
            {"candidate_trace_ids": [candidate["trace_id"] for candidate in candidates]},
        )
        return {**issue, "candidate_seed_traces": candidates}

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
            action_results = _execute_automation_actions(store, project_id, planned, trace_id)
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
            provider = model_provider_from_settings(settings)
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
        except ModelConfigurationError:
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
        run = store.start_investigation(request)
        try:
            provider = model_provider_from_settings(settings)
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
                provider = model_provider_from_settings(settings)
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
    def create_novelty_run(
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


def _screenshot_seed_trace_candidates(
    store: SQLiteStore,
    request: dict[str, Any],
) -> list[dict[str, object]]:
    project_id = request["project_id"]
    query = request.get("extracted_text") or request.get("reporter_text") or request.get("title")
    filters = request.get("filters") or {}
    traces = store.search_traces(
        project_id,
        filters=filters,
        full_text_query=query,
        limit=int(request.get("limit", 5)),
    )
    if not traces and request.get("session_id_hint"):
        traces = store.search_traces(
            project_id,
            filters={"session_id": request["session_id_hint"]},
            limit=int(request.get("limit", 5)),
        )
    candidates = []
    for trace in traces:
        reasons = []
        if query:
            reasons.append("matched extracted text or reporter text")
        if request.get("session_id_hint") and trace.get("session_id") == request["session_id_hint"]:
            reasons.append("matched session hint")
        candidates.append(
            {
                "trace_id": trace["trace_id"],
                "session_id": trace.get("session_id"),
                "status": trace.get("status"),
                "confidence": "low" if not reasons else "medium",
                "reasons": reasons or ["candidate from structured filters"],
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
        result = _execute_automation_action_with_retries(store, project_id, planned, trace_id)
        results.append(result)
        if _is_action_failure(result):
            behavior = _failure_behavior(planned["action"].get("on_failure"))
            result["partial_failure_behavior"] = behavior
            if behavior != "continue":
                if behavior == "compensate":
                    result["compensation_status"] = "not_configured"
                halted = True
    return results


def _execute_automation_action_with_retries(
    store: SQLiteStore,
    project_id: str,
    planned: dict[str, Any],
    trace_id: str | None,
) -> dict[str, Any]:
    attempts = _retry_attempts(planned["action"])
    attempt_results = []
    result = planned
    for attempt in range(1, attempts + 1):
        result = _execute_automation_action_once(store, project_id, planned, trace_id)
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
        if action_type == "send_notification":
            target_id = action.get("target_id")
            target = (
                store.get_notification_target(project_id, target_id)
                if isinstance(target_id, str)
                else None
            )
            if target is None:
                return {**planned, "status": "failed", "reason": "target not found"}
            audit_id = store.append_audit(
                "preview_notification",
                "notification_target",
                project_id,
                target_id,
                {"trace_id": trace_id, "message": action.get("message")},
            )
            return {
                **planned,
                "status": "succeeded",
                "delivery_status": "preview_only",
                "audit_id": audit_id,
            }
        return {**planned, "status": "unsupported", "reason": "unsupported action type"}
    except (KeyError, ValueError, RuntimeError) as exc:
        return {**planned, "status": "failed", "reason": str(exc)}


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
