import base64
import copy
import io
import json
import subprocess
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from openabm_api.main import create_app
from openabm_api.settings import Settings
from openabm_mcp.handlers import call_tool, read_resource
from openabm_worker.offline_eval import run_deterministic_eval

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"


def _pdf_base64(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 24 Tf 100 700 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R "
            b"/Resources << /Font << /F1 4 0 R >> >> "
            b"/MediaBox [0 0 612 792] /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode())
        output.write(obj)
        output.write(b"\nendobj\n")
    xref_offset = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode())
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return base64.b64encode(output.getvalue()).decode("ascii")


def _docx_base64(text: str) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                f"{text}"
                "</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _xlsx_base64(text: str) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            (
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<si><t>{text}</t></si>"
                "</sst>"
            ),
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetData><row><c t="s"><v>0</v></c></row></sheetData>'
                "</worksheet>"
            ),
        )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _pptx_base64(text: str) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t>"
                "</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
            ),
        )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer dev-openabm-key"}


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}")
    return TestClient(create_app(settings))


def make_client_with_settings(tmp_path: Path, **overrides) -> TestClient:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}", **overrides)
    return TestClient(create_app(settings))


def test_cors_origins_are_configurable_for_deployment(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        cors_origins=("http://localhost:8080",),
    )
    client = TestClient(create_app(settings))

    response = client.options(
        "/v1/projects",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"


def test_batch_ingest_and_trace_detail(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = copy.deepcopy(json.loads(FIXTURE_PATH.read_text())["fixtures"][0])
    fixture["spans"][0]["resource"] = {
        "service.name": "support-agent",
        "telemetry.sdk.name": "fixture",
    }
    response = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    assert response.status_code == 207
    assert response.json()["accepted"] == 1 + len(fixture["spans"])

    detail = client.get(
        f"/v1/traces/{fixture['trace']['trace_id']}",
        params={"project_id": fixture["trace"]["project_id"]},
        headers=auth_headers(),
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["trace"]["trace_id"] == fixture["trace"]["trace_id"]
    assert body["reconstruction"]["span_tree"][0]["span"]["span_id"] == "span_happy_root"
    assert body["reconstruction"]["span_tree"][0]["span"]["resource"]["service.name"] == (
        "support-agent"
    )

    session = client.get(
        f"/v1/sessions/{fixture['trace']['session_id']}",
        params={"project_id": fixture["trace"]["project_id"]},
        headers=auth_headers(),
    )
    assert session.status_code == 200
    assert fixture["trace"]["trace_id"] in session.json()["trace_ids"]


def test_auth_contract_api_keys_roles_sessions_and_revocation(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path)

    contract = client.get("/v1/auth/contract")
    assert contract.status_code == 200
    assert contract.json()["password_or_passwordless_decision"] == "passwordless_first"
    assert contract.json()["invites"]["delivery"] == "local_outbox"
    assert contract.json()["invites"]["optional_delivery_adapters"] == ["smtp"]
    assert "viewer" in contract.json()["role_matrix"]

    me = client.get("/v1/auth/me", headers=auth_headers())
    assert me.status_code == 200
    assert me.json()["actor"]["role"] == "owner"

    user = client.post(
        "/v1/auth/users",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "email": "dev@example.com",
            "display_name": "Dev User",
            "role": "developer",
        },
    )
    assert user.status_code == 201
    user_id = user.json()["user_id"]
    assert user.json()["membership"]["role"] == "developer"

    invite = client.post(
        "/v1/auth/invites",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "email": "viewer@example.com", "role": "viewer"},
    )
    assert invite.status_code == 201
    invite_body = invite.json()
    assert invite_body["status"] == "pending"
    assert invite_body["delivery"]["delivery_channel"] == "local_outbox"
    assert invite_body["delivery"]["delivery_status"] == "queued"
    assert invite_body["delivery"]["recipient_email"] == "viewer@example.com"
    assert invite_body["delivery"]["payload"]["template"] == "auth_invite_v1"
    assert invite_body["delivery"]["payload"]["invite_id"] == invite_body["invite_id"]

    invite_deliveries = client.get(
        "/v1/auth/invite-deliveries",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert invite_deliveries.status_code == 200
    assert invite_deliveries.json()["data"][0]["invite_id"] == invite_body["invite_id"]
    assert invite_deliveries.json()["data"][0]["delivery_status"] == "queued"

    invites = client.get(
        "/v1/auth/invites",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert invites.status_code == 200
    assert invites.json()["data"][0]["delivery"]["invite_delivery_id"] == invite_body["delivery"][
        "invite_delivery_id"
    ]

    smtp_messages: list[dict[str, object]] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout
            self.started_tls = False
            self.logins: list[tuple[str, str]] = []

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self) -> None:
            self.started_tls = True

        def login(self, username: str, password: str) -> None:
            self.logins.append((username, password))

        def send_message(self, message) -> None:
            smtp_messages.append(
                {
                    "host": self.host,
                    "port": self.port,
                    "timeout": self.timeout,
                    "started_tls": self.started_tls,
                    "logins": self.logins,
                    "message": message,
                }
            )

    monkeypatch.setattr("openabm_api.main.smtplib.SMTP", FakeSMTP)

    smtp_client = make_client_with_settings(
        tmp_path,
        enable_smtp_invites=True,
        smtp_host="smtp.example.test",
        smtp_port=2525,
        smtp_username="mailer",
        smtp_password="smtp-secret",
        smtp_from_email="noreply@example.test",
        smtp_timeout_seconds=12.5,
    )
    smtp_invite = smtp_client.post(
        "/v1/auth/invites",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "email": "smtp-viewer@example.com", "role": "viewer"},
    )
    assert smtp_invite.status_code == 201
    smtp_body = smtp_invite.json()
    assert smtp_body["delivery"]["delivery_channel"] == "smtp"
    assert smtp_body["delivery"]["delivery_status"] == "sent"
    assert smtp_body["delivery"]["error_nullable"] is None
    assert "smtp-secret" not in json.dumps(smtp_body)
    assert len(smtp_messages) == 1
    smtp_record = smtp_messages[0]
    assert smtp_record["host"] == "smtp.example.test"
    assert smtp_record["port"] == 2525
    assert smtp_record["timeout"] == 12.5
    assert smtp_record["started_tls"] is True
    assert smtp_record["logins"] == [("mailer", "smtp-secret")]
    message = smtp_record["message"]
    assert message["From"] == "noreply@example.test"
    assert message["To"] == "smtp-viewer@example.com"
    assert message["Subject"] == "OpenABM invite for proj_demo"
    assert "Invite ID:" in message.get_content()

    missing_config_client = make_client_with_settings(
        tmp_path,
        enable_smtp_invites=True,
        smtp_from_email="noreply@example.test",
    )
    failed_invite = missing_config_client.post(
        "/v1/auth/invites",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "email": "blocked-viewer@example.com", "role": "viewer"},
    )
    assert failed_invite.status_code == 201
    failed_body = failed_invite.json()
    assert failed_body["delivery"]["delivery_channel"] == "smtp"
    assert failed_body["delivery"]["delivery_status"] == "failed"
    assert "OPENABM_SMTP_HOST" in failed_body["delivery"]["error_nullable"]
    assert len(smtp_messages) == 1

    session = client.post(
        "/v1/auth/sessions",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "user_id": user_id},
    )
    assert session.status_code == 201
    assert session.json()["session_token"].startswith("opabm_sess_")
    sessions = client.get(
        "/v1/auth/sessions",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert sessions.status_code == 200
    assert "session_token" not in sessions.json()["data"][0]

    viewer_key = client.post(
        "/v1/auth/api-keys",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "Viewer key",
            "role": "viewer",
            "scopes": ["*"],
        },
    )
    assert viewer_key.status_code == 201
    viewer_headers = {"Authorization": f"Bearer {viewer_key.json()['api_key']}"}

    projects = client.get("/v1/projects", headers=viewer_headers)
    assert projects.status_code == 200
    forbidden = client.post(
        "/v1/auth/api-keys",
        headers=viewer_headers,
        json={"project_id": "proj_demo", "name": "Bad key", "role": "admin"},
    )
    assert forbidden.status_code == 403

    revoked = client.post(
        f"/v1/auth/api-keys/{viewer_key.json()['api_key_id']}/revoke",
        headers=auth_headers(),
        json={"project_id": "proj_demo"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    rejected = client.get("/v1/projects", headers=viewer_headers)
    assert rejected.status_code == 401


def test_secret_refs_are_encrypted_redacted_rotatable_and_audited(tmp_path) -> None:
    client = make_client(tmp_path)

    backend = client.get("/v1/secrets/backend", headers=auth_headers())
    assert backend.status_code == 200
    assert backend.json()["local_development_secret_mode"]["status"] == "implemented"
    assert backend.json()["plaintext_storage"] is False

    created = client.post(
        "/v1/secrets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "secret_ref": "secret_test_webhook",
            "purpose": "notification_webhook",
            "value": "https://example.invalid/private-token",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["secret_ref"] == "secret_test_webhook"
    assert body["current_version"] == 1
    assert "value" not in body
    assert "ciphertext" not in body
    assert "private-token" not in json.dumps(body)

    listed = client.get(
        "/v1/secrets",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert listed.status_code == 200
    assert "private-token" not in json.dumps(listed.json())
    assert listed.json()["data"][0]["redacted_value"] == "secret://redacted"

    resolved = client.post(
        "/v1/secrets/secret_test_webhook/resolve",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "purpose": "local qa"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["value"].endswith("private-token")
    assert resolved.json()["access_audit_id"].startswith("secret_access_")

    rotated = client.post(
        "/v1/secrets/secret_test_webhook/rotate",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "value": "rotated-secret-value",
        },
    )
    assert rotated.status_code == 200
    assert rotated.json()["current_version"] == 2
    assert "rotated-secret-value" not in json.dumps(rotated.json())

    resolved_after_rotate = client.post(
        "/v1/secrets/secret_test_webhook/resolve",
        headers=auth_headers(),
        json={"project_id": "proj_demo"},
    )
    assert resolved_after_rotate.status_code == 200
    assert resolved_after_rotate.json()["value"] == "rotated-secret-value"

    access_log = client.get(
        "/v1/secrets/secret_test_webhook/access-log",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert access_log.status_code == 200
    actions = {item["action"] for item in access_log.json()["data"]}
    assert {"create", "resolve", "rotate"} <= actions


def test_observability_status_metrics_dead_letters_and_heartbeats(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][0]
    trace_id = fixture["trace"]["trace_id"]
    ingest = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    assert ingest.status_code == 207

    heartbeat = client.post(
        "/v1/ops/worker-heartbeats",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "worker_id": "pytest-worker",
            "worker_type": "integration",
            "status": "ok",
            "queue_depth": 3,
            "details": {"test": "observability"},
        },
    )
    assert heartbeat.status_code == 201
    assert heartbeat.json()["queue_depth"] == 3
    mcp_observation = client.post(
        "/v1/ops/mcp-tool-observations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "tool_name": "get_trace",
            "status": "succeeded",
            "latency_ms": 12,
            "request": {"trace_id": trace_id},
            "response": {"trace": {"trace_id": trace_id}},
            "citations": [trace_id],
        },
    )
    assert mcp_observation.status_code == 201
    assert mcp_observation.json()["confirmation_required"] is False

    status = client.get(
        "/v1/ops/status",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert status.status_code == 200
    body = status.json()
    assert body["storage_growth"]["trace_metadata"] == 1
    assert body["storage_growth"]["trace_spans"] == len(fixture["spans"])
    assert body["queue_depth"]["worker_jobs"] == 3
    assert body["worker_heartbeats"][0]["worker_id"] == "pytest-worker"
    assert body["worker_health"][0]["status"] == "healthy"
    assert body["stale_worker_count"] == 0
    assert body["mcp_tool_observability"]["total_calls"] == 1
    assert body["mcp_tool_observability"]["tools"][0]["tool_name"] == "get_trace"
    assert "metrics" in body
    with client.app.state.store.connect() as conn:
        conn.execute(
            "UPDATE worker_heartbeats SET last_seen_at = ? WHERE worker_id = ?",
            ("2000-01-01T00:00:00+00:00", "pytest-worker"),
        )
    stale_status = client.get(
        "/v1/ops/status",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert stale_status.json()["worker_health"][0]["status"] == "stale"
    assert stale_status.json()["stale_worker_count"] == 1
    observations = client.get(
        "/v1/ops/mcp-tool-observations",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert observations.status_code == 200
    assert observations.json()["data"][0]["tool_name"] == "get_trace"
    assert observations.json()["data"][0]["request"]["trace_id"] == trace_id
    assert observations.json()["data"][0]["citations"] == [trace_id]

    dead_letters = client.get(
        "/v1/ops/dead-letter",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert dead_letters.status_code == 200
    assert dead_letters.json()["data"] == []

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain; version=0.0.4")
    text = metrics.text
    assert "openabm_api_requests" in text
    assert "openabm_api_request_latency_ms_count" in text
    assert "openabm_storage_trace_metadata_rows 1.0" in text
    assert "openabm_queue_worker_jobs 3.0" in text
    assert "openabm_worker_pytest_worker_queue_depth 3.0" in text


def test_invalid_span_gets_partial_success_rejection(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"spans": [{"span_id": "missing-required-fields"}]},
    )
    assert response.status_code == 207
    body = response.json()
    assert body["status"] == "failed"
    assert body["rejected"] == 1
    assert body["items"][0]["error"]["code"] == "schema_validation_failed"


def test_ingest_batch_applies_visible_payload_and_event_sampling(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        ingest_inline_payload_max_bytes=16,
        ingest_max_events_per_span=3,
        ingest_stream_event_sample_rate=2,
    )
    client = TestClient(create_app(settings))
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][0]
    trace = json.loads(json.dumps(fixture["trace"]))
    span = json.loads(json.dumps(fixture["spans"][0]))
    span["input"] = {"mode": "inline", "value": {"prompt": "x" * 100}, "redaction_state": "raw"}
    span["output"] = {"mode": "inline", "value": {"answer": "y" * 100}, "redaction_state": "raw"}
    span["events"] = [
        {"name": "model.stream.delta", "time": span["started_at"], "attributes": {"index": index}}
        for index in range(8)
    ]

    response = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [trace], "spans": [span]},
    )

    assert response.status_code == 207
    backpressure = response.json()["backpressure"]
    assert backpressure["payloads_omitted"] == 2
    assert backpressure["stream_events_omitted"] == 4
    detail = client.get(
        f"/v1/traces/{trace['trace_id']}",
        params={"project_id": trace["project_id"]},
        headers=auth_headers(),
    )
    stored_span = detail.json()["spans"][0]
    assert stored_span["input"]["mode"] == "omitted"
    assert stored_span["input"]["omission_reason"] == "server_payload_sampling"
    assert stored_span["events"][-1]["name"] == "openabm.events_omitted"


def test_ingest_backpressure_is_retryable_but_preserves_high_priority_trace(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        ingest_retryable_backpressure_items=1,
    )
    client = TestClient(create_app(settings))
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][0]
    trace = json.loads(json.dumps(fixture["trace"]))
    span = json.loads(json.dumps(fixture["spans"][0]))

    rejected = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [trace], "spans": [span]},
    )
    assert rejected.status_code == 429
    assert rejected.json()["detail"]["error"]["code"] == "ingest_backpressure"
    assert rejected.json()["detail"]["error"]["retryable"] is True

    trace["status"] = "error"
    accepted = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [trace], "spans": [span]},
    )
    assert accepted.status_code == 207
    assert accepted.json()["accepted"] == 2
    assert accepted.json()["backpressure"]["high_priority_present"] is True


def test_batch_ingest_accepts_events_feedback_and_payload_metadata(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][0]
    trace = fixture["trace"]
    span = fixture["spans"][0]
    response = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [trace],
            "spans": [span],
            "events": [
                {
                    "client_item_id": "event_1",
                    "project_id": trace["project_id"],
                    "trace_id": trace["trace_id"],
                    "span_id": span["span_id"],
                    "event": {
                        "name": "feedback.received",
                        "time": span["started_at"],
                        "attributes": {"rating": "negative"},
                    },
                }
            ],
            "feedback": [
                {
                    "client_item_id": "feedback_1",
                    "project_id": trace["project_id"],
                    "trace_id": trace["trace_id"],
                    "feedback_type": "thumbs_down",
                }
            ],
            "payloads": [
                {
                    "payload_id": "payload_batch_1",
                    "project_id": trace["project_id"],
                    "trace_id": trace["trace_id"],
                    "span_id": span["span_id"],
                    "content_type": "application/json",
                    "redaction_state": "omitted",
                    "created_at": span["started_at"],
                }
            ],
        },
    )
    assert response.status_code == 207
    assert response.json()["accepted"] == 5
    detail = client.get(
        f"/v1/traces/{trace['trace_id']}",
        params={"project_id": trace["project_id"]},
        headers=auth_headers(),
    )
    stored_events = detail.json()["spans"][0]["events"]
    assert any(event["name"] == "feedback.received" for event in stored_events)


def test_search_similar_fails_closed_without_embeddings(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][2]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    response = client.post(
        "/v1/search/similar",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "source_id": "trace_missing_parent",
            "source_type": "trace",
        },
    )
    assert response.status_code == 200
    assert response.json()["disabled"] is True


def test_search_similar_uses_model_when_configured(tmp_path, monkeypatch) -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "matches": [
                        {
                            "trace_id": "trace_wrong_tool",
                            "similarity_score": 0.91,
                            "rationale": "Both traces are refund support tasks.",
                            "evidence_span_ids": ["span_wrong_tool_order_lookup"],
                        }
                    ],
                    "uncertainty": "fixture-sized candidate set",
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": None,
                "repaired": False,
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixtures = json.loads(FIXTURE_PATH.read_text())["fixtures"][:2]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [fixture["trace"] for fixture in fixtures],
            "spans": [span for fixture in fixtures for span in fixture["spans"]],
        },
    )
    response = client.post(
        "/v1/search/similar",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "source_id": "trace_happy_support",
            "source_type": "trace",
        },
    )
    assert response.status_code == 200
    assert response.json()["disabled"] is False
    assert response.json()["data"][0]["trace_id"] == "trace_wrong_tool"


def test_search_similar_can_use_embedding_representation(tmp_path, monkeypatch) -> None:
    class StubEmbeddingProvider:
        adapter_name = "stub-embedding"
        supported_capabilities = ["embedding"]

        async def embed_documents(self, documents):
            vectors = {}
            for document in documents:
                document_id = document["document_id"]
                if document_id == "source_trace":
                    vectors[document_id] = [1.0, 0.0]
                elif document_id == "trace:trace_wrong_tool":
                    vectors[document_id] = [0.92, 0.08]
                elif document_id == "span:trace_wrong_tool:span_wrong_tool_order_lookup":
                    vectors[document_id] = [0.97, 0.03]
                else:
                    vectors[document_id] = [0.0, 1.0]
            return {
                "status": "succeeded",
                "embeddings": [
                    {
                        "document_id": document["document_id"],
                        "embedding": vectors[document["document_id"]],
                        "index": index,
                    }
                    for index, document in enumerate(documents)
                ],
                "provider": "stub",
                "model": "stub-embed-model",
                "usage": {"total_tokens": len(documents)},
            }

    monkeypatch.setattr(
        "openabm_api.main.embedding_provider_from_settings",
        lambda settings: StubEmbeddingProvider(),
    )
    client = make_client(tmp_path)
    fixtures = json.loads(FIXTURE_PATH.read_text())["fixtures"][:2]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [fixture["trace"] for fixture in fixtures],
            "spans": [span for fixture in fixtures for span in fixture["spans"]],
        },
    )
    response = client.post(
        "/v1/search/similar",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "source_id": "trace_happy_support",
            "source_type": "trace",
            "representation": "embedding",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["disabled"] is False
    assert body["representation_version"] == "embedding_similarity_v1"
    assert body["data"][0]["trace_id"] == "trace_wrong_tool"
    assert body["data"][0]["evidence_span_ids"] == ["span_wrong_tool_order_lookup"]
    assert body["model_metadata"]["model"] == "stub-embed-model"


def test_similarity_index_rebuild_persists_embedding_vectors(tmp_path, monkeypatch) -> None:
    class StubEmbeddingProvider:
        adapter_name = "stub-embedding"
        supported_capabilities = ["embedding"]

        async def embed_documents(self, documents):
            vectors = {}
            for document in documents:
                document_id = document["document_id"]
                if document_id == "trace:trace_happy_support":
                    vectors[document_id] = [1.0, 0.0]
                elif document_id == "trace:trace_wrong_tool":
                    vectors[document_id] = [0.9, 0.1]
                elif document_id == "span:trace_wrong_tool:span_wrong_tool_order_lookup":
                    vectors[document_id] = [0.95, 0.05]
                else:
                    vectors[document_id] = [0.0, 1.0]
            return {
                "status": "succeeded",
                "embeddings": [
                    {
                        "document_id": document["document_id"],
                        "embedding": vectors[document["document_id"]],
                        "index": index,
                    }
                    for index, document in enumerate(documents)
                ],
                "provider": "stub",
                "model": "stub-embed-model",
                "usage": {"total_tokens": len(documents)},
            }

    monkeypatch.setattr(
        "openabm_api.main.embedding_provider_from_settings",
        lambda settings: StubEmbeddingProvider(),
    )
    client = make_client(tmp_path)
    fixtures = json.loads(FIXTURE_PATH.read_text())["fixtures"][:2]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [fixture["trace"] for fixture in fixtures],
            "spans": [span for fixture in fixtures for span in fixture["spans"]],
        },
    )
    rebuild = client.post(
        "/v1/similarity-index/rebuild",
        headers=auth_headers(),
        json={"project_id": "proj_demo"},
    )
    assert rebuild.status_code == 201
    rebuild_body = rebuild.json()
    assert rebuild_body["representation_version"] == "embedding_index_v1:stub-embed-model"
    assert rebuild_body["indexed_counts"]["trace"] == 2
    assert rebuild_body["indexed_counts"]["span"] >= 2

    summary = client.get(
        "/v1/similarity-index",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert summary.status_code == 200
    assert {
        item["entity_type"]: item["count"]
        for item in summary.json()["representations"]
    }["trace"] == 2

    response = client.post(
        "/v1/search/similar",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "source_id": "trace_happy_support",
            "source_type": "trace",
            "representation": "embedding_index",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["disabled"] is False
    assert body["representation_version"] == rebuild_body["representation_version"]
    assert body["data"][0]["trace_id"] == "trace_wrong_tool"
    assert body["data"][0]["evidence_span_ids"] == ["span_wrong_tool_order_lookup"]

    investigation = client.post(
        "/v1/investigations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "seed_trace_id_nullable": "trace_happy_support",
            "limit": 2,
        },
    )
    assert investigation.status_code == 201
    result = investigation.json()["result"]
    assert result["semantic_similarity"]["status"] == "succeeded"
    assert result["semantic_similarity"]["matches"][0]["trace_id"] == "trace_wrong_tool"
    assert result["orchestration"]["semantic_trace_ids"] == ["trace_wrong_tool"]
    assert "semantic similarity" not in result["llm_deferred"]


def test_novelty_run_can_group_candidates_with_similarity_index(tmp_path, monkeypatch) -> None:
    class StubEmbeddingProvider:
        adapter_name = "stub-embedding"
        supported_capabilities = ["embedding"]

        async def embed_documents(self, documents):
            vectors = {}
            for document in documents:
                document_id = document["document_id"]
                if document_id == "trace:trace_wrong_tool":
                    vectors[document_id] = [1.0, 0.0]
                elif document_id == "trace:trace_policy_loop":
                    vectors[document_id] = [0.96, 0.04]
                else:
                    vectors[document_id] = [0.0, 1.0]
            return {
                "status": "succeeded",
                "embeddings": [
                    {
                        "document_id": document["document_id"],
                        "embedding": vectors[document["document_id"]],
                        "index": index,
                    }
                    for index, document in enumerate(documents)
                ],
                "provider": "stub",
                "model": "stub-embed-model",
                "usage": {"total_tokens": len(documents)},
            }

    monkeypatch.setattr(
        "openabm_api.main.embedding_provider_from_settings",
        lambda settings: StubEmbeddingProvider(),
    )
    client = make_client(tmp_path)
    corpus = json.loads(FIXTURE_PATH.read_text())
    happy_fixture = corpus["fixtures"][0]
    source_fixture = corpus["fixtures"][1]
    second_fixture = copy.deepcopy(source_fixture)
    second_fixture["trace"]["trace_id"] = "trace_policy_loop"
    second_fixture["trace"]["session_id"] = "session_policy_loop"
    second_fixture["trace"]["root_span_id"] = "span_policy_loop_root"
    second_fixture["trace"]["summary"] = "Agent looped on policy lookup and failed refund routing."
    span_id_map = {
        span["span_id"]: span["span_id"].replace("wrong_tool", "policy_loop")
        for span in second_fixture["spans"]
    }
    for span in second_fixture["spans"]:
        span["trace_id"] = "trace_policy_loop"
        span["span_id"] = span_id_map[span["span_id"]]
        if span["parent_span_id"] is not None:
            span["parent_span_id"] = span_id_map[span["parent_span_id"]]
        if span.get("attributes", {}).get("error.type") == "wrong_tool":
            span["attributes"]["error.type"] = "policy_loop"
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [happy_fixture["trace"], source_fixture["trace"], second_fixture["trace"]],
            "spans": [
                *happy_fixture["spans"],
                *source_fixture["spans"],
                *second_fixture["spans"],
            ],
        },
    )
    rebuild = client.post(
        "/v1/similarity-index/rebuild",
        headers=auth_headers(),
        json={"project_id": "proj_demo"},
    )
    assert rebuild.status_code == 201
    novelty = client.post(
        "/v1/novelty-runs",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "filters": {"status": "error"},
            "similarity_index_grouping": True,
            "representation_version": rebuild.json()["representation_version"],
            "similarity_threshold": 0.8,
        },
    )
    assert novelty.status_code == 201
    result = novelty.json()["result"]
    assert result["similarity_index_grouping"]["status"] == "succeeded"
    candidate = result["new_behavior_candidates"][0]
    assert set(candidate["source_candidate_names"]) == {
        "error_wrong_tool",
        "error_policy_loop",
    }
    assert candidate["frequency"] == 2
    assert set(candidate["representative_positive_traces"]) == {
        "trace_wrong_tool",
        "trace_policy_loop",
    }
    assert candidate["representative_negative_traces"] == [happy_fixture["trace"]["trace_id"]]
    assert result["negative_example_selection"]["candidate_count_with_negatives"] == 2


def test_trace_can_be_added_to_dataset_with_provenance(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    dataset = client.post(
        "/v1/datasets",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "name": "Refund failures"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["dataset_id"]
    fetched_dataset = client.get(
        f"/v1/datasets/{dataset_id}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched_dataset.status_code == 200

    example = client.post(
        f"/v1/datasets/{dataset_id}/examples/from-trace",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": fixture["trace"]["trace_id"],
            "labels": ["wrong_tool_for_refund"],
        },
    )
    assert example.status_code == 201
    body = example.json()
    assert body["source_trace_id"] == fixture["trace"]["trace_id"]
    assert body["source_span_id"] == fixture["trace"]["root_span_id"]
    assert body["labels"] == ["wrong_tool_for_refund"]


def test_v1_issue_investigation_saved_search_and_classification_flow(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )

    dimension = client.post(
        "/v1/trace-dimensions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "key": "account_id",
            "value": "acct_123",
        },
    )
    assert dimension.status_code == 201

    saved_search = client.post(
        "/v1/saved-searches",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "Refund errors",
            "query": {"filters": {"status": "error"}, "full_text_query": "refund"},
        },
    )
    assert saved_search.status_code == 201

    issue = client.post(
        "/v1/issues",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "title": "Refund workflow uses order lookup",
            "seed_trace_id_nullable": trace_id,
        },
    )
    assert issue.status_code == 201
    fetched_issue = client.get(
        f"/v1/issues/{issue.json()['issue_id']}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched_issue.status_code == 200

    investigation = client.post(
        "/v1/investigations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "issue_id_nullable": issue.json()["issue_id"],
            "seed_trace_id_nullable": trace_id,
            "natural_language_problem_nullable": "refund",
            "filters": {"status": "error"},
        },
    )
    assert investigation.status_code == 201
    investigation_id = investigation.json()["investigation_run_id"]
    fetched_investigation = client.get(
        f"/v1/investigations/{investigation_id}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched_investigation.status_code == 200
    listed_investigations = client.get(
        "/v1/investigations",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert listed_investigations.json()["data"][0]["investigation_run_id"] == investigation_id
    impact = investigation.json()["result"]["impact_report"]
    assert impact["matching_trace_count"] >= 1
    assert impact["affected_entity_count"] == 1
    assert trace_id in impact["representative_trace_ids"]

    policy = client.post(
        "/v1/data-classification-policies",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "default_classification": "internal",
            "rules": [{"path": "customer.email", "classification": "confidential"}],
        },
    )
    assert policy.status_code == 201

    classification = client.post(
        "/v1/data-classification/classify",
        headers=auth_headers(),
        json={
            "payload": {"customer": {"email": "zach@example.com"}},
            "policy": policy.json(),
            "max_classification": "internal",
        },
    )
    assert classification.status_code == 200
    assert classification.json()["classification"] == "confidential"
    assert classification.json()["payload"]["redacted"] is True

    reports = client.get(
        "/v1/impact-reports",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert reports.status_code == 200
    assert reports.json()["data"][0]["matching_trace_count"] >= 1
    fetched_report = client.get(
        f"/v1/impact-reports/{impact['report_id']}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched_report.status_code == 200


def test_v1_eval_runs_are_queryable(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    store = client.app.state.store
    dataset = store.create_dataset("proj_demo", "Refund eval")
    store.add_trace_to_dataset(
        "proj_demo",
        dataset["dataset_id"],
        fixture["trace"]["trace_id"],
        expected_trace_assertions={"required_tools": ["order_lookup"]},
    )
    run = run_deterministic_eval(
        store,
        project_id="proj_demo",
        dataset_version_id=dataset["latest_version_id"],
        judges=[_wrong_tool_judge()],
    )

    runs = client.get("/v1/evals", params={"project_id": "proj_demo"}, headers=auth_headers())
    assert runs.status_code == 200
    assert runs.json()["data"][0]["eval_run_id"] == run["eval_run_id"]

    results = client.get(
        f"/v1/evals/{run['eval_run_id']}/results",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert results.status_code == 200
    assert results.json()["data"][0]["scores"][0]["failure_mode"] == "wrong_tool_for_refund"
    assert results.json()["data"][0]["scores"][0]["failure_reason"] is None
    assert results.json()["data"][0]["assertion_results"]["status"] == "passed"


def test_v1_judge_registry_eval_compare_and_docs_search(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    store = client.app.state.store
    dataset = store.create_dataset("proj_demo", "Refund judge registry eval")
    store.add_trace_to_dataset("proj_demo", dataset["dataset_id"], fixture["trace"]["trace_id"])

    judge = client.post(
        "/v1/judges/drafts",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "Wrong tool for refund",
            "judge_type": "deterministic_rule",
            "definition": _wrong_tool_judge(),
        },
    )
    assert judge.status_code == 201
    judge_id = judge.json()["judge_id"]
    fetched = client.get(
        f"/v1/judges/{judge_id}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched.status_code == 200
    assert fetched.json()["versions"][0]["definition"]["rule"]["failure_mode"] == (
        "wrong_tool_for_refund"
    )

    historical = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "dataset_version_id": dataset["latest_version_id"],
            "judges": [_order_lookup_present_judge()],
        },
    )
    assert historical.status_code == 201

    baseline = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "dataset_version_id": dataset["latest_version_id"],
            "judge_ids": [judge_id],
        },
    )
    assert baseline.status_code == 201
    candidate = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "dataset_version_id": dataset["latest_version_id"],
            "judges": [_order_lookup_present_judge()],
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
        },
    )
    assert candidate.status_code == 201
    fetched_run = client.get(
        f"/v1/evals/{candidate.json()['eval_run_id']}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched_run.json()["baseline_eval_run_id"] == baseline.json()["eval_run_id"]

    comparison = client.post(
        "/v1/evals/compare",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
            "candidate_eval_run_id": candidate.json()["eval_run_id"],
        },
    )
    assert comparison.status_code == 200
    assert comparison.json()["pass_rate_delta"] == 1.0
    assert comparison.json()["avg_score_delta"] == 1.0
    assert comparison.json()["fixed_failures"]
    historical_runs = comparison.json()["historical_runs"]
    historical_by_id = {run["eval_run_id"]: run for run in historical_runs}
    assert historical_by_id[baseline.json()["eval_run_id"]]["role"] == "baseline"
    assert historical_by_id[candidate.json()["eval_run_id"]]["role"] == "candidate"
    assert historical_by_id[historical.json()["eval_run_id"]]["role"] == "related"
    assert "dataset_version_id" in historical_by_id[historical.json()["eval_run_id"]]["matched_on"]
    assert historical_by_id[candidate.json()["eval_run_id"]]["baseline_eval_run_id"] == (
        baseline.json()["eval_run_id"]
    )

    review_tasks = client.get(
        "/v1/review-tasks",
        params={"project_id": "proj_demo", "task_type": "judge_output"},
        headers=auth_headers(),
    )
    assert review_tasks.status_code == 200
    review_task_id = next(
        task["review_task_id"]
        for task in review_tasks.json()["data"]
        if task["source_entity_id"] == judge_id
    )
    accepted = client.patch(
        f"/v1/review-tasks/{review_task_id}",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "status": "accepted",
            "decision": "accepted",
            "notes": "Calibration label from registry eval test.",
        },
    )
    assert accepted.status_code == 200
    report = client.get(
        f"/v1/judges/{judge_id}/calibration-report",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert report.status_code == 200
    report_body = report.json()
    assert report_body["score_count"] == 1
    assert report_body["verdict_counts"]["fail"] == 1
    assert report_body["invalid_output_rate"] == 0
    assert report_body["human_review_labels"]["accepted"] == 1
    promoted = client.post(
        f"/v1/judges/{judge_id}/promote",
        headers=auth_headers(),
        json={"project_id": "proj_demo"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "promoted"
    assert promoted.json()["judge"]["status"] == "active"

    docs = client.post(
        "/v1/docs/search",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "query": "judge registry", "limit": 5},
    )
    assert docs.status_code == 200
    assert docs.json()["results"]
    all_paths = [*docs.json()["searched_paths"], *[item["path"] for item in docs.json()["results"]]]
    assert "openabm_implementation_spec.md" not in all_paths


def test_v1_model_backed_judge_draft_requires_review(tmp_path, monkeypatch) -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "name": "Refund rubric",
                    "description": "Checks whether refund traces use the right evidence.",
                    "judge_type": "rubric_judge",
                    "definition": {
                        "judge_id": "draft_refund_rubric",
                        "judge_type": "rubric_judge",
                        "rubric": {
                            "pass": "Refund policy evidence supports the action.",
                            "fail": "The trace uses unrelated order lookup evidence.",
                            "unsure": "The trace lacks enough evidence.",
                        },
                        "require_span_citations": True,
                    },
                    "uncertainty": "single trace draft; human review required",
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": None,
                "repaired": False,
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    response = client.post(
        "/v1/judges/drafts",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": fixture["trace"]["trace_id"],
            "natural_language_request": "Draft a rubric for refund tool misuse.",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["judge_type"] == "rubric_judge"
    assert body["status"] == "draft"
    assert body["model_metadata"]["model"] == "stub-model"


def test_v1_retention_export_and_trace_tombstone_flow(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    span_id = fixture["spans"][0]["span_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    dataset = client.post(
        "/v1/datasets",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "name": "Delete flow dataset"},
    )
    example = client.post(
        f"/v1/datasets/{dataset.json()['dataset_id']}/examples/from-trace",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "trace_id": trace_id, "labels": ["delete-flow"]},
    )
    assert example.status_code == 201
    dimension = client.post(
        "/v1/trace-dimensions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "key": "account_id",
            "value": "acct_delete",
        },
    )
    assert dimension.status_code == 201
    context_pack = client.post(
        "/v1/context-packs",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "source_trace_ids": [trace_id]},
    )
    assert context_pack.status_code == 201
    review = client.post(
        "/v1/review-tasks",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "task_type": "delete_flow",
            "source_entity_type": "trace",
            "source_entity_id": trace_id,
            "evidence_ids": [trace_id, span_id],
        },
    )
    assert review.status_code == 201
    deployment_context = client.post(
        "/v1/deployment-contexts",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "deployment_context_id": "deploy_delete_flow",
            "service_name": "support-agent",
            "service_version": "1.0.0",
            "source_revision": "delete-flow-rev",
            "branch_nullable": None,
            "build_id_nullable": None,
            "deploy_id_nullable": None,
            "runtime_nullable": None,
            "environment": "test",
            "created_at": "2026-05-13T00:00:00Z",
        },
    )
    assert deployment_context.status_code == 201
    code_context = client.post(
        "/v1/code-contexts",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "code_context_id": "code_delete_flow",
            "trace_id": trace_id,
            "span_id_nullable": span_id,
            "file_path_nullable": "agents/support.py",
            "function_name_nullable": "run_support_agent",
            "line_start_nullable": 40,
            "line_end_nullable": 88,
            "stack_frame_hash_nullable": "stack-delete-flow",
            "source_url_nullable": "https://example.invalid/support.py#L40-L88",
            "source_revision_nullable": "delete-flow-rev",
            "created_at": "2026-05-13T00:00:00Z",
        },
    )
    assert code_context.status_code == 201
    code_contexts = client.get(
        "/v1/code-contexts",
        headers=auth_headers(),
        params={"project_id": "proj_demo", "trace_id": trace_id},
    )
    assert code_contexts.status_code == 200
    assert code_contexts.json()["data"][0]["code_context_id"] == "code_delete_flow"
    fetched_code_context = client.get(
        "/v1/code-contexts/code_delete_flow",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert fetched_code_context.status_code == 200
    assert fetched_code_context.json()["function_name_nullable"] == "run_support_agent"
    policy = client.post(
        "/v1/retention-policies",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "short lived traces",
            "rules": [{"entity": "traces", "ttl_days": 0}],
            "status": "active",
        },
    )
    assert policy.status_code == 201
    dry_run = client.post(
        f"/v1/retention-policies/{policy.json()['retention_policy_id']}/apply",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "dry_run": True},
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["status"] == "planned"
    assert dry_run.json()["candidate_trace_ids"] == [trace_id]

    export = client.post(
        "/v1/exports/project",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "include_payloads": False},
    )
    assert export.status_code == 200
    manifest = export.json()["manifest"]
    assert manifest["sections"]["traces"]["count"] == 1
    assert manifest["sections"]["trace_jsonl"]["count"] == 1
    assert manifest["sections"]["span_jsonl"]["count"] == len(fixture["spans"])
    assert manifest["sections"]["dataset_examples"]["count"] == 1
    assert manifest["sections"]["deployment_contexts"]["count"] == 1
    assert export.json()["deployment_contexts"][0]["deployment_context_id"] == (
        "deploy_delete_flow"
    )
    assert manifest["sections"]["code_contexts"]["count"] == 1
    assert export.json()["code_contexts"][0]["code_context_id"] == "code_delete_flow"
    assert export.json()["audit_summary"]["total_count"] >= 1
    assert manifest["sections"]["spans"]["sha256"]

    delete = client.post(
        f"/v1/retention-policies/{policy.json()['retention_policy_id']}/apply",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "dry_run": False},
    )
    assert delete.status_code == 200
    assert delete.json()["status"] == "applied"
    assert delete.json()["deleted_trace_ids"] == [trace_id]
    effects = delete.json()["effects"][0]["effects"]
    assert effects["trace_dimensions"] == 1
    assert effects["code_contexts"] == 1
    assert effects["dataset_examples"] == 1
    assert effects["context_packs_scrubbed"] == 1
    assert effects["review_task_evidence_scrubbed"] == 1
    assert "eval_results" in effects
    assert "similarity_vectors" in effects
    scrubbed_context = client.get(
        f"/v1/context-packs/{context_pack.json()['context_pack_id']}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert scrubbed_context.json()["source_trace_ids"] == []
    assert trace_id not in json.dumps(scrubbed_context.json()["content"])
    detail = client.get(
        f"/v1/traces/{trace_id}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert detail.json()["trace"]["status"] == "deleted"
    assert detail.json()["spans"] == []


def test_v1_prompt_and_agent_config_registry_lifecycle(tmp_path) -> None:
    client = make_client(tmp_path)
    prompt = client.post(
        "/v1/prompts",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "name": "Refund assistant"},
    )
    assert prompt.status_code == 201
    prompt_id = prompt.json()["prompt_id"]
    version_1 = client.post(
        f"/v1/prompts/{prompt_id}/versions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "template_text": "Hello {{name}}",
            "variables_schema": {"type": "object", "required": ["name"]},
            "tag": "prod",
        },
    )
    assert version_1.status_code == 201
    version_2 = client.post(
        f"/v1/prompts/{prompt_id}/versions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "template_text": "Hi {{name}}",
            "variables_schema": {"type": "object", "required": ["name"]},
            "parent_commit_id": version_1.json()["commit_id"],
            "tag": "prod",
        },
    )
    assert version_2.status_code == 201
    rendered = client.post(
        f"/v1/prompts/{prompt_id}/render",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "commit_id": version_2.json()["commit_id"],
            "variables": {"name": "OpenABM"},
        },
    )
    assert rendered.json()["rendered"] == "Hi OpenABM"
    mcp_prompt_version = call_tool(
        "commit_prompt",
        {
            "project_id": "proj_demo",
            "prompt_id": prompt_id,
            "template_text": "MCP says hi to {{name}}",
            "variables_schema": {"type": "object", "required": ["name"]},
            "parent_commit_id": version_2.json()["commit_id"],
            "tag": "mcp",
            "confirmed": True,
        },
        client=_TestClientMcpAdapter(client),
    )
    mcp_rendered = call_tool(
        "render_prompt",
        {
            "project_id": "proj_demo",
            "prompt_id": prompt_id,
            "commit_id": mcp_prompt_version["commit_id"],
            "variables": {"name": "OpenABM"},
        },
        client=_TestClientMcpAdapter(client),
    )
    assert mcp_rendered["rendered"] == "MCP says hi to OpenABM"
    prompt_secret = client.post(
        "/v1/secrets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "secret_ref": "secret_prompt_api_key",
            "purpose": "prompt_render",
            "value": "prompt-secret-value",
        },
    )
    assert prompt_secret.status_code == 201
    secret_version = client.post(
        f"/v1/prompts/{prompt_id}/versions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "template_text": "Use {{secret:secret_prompt_api_key}} for {{name}}",
            "variables_schema": {"type": "object", "required": ["name"]},
            "parent_commit_id": version_2.json()["commit_id"],
            "tag": "secret-test",
        },
    )
    assert secret_version.status_code == 201
    blocked_secret_render = client.post(
        f"/v1/prompts/{prompt_id}/render",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "commit_id": secret_version.json()["commit_id"],
            "variables": {"name": "OpenABM"},
        },
    )
    assert blocked_secret_render.status_code == 400
    viewer_key = client.post(
        "/v1/auth/api-keys",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "Prompt viewer key",
            "role": "viewer",
            "scopes": ["*"],
        },
    )
    forbidden_secret_render = client.post(
        f"/v1/prompts/{prompt_id}/render",
        headers={"Authorization": f"Bearer {viewer_key.json()['api_key']}"},
        json={
            "project_id": "proj_demo",
            "commit_id": secret_version.json()["commit_id"],
            "variables": {"name": "OpenABM"},
            "resolve_secret_refs": True,
        },
    )
    assert forbidden_secret_render.status_code == 403
    secret_render = client.post(
        f"/v1/prompts/{prompt_id}/render",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "commit_id": secret_version.json()["commit_id"],
            "variables": {"name": "OpenABM"},
            "resolve_secret_refs": True,
            "purpose": "integration test",
        },
    )
    assert secret_render.status_code == 200
    assert secret_render.json()["rendered"] == "Use prompt-secret-value for OpenABM"
    assert secret_render.json()["secret_interpolations"][0]["secret_ref"] == "secret_prompt_api_key"
    secret_access = client.get(
        "/v1/secrets/secret_prompt_api_key/access-log",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert secret_access.json()["data"][0]["action"] == "prompt_render"
    diff = client.post(
        f"/v1/prompts/{prompt_id}/diff",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "old_commit_id": version_1.json()["commit_id"],
            "new_commit_id": version_2.json()["commit_id"],
        },
    )
    diff_body = diff.json()
    assert "-Hello {{name}}" in diff_body["text_diff"]
    prod_tag_events = [
        event for event in diff_body["tag_movement_history"] if event["tag"] == "prod"
    ]
    assert [event["new_commit_id"] for event in prod_tag_events] == [
        version_1.json()["commit_id"],
        version_2.json()["commit_id"],
    ]
    assert prod_tag_events[1]["previous_commit_id"] == version_1.json()["commit_id"]
    assert diff_body["message_level_diff"]["status"] == "not_applicable"

    message_prompt = client.post(
        "/v1/prompts",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "name": "Message prompt"},
    )
    assert message_prompt.status_code == 201
    message_prompt_id = message_prompt.json()["prompt_id"]
    message_v1 = client.post(
        f"/v1/prompts/{message_prompt_id}/versions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "template_text": json.dumps(
                [
                    {"role": "system", "content": "Be brief."},
                    {"role": "user", "content": "{{question}}"},
                ]
            ),
            "variables_schema": {"type": "object", "required": ["question"]},
        },
    )
    message_v2 = client.post(
        f"/v1/prompts/{message_prompt_id}/versions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "template_text": json.dumps(
                [
                    {"role": "system", "content": "Be precise."},
                    {"role": "user", "content": "{{question}}"},
                    {"role": "assistant", "content": "I will cite trace evidence."},
                ]
            ),
            "variables_schema": {"type": "object", "required": ["question"]},
            "parent_commit_id": message_v1.json()["commit_id"],
        },
    )
    message_diff = client.post(
        f"/v1/prompts/{message_prompt_id}/diff",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "old_commit_id": message_v1.json()["commit_id"],
            "new_commit_id": message_v2.json()["commit_id"],
        },
    )
    assert message_diff.json()["message_level_diff"]["status"] == "succeeded"
    assert message_diff.json()["message_level_diff"]["message_count_delta"] == 1
    assert message_diff.json()["message_level_diff"]["changed_message_count"] == 2
    fetched_prompt = client.get(
        f"/v1/prompts/{prompt_id}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched_prompt.json()["tags"]["prod"] == version_2.json()["commit_id"]

    config = client.post(
        "/v1/agent-configs",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "Refund runtime",
            "config_type": "runtime",
        },
    )
    assert config.status_code == 201
    config_id = config.json()["agent_config_id"]
    cfg_v1 = client.post(
        f"/v1/agent-configs/{config_id}/versions",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "content": {"model": "local-9b"}, "tag": "prod"},
    )
    cfg_v2 = client.post(
        f"/v1/agent-configs/{config_id}/versions",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "content": {"model": "local-9b", "tools": ["lookup"]},
            "metadata": {"deployment_context_id": "deploy_refund_runtime_v2"},
            "tag": "prod",
        },
    )
    compare = client.post(
        f"/v1/agent-configs/{config_id}/compare",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "old_commit_id": cfg_v1.json()["commit_id"],
            "new_commit_id": cfg_v2.json()["commit_id"],
        },
    )
    assert '"tools":["lookup"]' in compare.json()["content_diff"]
    compare_body = compare.json()
    assert compare_body["metadata_changed"] is True
    assert compare_body["metadata_diff"]["changed_fields"] == ["deployment_context_id"]
    assert compare_body["structured_diff"]["tool_changes"]["added"] == ["lookup"]
    assert compare_body["structured_diff"]["changed_fields"] == ["tools"]
    config_detail = client.get(
        f"/v1/agent-configs/{config_id}",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert config_detail.json()["tags"]["prod"] == cfg_v2.json()["commit_id"]
    deployment_context_payload = {
        "project_id": "proj_demo",
        "deployment_context_id": "deploy_refund_runtime_v2",
        "service_name": "refund-agent",
        "service_version": "2.0.0",
        "source_revision": "abc123",
        "branch_nullable": "main",
        "build_id_nullable": "build-456",
        "deploy_id_nullable": "deploy-789",
        "runtime_nullable": "python3.12",
        "environment": "prod",
        "created_at": "2026-05-13T00:00:00Z",
    }
    deployment_context = client.post(
        "/v1/deployment-contexts",
        headers=auth_headers(),
        json=deployment_context_payload,
    )
    assert deployment_context.status_code == 201
    assert deployment_context.json()["service_name"] == "refund-agent"
    deployment_contexts = client.get(
        "/v1/deployment-contexts",
        headers=auth_headers(),
        params={"project_id": "proj_demo", "environment": "prod"},
    )
    assert deployment_contexts.status_code == 200
    assert deployment_contexts.json()["data"][0]["deployment_context_id"] == (
        "deploy_refund_runtime_v2"
    )
    fetched_deployment_context = client.get(
        "/v1/deployment-contexts/deploy_refund_runtime_v2",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert fetched_deployment_context.status_code == 200
    assert fetched_deployment_context.json()["source_revision"] == "abc123"
    mcp_config_version = call_tool(
        "commit_agent_config",
        {
            "project_id": "proj_demo",
            "agent_config_id": config_id,
            "content": {"model": "local-9b", "tools": ["lookup", "refund_status"]},
            "tag": "mcp",
            "confirmed": True,
        },
        client=_TestClientMcpAdapter(client),
    )
    mcp_config_detail = client.get(
        f"/v1/agent-configs/{config_id}",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert mcp_config_detail.json()["tags"]["mcp"] == mcp_config_version["commit_id"]
    assert [
        event["new_commit_id"]
        for event in compare_body["tag_movement_history"]
        if event["tag"] == "prod"
    ] == [cfg_v1.json()["commit_id"], cfg_v2.json()["commit_id"]]
    prod_config_tag_events = [
        event for event in compare_body["tag_movement_history"] if event["tag"] == "prod"
    ]
    assert prod_config_tag_events[1]["previous_commit_id"] == cfg_v1.json()["commit_id"]

    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace = {
        **fixture["trace"],
        "prompt_version_id": version_2.json()["prompt_version_id"],
        "agent_config_version_id": cfg_v2.json()["agent_config_version_id"],
        "deployment_context_id": "deploy_refund_runtime_v2",
        "tool_version_ids": ["tool_lookup_v1"],
    }
    ingest = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [trace], "spans": fixture["spans"]},
    )
    assert ingest.status_code == 207
    detail = client.get(
        f"/v1/traces/{trace['trace_id']}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert detail.status_code == 200
    assert detail.json()["trace"]["prompt_version_id"] == version_2.json()["prompt_version_id"]
    assert detail.json()["trace"]["agent_config_version_id"] == cfg_v2.json()[
        "agent_config_version_id"
    ]
    assert detail.json()["trace"]["tool_version_ids"] == ["tool_lookup_v1"]

    store = client.app.state.store
    dataset = store.create_dataset("proj_demo", "Runtime provenance eval")
    store.add_trace_to_dataset("proj_demo", dataset["dataset_id"], trace["trace_id"])
    baseline = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "dataset_version_id": dataset["latest_version_id"],
            "judges": [_wrong_tool_judge()],
            "prompt_version_id": version_1.json()["prompt_version_id"],
            "agent_config_version_id": cfg_v1.json()["agent_config_version_id"],
            "runtime_context": {
                "deployment_context_id": "deploy_refund_runtime_v1",
                "tool_version_ids": ["tool_refund_v1"],
            },
        },
    )
    candidate = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "dataset_version_id": dataset["latest_version_id"],
            "judges": [_wrong_tool_judge()],
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
            "prompt_version_id": version_2.json()["prompt_version_id"],
            "agent_config_version_id": cfg_v2.json()["agent_config_version_id"],
            "runtime_context": {
                "deployment_context_id": "deploy_refund_runtime_v2",
                "tool_version_ids": ["tool_refund_v2"],
            },
        },
    )
    assert baseline.status_code == 201
    assert candidate.status_code == 201
    assert candidate.json()["agent_config_version_id"] == cfg_v2.json()[
        "agent_config_version_id"
    ]
    post_eval_config_compare = client.post(
        f"/v1/agent-configs/{config_id}/compare",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "old_commit_id": cfg_v1.json()["commit_id"],
            "new_commit_id": cfg_v2.json()["commit_id"],
        },
    )
    config_eval_diff = post_eval_config_compare.json()["linked_eval_result_diff"]
    assert config_eval_diff["old"]["eval_run_ids"] == [baseline.json()["eval_run_id"]]
    assert config_eval_diff["new"]["eval_run_ids"] == [candidate.json()["eval_run_id"]]
    assert config_eval_diff["run_count_delta"] == 0
    comparison = client.post(
        "/v1/evals/compare",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
            "candidate_eval_run_id": candidate.json()["eval_run_id"],
        },
    )
    assert comparison.status_code == 200
    provenance = comparison.json()["provenance_comparison"]
    assert set(provenance["changed_fields"]) == {
        "prompt_version_id",
        "agent_config_version_id",
        "deployment_context_id",
        "tool_version_ids",
    }
    assert provenance["candidate"]["runtime_context"]["deployment_context_id"] == (
        "deploy_refund_runtime_v2"
    )
    diff_after_evals = client.post(
        f"/v1/prompts/{prompt_id}/diff",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "old_commit_id": version_1.json()["commit_id"],
            "new_commit_id": version_2.json()["commit_id"],
        },
    )
    linked_eval_diff = diff_after_evals.json()["linked_eval_result_diff"]
    assert linked_eval_diff["old"]["run_count"] == 1
    assert linked_eval_diff["new"]["run_count"] == 1
    assert linked_eval_diff["old"]["eval_run_ids"] == [baseline.json()["eval_run_id"]]
    assert linked_eval_diff["new"]["eval_run_ids"] == [candidate.json()["eval_run_id"]]
    assert linked_eval_diff["run_count_delta"] == 0
    prompt_usage = client.get(
        f"/v1/prompts/{prompt_id}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    ).json()
    prompt_v2_usage = next(
        version["usage_summary"]
        for version in prompt_usage["versions"]
        if version["prompt_version_id"] == version_2.json()["prompt_version_id"]
    )
    assert prompt_v2_usage["trace_count"] == 1
    assert prompt_v2_usage["trace_status_counts"] == {"error": 1}
    assert prompt_v2_usage["recent_traces"][0]["trace_id"] == trace["trace_id"]
    assert prompt_v2_usage["eval_summary"]["eval_run_ids"] == [candidate.json()["eval_run_id"]]
    assert next(
        version["active_tags"]
        for version in prompt_usage["versions"]
        if version["commit_id"] == version_2.json()["commit_id"]
    ) == ["prod"]
    config_usage = client.get(
        f"/v1/agent-configs/{config_id}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    ).json()
    config_v2_usage = next(
        version["usage_summary"]
        for version in config_usage["versions"]
        if version["agent_config_version_id"] == cfg_v2.json()["agent_config_version_id"]
    )
    assert config_v2_usage["trace_count"] == 1
    assert config_v2_usage["recent_traces"][0]["trace_id"] == trace["trace_id"]
    assert config_v2_usage["eval_summary"]["eval_run_ids"] == [candidate.json()["eval_run_id"]]
    assert next(
        version["active_tags"]
        for version in config_usage["versions"]
        if version["commit_id"] == cfg_v2.json()["commit_id"]
    ) == ["prod"]
    analytics = client.get(
        "/v1/evals/analytics",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert analytics.status_code == 200
    analytics_body = analytics.json()
    assert analytics_body["run_count"] == 2
    assert analytics_body["by_prompt_version"][0]["run_count"] == 1
    prompt_keys = {item["key"] for item in analytics_body["by_prompt_version"]}
    assert version_1.json()["prompt_version_id"] in prompt_keys
    assert version_2.json()["prompt_version_id"] in prompt_keys
    deployment_keys = {item["key"] for item in analytics_body["by_deployment_context"]}
    assert {"deploy_refund_runtime_v1", "deploy_refund_runtime_v2"} <= deployment_keys
    assert [row["eval_run_id"] for row in analytics_body["trend"]] == [
        baseline.json()["eval_run_id"],
        candidate.json()["eval_run_id"],
    ]
    assert analytics_body["trend"][0]["pass_rate_delta"] is None
    assert analytics_body["trend"][1]["pass_rate_delta"] == 0.0
    assert analytics_body["trend"][1]["deployment_context_id"] == "deploy_refund_runtime_v2"

    investigation = client.post(
        "/v1/investigations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "seed_trace_id_nullable": trace["trace_id"],
            "filters": {"trace_id": trace["trace_id"]},
        },
    )
    assert investigation.status_code == 201
    impact = investigation.json()["result"]["impact_report"]
    assert impact["deployment_distribution"]["prompt_version_id"][
        version_2.json()["prompt_version_id"]
    ] == 1
    assert impact["deployment_distribution"]["agent_config_version_id"][
        cfg_v2.json()["agent_config_version_id"]
    ] == 1
    assert any(
        candidate["hypothesis"] == "Trace cohort has correlated runtime provenance identifiers."
        for candidate in impact["suspected_root_causes"]
    )
    prompt_candidate = next(
        candidate
        for candidate in impact["suspected_root_causes"]
        if candidate.get("evidence_summary", {}).get("field") == "prompt_version_id"
    )
    assert prompt_candidate["failing_cohort_metric"] == {"count": 1, "rate": 1.0}
    assert prompt_candidate["baseline_cohort_metric"] == {"count": 0, "rate": 0.0}
    assert prompt_candidate["lift_or_delta"]["rate_delta"] == 1.0
    assert prompt_candidate["representative_trace_ids"] == [trace["trace_id"]]
    tool_candidate = next(
        candidate
        for candidate in impact["suspected_root_causes"]
        if candidate.get("evidence_summary", {}).get("field") == "tool_name"
    )
    assert tool_candidate["representative_span_ids"] == ["span_wrong_tool_order_lookup"]


def test_v1_automation_run_creates_review_task_and_notification_preview(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    target = client.post(
        "/v1/notification-targets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "type": "webhook",
            "display_name": "Local preview",
            "config_secret_refs": ["secret_webhook_url"],
        },
    )
    assert target.status_code == 201
    automation = client.post(
        "/v1/automations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "review refund errors",
            "trigger": {"type": "trace_completed"},
            "conditions": {
                "combine": "all",
                "items": [{"field": "trace.status", "op": "eq", "value": "error"}],
            },
            "cooldown": {"seconds": 1800, "key": "automation_id + project_id"},
            "actions": [
                {"type": "create_review_task", "task_type": "behavior_candidate"},
                {
                    "type": "send_notification",
                    "target_id": target.json()["target_id"],
                    "message": "Refund error needs review",
                },
            ],
        },
    )
    assert automation.status_code == 201
    preview = client.post(
        f"/v1/automations/{automation.json()['automation_id']}/preview",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "filters": {"status": "error"}},
    )
    assert preview.status_code == 200
    assert preview.json()["match_count"] == 1
    assert preview.json()["matches"][0]["trace_id"] == trace_id
    assert preview.json()["matches"][0]["condition_result"]["passed"] is True

    run = client.post(
        f"/v1/automations/{automation.json()['automation_id']}/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "idempotency_key": "auto-test-1",
        },
    )
    assert run.status_code == 201
    body = run.json()
    assert body["status"] == "succeeded"
    assert body["condition_result"]["passed"] is True
    assert body["action_results"][0]["status"] == "succeeded"
    assert body["action_results"][1]["delivery_status"] == "preview_only"

    duplicate = client.post(
        f"/v1/automations/{automation.json()['automation_id']}/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "idempotency_key": "auto-test-1",
        },
    )
    assert duplicate.json()["duplicate"] is True

    cooldown = client.post(
        f"/v1/automations/{automation.json()['automation_id']}/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "idempotency_key": "auto-test-2",
        },
    )
    assert cooldown.status_code == 201
    cooldown_body = cooldown.json()
    assert cooldown_body["status"] == "skipped_cooldown"
    assert cooldown_body["cooldown_result"]["active"] is True
    assert cooldown_body["action_results"] == []
    runs = client.get(
        f"/v1/automations/{automation.json()['automation_id']}/runs",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert runs.status_code == 200
    assert sorted(item["status"] for item in runs.json()["data"]) == [
        "skipped_cooldown",
        "succeeded",
    ]

    retrying = client.post(
        "/v1/automations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "continue after notification failure",
            "trigger": {"type": "trace_completed"},
            "conditions": {
                "combine": "all",
                "items": [{"field": "trace.status", "op": "eq", "value": "error"}],
            },
            "actions": [
                {
                    "type": "send_notification",
                    "target_id": "missing_target",
                    "message": "This should dead-letter",
                    "retry": {"attempts": 2},
                    "on_failure": "continue",
                },
                {"type": "create_review_task", "task_type": "behavior_candidate"},
            ],
        },
    )
    assert retrying.status_code == 201
    retry_run = client.post(
        f"/v1/automations/{retrying.json()['automation_id']}/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "idempotency_key": "auto-test-retry",
        },
    )
    assert retry_run.status_code == 201
    retry_body = retry_run.json()
    assert retry_body["status"] == "partial_failure"
    assert retry_body["action_results"][0]["status"] == "dead_lettered"
    assert retry_body["action_results"][0]["attempts"] == 2
    assert retry_body["action_results"][0]["partial_failure_behavior"] == "continue"
    assert retry_body["action_results"][1]["status"] == "succeeded"

    compensating = client.post(
        "/v1/automations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "compensate after notification failure",
            "trigger": {"type": "trace_completed"},
            "conditions": {
                "combine": "all",
                "items": [{"field": "trace.status", "op": "eq", "value": "error"}],
            },
            "actions": [
                {
                    "type": "create_review_task",
                    "task_type": "behavior_candidate",
                    "compensation_actions": [
                        {
                            "type": "rollback_review_task",
                            "notes": (
                                "Review task created by failed automation path "
                                "was rolled back"
                            ),
                        },
                        {
                            "type": "send_notification",
                            "target_id": target.json()["target_id"],
                            "message": "Review task needs manual cleanup",
                            "group_key": "compensation-review-cleanup",
                        }
                    ],
                },
                {
                    "type": "send_notification",
                    "target_id": "missing_target",
                    "message": "This should trigger compensation",
                    "on_failure": "compensate",
                },
            ],
        },
    )
    assert compensating.status_code == 201
    compensation_run = client.post(
        f"/v1/automations/{compensating.json()['automation_id']}/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "idempotency_key": "auto-test-compensate",
        },
    )
    assert compensation_run.status_code == 201
    compensation_body = compensation_run.json()
    assert compensation_body["status"] == "partial_failure"
    failed_action = compensation_body["action_results"][1]
    assert failed_action["status"] == "dead_lettered"
    assert failed_action["partial_failure_behavior"] == "compensate"
    assert failed_action["compensation_status"] == "succeeded"
    rollback_result = failed_action["compensation_results"][0]
    notification_result = failed_action["compensation_results"][1]
    created_task_id = compensation_body["action_results"][0]["result"]["review_task_id"]
    assert rollback_result["type"] == "rollback_review_task"
    assert rollback_result["rollback"]["target_id"] == created_task_id
    assert rollback_result["result"]["status"] == "resolved"
    assert rollback_result["result"]["decision_nullable"] == "rolled_back_by_automation"
    assert rollback_result["compensates_action_index"] == 0
    assert notification_result["delivery_status"] == "preview_only"
    assert notification_result["compensates_action_index"] == 0
    assert notification_result["group_key"] == "compensation-review-cleanup"


def test_v1_notification_targets_require_secret_refs(tmp_path) -> None:
    client = make_client(tmp_path)
    plaintext = client.post(
        "/v1/notification-targets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "type": "webhook",
            "display_name": "Plaintext webhook",
            "config": {"url": "https://example.invalid/webhook"},
        },
    )
    assert plaintext.status_code == 400
    assert plaintext.json()["error"]["code"] == "schema_validation_failed"

    bad_ref = client.post(
        "/v1/notification-targets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "type": "webhook",
            "display_name": "Bad ref",
            "config_secret_refs": ["https://example.invalid/webhook"],
        },
    )
    assert bad_ref.status_code == 400
    assert bad_ref.json()["error"]["path"] == "/config_secret_refs/0"

    paused_without_secret = client.post(
        "/v1/notification-targets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "type": "webhook",
            "display_name": "Paused placeholder",
            "status": "paused",
        },
    )
    assert paused_without_secret.status_code == 201


def test_v1_live_webhook_notification_is_secret_backed_and_audited(tmp_path, monkeypatch) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        enable_external_notifications=True,
    )
    client = TestClient(create_app(settings))
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    secret = client.post(
        "/v1/secrets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "secret_ref": "secret_live_webhook",
            "purpose": "notification_webhook",
            "value": "https://example.invalid/openabm-webhook",
        },
    )
    assert secret.status_code == 201
    target = client.post(
        "/v1/notification-targets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "type": "webhook",
            "display_name": "Live webhook",
            "config_secret_refs": ["secret_live_webhook"],
        },
    )
    assert target.status_code == 201

    observed: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> httpx.Response:
        observed["url"] = url
        observed["json"] = json
        observed["timeout"] = timeout
        return httpx.Response(202, json={"ok": True})

    monkeypatch.setattr("openabm_api.main.httpx.post", fake_post)
    automation = client.post(
        "/v1/automations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "live notification",
            "trigger": {"type": "trace_completed"},
            "conditions": {
                "combine": "all",
                "items": [{"field": "trace.status", "op": "eq", "value": "error"}],
            },
            "actions": [
                {
                    "type": "send_notification",
                    "target_id": target.json()["target_id"],
                    "message": "Refund error needs review",
                    "delivery_mode": "live",
                    "group_key": "refund-errors",
                }
            ],
        },
    )
    assert automation.status_code == 201
    run = client.post(
        f"/v1/automations/{automation.json()['automation_id']}/run",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "trace_id": trace_id},
    )

    assert run.status_code == 201
    result = run.json()["action_results"][0]
    assert result["status"] == "succeeded"
    assert result["delivery_status"] == "delivered"
    assert result["http_status"] == 202
    assert result["group_key"] == "refund-errors"
    assert observed["url"] == "https://example.invalid/openabm-webhook"
    assert observed["json"]["trace_id"] == trace_id
    assert "openabm-webhook" not in json.dumps(result)

    email_secret = client.post(
        "/v1/secrets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "secret_ref": "secret_live_email_adapter",
            "purpose": "notification_email_adapter",
            "value": "local-email-adapter-config",
        },
    )
    assert email_secret.status_code == 201
    email_target = client.post(
        "/v1/notification-targets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "type": "email",
            "display_name": "Email adapter",
            "config_secret_refs": ["secret_live_email_adapter"],
        },
    )
    assert email_target.status_code == 201
    email_automation = client.post(
        "/v1/automations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "email notification adapter",
            "trigger": {"type": "trace_completed"},
            "conditions": {
                "combine": "all",
                "items": [{"field": "trace.status", "op": "eq", "value": "error"}],
            },
            "actions": [
                {
                    "type": "send_notification",
                    "target_id": email_target.json()["target_id"],
                    "message": "Refund error needs review by email",
                    "delivery_mode": "live",
                    "group_key": "refund-email",
                }
            ],
        },
    )
    assert email_automation.status_code == 201
    email_run = client.post(
        f"/v1/automations/{email_automation.json()['automation_id']}/run",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "trace_id": trace_id},
    )
    assert email_run.status_code == 201
    email_result = email_run.json()["action_results"][0]
    assert email_result["status"] == "succeeded"
    assert email_result["delivery_status"] == "queued_for_adapter"
    assert email_result["adapter_status"] == "local_outbox"
    assert email_result["target_type"] == "email"
    assert "local-email-adapter-config" not in json.dumps(email_result)


def test_v1_grounding_checks_and_novelty_runs_are_reviewable(tmp_path) -> None:
    client = make_client(tmp_path)
    corpus = json.loads(FIXTURE_PATH.read_text())
    happy_fixture = corpus["fixtures"][0]
    fixture = corpus["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    negative_trace_id = happy_fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [happy_fixture["trace"], fixture["trace"]],
            "spans": [*happy_fixture["spans"], *fixture["spans"]],
        },
    )
    grounding = client.post(
        "/v1/grounding-checks",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "claims": [
                {"claim": "delivered"},
                {"claim": "refund policy approved"},
            ],
        },
    )
    assert grounding.status_code == 201
    assert grounding.json()["status"] == "needs_review"
    statuses = {claim["claim"]: claim["status"] for claim in grounding.json()["claims"]}
    assert statuses["delivered"] == "supported"
    assert statuses["refund policy approved"] == "missing_evidence"

    novelty = client.post(
        "/v1/novelty-runs",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "filters": {"status": "error"}},
    )
    assert novelty.status_code == 201
    result = novelty.json()["result"]
    candidates = result["new_behavior_candidates"]
    assert candidates[0]["representative_positive_traces"] == [trace_id]
    assert candidates[0]["representative_negative_traces"] == [negative_trace_id]
    assert result["negative_example_selection"]["status"] == "succeeded"
    assert result["negative_example_selection"]["candidate_count_with_negatives"] == 1
    reviews = client.get(
        "/v1/review-tasks",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert {"grounding_check", "behavior_candidate"} <= {
        task["task_type"] for task in reviews.json()["data"]
    }


def test_v1_model_grouped_novelty_candidates_are_reviewable(tmp_path, monkeypatch) -> None:
    class StubProvider:
        async def tool_completion(self, request, tools):
            del request, tools
            return {
                "status": "succeeded",
                "tool_calls": [
                    {
                        "name": "record_novelty_groups",
                        "arguments": {
                            "groups": [
                                {
                                    "name": "Refund flow uses order lookup",
                                    "description": (
                                        "Refund requests are routed through order lookup."
                                    ),
                                    "candidate_names": ["error_wrong_tool", "not_real"],
                                    "severity": "high",
                                    "uncertainty": "single fixture trace",
                                }
                            ],
                            "uncertainty": "model grouped deterministic signatures",
                        },
                    }
                ],
                "provider": "stub",
                "model": "stub-model",
                "usage": {"total_tokens": 77},
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    novelty = client.post(
        "/v1/novelty-runs",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "filters": {"status": "error"},
            "semantic_grouping_with_model": True,
        },
    )
    assert novelty.status_code == 201
    result = novelty.json()["result"]
    candidate = result["new_behavior_candidates"][0]
    assert candidate["name"] == "Refund flow uses order lookup"
    assert candidate["source_candidate_names"] == ["error_wrong_tool"]
    assert candidate["representative_positive_traces"] == [trace_id]
    assert result["source_signature_candidates"][0]["name"] == "error_wrong_tool"
    assert result["semantic_grouping"]["model_metadata"]["model"] == "stub-model"


def test_v1_model_extracted_grounding_claims_are_deterministically_checked(
    tmp_path,
    monkeypatch,
) -> None:
    class StubProvider:
        async def tool_completion(self, request, tools):
            del request, tools
            return {
                "status": "succeeded",
                "tool_calls": [
                    {
                        "name": "record_grounding_extraction",
                        "arguments": {
                            "claims": ["delivered", "refund policy approved"],
                            "possible_contradictions": [
                                {
                                    "claim": "refund policy approved",
                                    "contradicted_by_span_ids": [
                                        "span_wrong_tool_order_lookup",
                                        "span_not_real",
                                    ],
                                    "reason": "Trace shows order lookup evidence.",
                                    "uncertainty": "single fixture trace",
                                }
                            ],
                            "uncertainty": "tool call extraction requires deterministic check",
                        },
                    }
                ],
                "provider": "stub",
                "model": "stub-model",
                "usage": {"total_tokens": 99},
                "repaired": False,
            }

        async def structured_completion(self, request, schema):
            del request, schema
            raise AssertionError("tool completion should be used before structured fallback")

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    response = client.post(
        "/v1/grounding-checks",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "text": "The order was delivered and refund policy approved.",
            "extract_claims_with_model": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "needs_review"
    statuses = {claim["claim"]: claim["status"] for claim in body["claims"]}
    assert statuses["delivered"] == "supported"
    assert statuses["refund policy approved"] == "missing_evidence"
    contradiction = body["model_extraction"]["possible_contradictions"][0]
    assert contradiction["contradicted_by_span_ids"] == ["span_wrong_tool_order_lookup"]
    assert body["model_extraction"]["model_metadata"]["model"] == "stub-model"


def test_v1_model_adjudicated_grounding_contradictions_are_review_gated(
    tmp_path,
    monkeypatch,
) -> None:
    class StubProvider:
        async def tool_completion(self, request, tools):
            assert request["tool_choice"]["function"]["name"] == (
                "record_grounding_contradictions"
            )
            assert tools[0]["function"]["name"] == "record_grounding_contradictions"
            return {
                "status": "succeeded",
                "tool_calls": [
                    {
                        "name": "record_grounding_contradictions",
                        "arguments": {
                            "contradictions": [
                                {
                                    "claim": "refund policy approved",
                                    "contradicted_by_span_ids": [
                                        "span_wrong_tool_order_lookup",
                                        "span_not_real",
                                    ],
                                    "reason": "Trace evidence shows an order lookup instead.",
                                    "uncertainty": "single fixture trace",
                                },
                                {
                                    "claim": "not one of the supplied claims",
                                    "contradicted_by_span_ids": [
                                        "span_wrong_tool_order_lookup",
                                    ],
                                    "reason": "Should be ignored by deterministic validation.",
                                },
                            ],
                            "uncertainty": "model contradiction adjudication",
                        },
                    }
                ],
                "provider": "stub",
                "model": "stub-model",
                "usage": {"total_tokens": 88},
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    response = client.post(
        "/v1/grounding-checks",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": trace_id,
            "claims": [
                {"claim": "delivered"},
                {"claim": "refund policy approved"},
            ],
            "adjudicate_contradictions_with_model": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "contradicted"
    claims = {claim["claim"]: claim for claim in body["claims"]}
    assert claims["delivered"]["status"] == "supported"
    assert claims["refund policy approved"]["status"] == "contradicted"
    assert claims["refund policy approved"]["contradicted_by_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]
    adjudication = body["model_contradiction_adjudication"]
    assert adjudication["model_metadata"]["model"] == "stub-model"
    assert adjudication["contradictions"][0]["claim"] == "refund policy approved"
    assert adjudication["contradictions"][0]["contradicted_by_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]

    listed = client.get(
        "/v1/grounding-checks",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["model_contradiction_adjudication"] == adjudication
    reviews = client.get(
        "/v1/review-tasks",
        params={"project_id": "proj_demo", "task_type": "grounding_check"},
        headers=auth_headers(),
    )
    assert reviews.status_code == 200
    assert reviews.json()["data"][0]["source_entity_id"] == body["grounding_check_id"]


def test_v1_screenshot_issue_and_chatops_create_canonical_artifacts(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    trace_id = fixture["trace"]["trace_id"]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    screenshot_issue = client.post(
        "/v1/issues/from-screenshot",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "title": "Screenshot issue report",
            "screenshot_payload_id_nullable": "payload_screenshot_1",
            "attachments": [
                {
                    "payload_id": "payload_log_1",
                    "content_type": "application/json",
                    "filename": "support-event.json",
                    "content_base64": base64.b64encode(
                        json.dumps(
                            {
                                "symptom": "damaged order refund",
                                "tool": "order lookup",
                                "status": "refund blocked",
                            }
                        ).encode("utf-8")
                    ).decode("ascii"),
                },
                {
                    "payload_id": "payload_pdf_1",
                    "content_type": "application/pdf",
                    "filename": "support-escalation.pdf",
                    "content_base64": _pdf_base64(
                        "uploaded PDF says damaged order refund needs escalation"
                    ),
                },
                {
                    "payload_id": "payload_docx_1",
                    "content_type": (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    "filename": "support-summary.docx",
                    "content_base64": _docx_base64(
                        "uploaded DOCX says refund blocked by order lookup"
                    ),
                }
            ],
        },
    )
    assert screenshot_issue.status_code == 201
    screenshot_body = screenshot_issue.json()
    assert screenshot_body["source_type"] == "screenshot"
    assert screenshot_body["candidate_seed_traces"][0]["trace_id"] == trace_id
    assert screenshot_body["intake_evidence"]["attachment_payload_ids"] == [
        "payload_screenshot_1",
        "payload_log_1",
        "payload_pdf_1",
        "payload_docx_1",
    ]
    assert "damaged order refund" in screenshot_body["intake_evidence"]["query"]
    assert "order lookup" in screenshot_body["intake_evidence"]["query"]
    assert "uploaded PDF says damaged order refund" in screenshot_body["intake_evidence"]["query"]
    assert "uploaded DOCX says refund blocked" in screenshot_body["intake_evidence"]["query"]
    assert screenshot_body["intake_evidence"]["source_counts"]["parsed_attachments"] == 3
    parse_results = {
        result["payload_id"]: result
        for result in screenshot_body["intake_evidence"]["attachment_parse_results"]
    }
    assert parse_results["payload_log_1"]["status"] == "parsed"
    assert screenshot_body["intake_evidence"]["attachment_parse_results"][0][
        "extracted_fields"
    ][:2] == ["content_base64", "content_base64:parsed_json:0"]
    assert parse_results["payload_pdf_1"]["status"] == "parsed"
    assert parse_results["payload_pdf_1"]["binary_like"] is True
    assert parse_results["payload_pdf_1"]["extracted_fields"] == ["content_base64"]
    assert parse_results["payload_docx_1"]["status"] == "parsed"
    assert parse_results["payload_docx_1"]["binary_like"] is True
    assert parse_results["payload_docx_1"]["extracted_fields"] == ["content_base64"]
    screenshot_links = client.get(
        f"/v1/issues/{screenshot_body['issue_id']}/links",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert screenshot_links.status_code == 200
    screenshot_targets = {
        (link["target_type"], link["target_id"], link["relation"])
        for link in screenshot_links.json()["data"]
    }
    assert ("payload_object", "payload_screenshot_1", "screenshot_payload") in screenshot_targets
    assert ("payload_object", "payload_log_1", "source_attachment") in screenshot_targets
    assert ("payload_object", "payload_pdf_1", "source_attachment") in screenshot_targets
    assert ("payload_object", "payload_docx_1", "source_attachment") in screenshot_targets

    chatops = client.post(
        "/v1/chatops/investigate",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "message": "Investigate damaged order refund failures",
            "seed_trace_id_nullable": trace_id,
        },
    )
    assert chatops.status_code == 201
    assert chatops.json()["issue"]["source_type"] == "chat"
    assert chatops.json()["links"]["investigation_run"].startswith("investigation-run://")


def test_v1_screenshot_issue_uses_configured_image_ocr(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs) -> subprocess.CompletedProcess:
        calls.append(command)
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 12.0
        assert command[0] == "fake-tesseract"
        assert command[2] == "stdout"
        assert command[3:] == ["--psm", "11", "-l", "eng", "--loglevel", "ERROR"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="OCR says damaged refund screenshot requires escalation\n",
            stderr="",
        )

    monkeypatch.setattr("openabm_api.main.subprocess.run", fake_run)
    client = make_client_with_settings(
        tmp_path,
        image_ocr_command="fake-tesseract",
        image_ocr_timeout_seconds=12.0,
    )

    response = client.post(
        "/v1/issues/from-screenshot",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "title": "OCR screenshot issue",
            "screenshot_payload_id_nullable": "payload_screenshot_ocr",
            "attachments": [
                {
                    "payload_id": "payload_image_1",
                    "content_type": "image/png",
                    "filename": "support-screenshot.png",
                    "content_base64": base64.b64encode(b"fake-image-bytes").decode("ascii"),
                },
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "OCR says damaged refund screenshot" in body["intake_evidence"]["query"]
    parse_result = body["intake_evidence"]["attachment_parse_results"][0]
    assert parse_result["status"] == "parsed"
    assert parse_result["image_like"] is True
    assert parse_result["extracted_fields"] == ["content_base64"]
    assert body["intake_evidence"]["source_counts"]["parsed_attachments"] == 1
    assert len(calls) == 1


def test_v1_screenshot_issue_parses_xlsx_and_pptx_attachments(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/v1/issues/from-screenshot",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "title": "Office attachments issue",
            "screenshot_payload_id_nullable": "payload_screenshot_office",
            "attachments": [
                {
                    "payload_id": "payload_xlsx_1",
                    "content_type": (
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                    "filename": "support-metrics.xlsx",
                    "content_base64": _xlsx_base64(
                        "uploaded XLSX says escalation queue has five blocked refunds"
                    ),
                },
                {
                    "payload_id": "payload_pptx_1",
                    "content_type": (
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    ),
                    "filename": "support-deck.pptx",
                    "content_base64": _pptx_base64(
                        "uploaded PPTX says checkout agent loop is recurring"
                    ),
                },
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "uploaded XLSX says escalation queue" in body["intake_evidence"]["query"]
    assert "uploaded PPTX says checkout agent loop" in body["intake_evidence"]["query"]
    parse_results = {
        result["payload_id"]: result
        for result in body["intake_evidence"]["attachment_parse_results"]
    }
    assert parse_results["payload_xlsx_1"]["status"] == "parsed"
    assert parse_results["payload_xlsx_1"]["extracted_fields"] == ["content_base64"]
    assert parse_results["payload_pptx_1"]["status"] == "parsed"
    assert parse_results["payload_pptx_1"]["extracted_fields"] == ["content_base64"]
    assert body["intake_evidence"]["source_counts"]["parsed_attachments"] == 2


def test_v1_rubric_judge_run_persists_cited_score(tmp_path, monkeypatch) -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "verdict": "fail",
                    "score": 0.0,
                    "confidence": 0.7,
                    "reasoning": "Order lookup was used for a refund issue.",
                    "evidence_span_ids": ["span_wrong_tool_order_lookup"],
                    "failure_mode": "wrong_tool_for_refund",
                    "notes": None,
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": None,
                "repaired": False,
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    response = client.post(
        "/v1/judges/rubric/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": fixture["trace"]["trace_id"],
            "judge": {
                "judge_id": "judge_wrong_tool_for_refund",
                "judge_type": "rubric_judge",
                "rubric": {"fail": "Wrong tool was used for the task."},
            },
        },
    )
    assert response.status_code == 201
    assert response.json()["failure_reason"] is None
    assert response.json()["evidence_span_ids"] == ["span_wrong_tool_order_lookup"]
    scores = client.get(
        "/v1/scores",
        params={"project_id": "proj_demo", "trace_id": fixture["trace"]["trace_id"]},
        headers=auth_headers(),
    )
    assert scores.json()["data"][0]["failure_reason"] is None
    assert scores.json()["data"][0]["cost"]["model"] == "stub-model"


def test_v1_rubric_judge_run_reports_disabled_model(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        chat_model="stub-model",
        model_mode="disabled",
    )
    client = TestClient(create_app(settings))
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )

    response = client.post(
        "/v1/judges/rubric/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": fixture["trace"]["trace_id"],
            "judge": {
                "judge_id": "judge_wrong_tool_for_refund",
                "judge_type": "rubric_judge",
                "rubric": {"fail": "Wrong tool was used for the task."},
            },
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "model_unavailable"


def test_v1_trace_assertion_check_reports_deterministic_failures(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )

    response = client.post(
        "/v1/traces/trace_wrong_tool/assertions/check",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "assertions": {"forbidden_tools": ["order_lookup"]},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["failures"][0]["type"] == "forbidden_tool_used"
    assert body["failures"][0]["span_ids"] == ["span_wrong_tool_order_lookup"]


def test_v1_context_pack_cites_source_trace_and_span(tmp_path, monkeypatch) -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "issue_summary": "Refund issue",
                    "trace_summaries": [
                        {
                            "trace_id": "trace_wrong_tool",
                            "summary": "Order lookup was used.",
                            "evidence_span_ids": ["span_wrong_tool_order_lookup"],
                        }
                    ],
                    "tool_sequence_summary": "refund_agent then lookup_order",
                    "business_dimension_summary": "No dimensions supplied.",
                    "key_evidence": [
                        {
                            "claim": "wrong tool",
                            "trace_id": "trace_wrong_tool",
                            "span_ids": ["span_wrong_tool_order_lookup"],
                        }
                    ],
                    "uncertainty": "single fixture trace",
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": None,
                "repaired": False,
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    response = client.post(
        "/v1/context-packs",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "source_trace_ids": ["trace_wrong_tool"]},
    )
    assert response.status_code == 201
    content = response.json()["content"]
    assert content["model_metadata"]["summary_validation"]["status"] == "valid"
    assert content["summary"]["key_evidence"][0]["span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]
    fetched = client.get(
        f"/v1/context-packs/{response.json()['context_pack_id']}",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    assert fetched.status_code == 200


def test_v1_behavior_backtest_persists_matches_and_review_task(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    behavior = client.post(
        "/v1/behaviors",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "wrong_tool_for_refund",
            "description": "Refund workflow uses an unrelated order lookup.",
            "severity": "high",
            "detector": {
                "type": "rule",
                "scope": "span",
                "conditions": {
                    "combine": "all",
                    "items": [
                        {
                            "field": "attributes.tool.name",
                            "op": "eq",
                            "value": "order_lookup",
                        }
                    ],
                },
            },
        },
    )
    assert behavior.status_code == 201

    backtest = client.post(
        f"/v1/behaviors/{behavior.json()['behavior_id']}/backtest",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "filters": {"status": "error"}},
    )
    assert backtest.status_code == 200
    body = backtest.json()
    assert body["status"] == "succeeded"
    assert body["positive_count"] == 1
    assert body["positive_examples"][0]["evidence_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]
    assert body["persisted_behavior_matches"][0]["status"] == "backtest_positive"
    assert body["review_task"]["task_type"] == "behavior_candidate"

    matches = client.get(
        "/v1/behavior-matches",
        params={"project_id": "proj_demo", "trace_id": "trace_wrong_tool"},
        headers=auth_headers(),
    )
    assert matches.status_code == 200
    assert matches.json()["data"][0]["behavior_id"] == behavior.json()["behavior_id"]
    assert matches.json()["data"][0]["evidence_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]

    label = client.post(
        "/v1/traces/trace_wrong_tool/behavior-labels",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "behavior_id": behavior.json()["behavior_id"],
            "span_id_nullable": "span_wrong_tool_order_lookup",
        },
    )
    assert label.status_code == 201
    assert label.json()["behavior_match"]["status"] == "confirmed"
    assert label.json()["behavior_match"]["evidence_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]
    assert behavior.json()["behavior_id"] in label.json()["trace"]["attributes"][
        "openabm.behavior_ids"
    ]

    reviews = client.get(
        "/v1/review-tasks",
        params={"project_id": "proj_demo", "task_type": "behavior_candidate"},
        headers=auth_headers(),
    )
    assert reviews.status_code == 200
    assert reviews.json()["data"][0]["source_entity_id"] == behavior.json()["behavior_id"]


def test_v1_investigation_adds_model_assistance_with_citations(tmp_path, monkeypatch) -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "suspected_root_causes": [
                        {
                            "hypothesis": (
                                "Refund workflow selected order lookup instead of policy lookup."
                            ),
                            "evidence_trace_ids": ["trace_wrong_tool"],
                            "evidence_span_ids": ["span_wrong_tool_order_lookup"],
                            "confidence_or_uncertainty": "single trace fixture",
                        }
                    ],
                    "behavior_drafts": [
                        {
                            "name": "wrong_tool_for_refund",
                            "description": "Refund task uses an unrelated order lookup.",
                            "positive_trace_ids": ["trace_wrong_tool"],
                            "negative_trace_ids": [],
                        }
                    ],
                    "rubric_drafts": [
                        {
                            "name": "Wrong refund tool",
                            "pass": "Refund policy lookup or no lookup is appropriate.",
                            "fail": "Order lookup is used as the decisive refund tool.",
                            "unsure": "Trace lacks enough tool evidence.",
                            "evidence_trace_ids": ["trace_wrong_tool"],
                        }
                    ],
                    "recommended_next_actions": ["backtest wrong_tool_for_refund"],
                    "confidence_or_uncertainty": "single fixture trace",
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": None,
                "repaired": False,
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][1]
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    response = client.post(
        "/v1/investigations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "seed_trace_id_nullable": "trace_wrong_tool",
            "filters": {"status": "error"},
        },
    )
    assert response.status_code == 201
    orchestration = response.json()["result"]["orchestration"]
    assert orchestration["framework"] == "langgraph"
    assert orchestration["graph_version"] == "openabm_investigation_graph_v1"
    assert orchestration["structured_trace_ids"] == ["trace_wrong_tool"]
    assert [event["node"] for event in orchestration["tool_calls"]] == [
        "generate_candidate_search_queries",
        "run_structured_search",
        "run_full_text_search",
        "run_semantic_similarity_search",
        "persist_investigation_run",
    ]
    assert response.json()["result"]["semantic_similarity"] == {
        "status": "skipped",
        "reason": "no_similarity_index",
        "matches": [],
    }
    assert {event["status"] for event in orchestration["tool_calls"]} == {
        "skipped",
        "succeeded",
    }
    structured_event = orchestration["tool_calls"][1]
    assert structured_event["citations"] == ["trace_wrong_tool"]
    assert structured_event["resource_uris"] == ["trace://trace_wrong_tool"]
    persist_event = orchestration["tool_calls"][-1]
    assert f"investigation-run://{response.json()['investigation_run_id']}" in persist_event[
        "resource_uris"
    ]
    assert f"impact-report://{orchestration['tool_calls'][-1]['output']['impact_report_id']}" in (
        persist_event["resource_uris"]
    )
    assistance = response.json()["result"]["model_assistance"]
    assert assistance["suspected_root_causes"][0]["evidence_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]
    assert assistance["behavior_drafts"][0]["positive_trace_ids"] == ["trace_wrong_tool"]
    review_task_ids = response.json()["result"]["review_task_ids"]
    assert len(review_task_ids) == 2
    reviews = client.get(
        "/v1/review-tasks",
        params={"project_id": "proj_demo"},
        headers=auth_headers(),
    )
    task_types = {task["task_type"] for task in reviews.json()["data"]}
    assert {"root_cause_candidate", "behavior_candidate"} <= task_types
    mcp_reviews = call_tool(
        "list_review_tasks",
        {"project_id": "proj_demo", "task_type": "root_cause_candidate"},
        client=_TestClientMcpAdapter(client),
    )
    root_cause_task = mcp_reviews["data"][0]
    assert root_cause_task["task_type"] == "root_cause_candidate"
    mcp_review_update = call_tool(
        "update_review_task",
        {
            "project_id": "proj_demo",
            "review_task_id": root_cause_task["review_task_id"],
            "status": "needs_more_evidence",
            "decision": "needs_more_evidence",
            "notes": "Need one more trace before acting.",
            "confirmed": True,
        },
        client=_TestClientMcpAdapter(client),
    )
    assert mcp_review_update["decision_nullable"] == "needs_more_evidence"


def test_core_loop_acceptance_preserves_provenance_through_mcp(tmp_path, monkeypatch) -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "verdict": "fail",
                    "score": 0.0,
                    "confidence": 0.91,
                    "reasoning": "Order lookup was used for a refund-policy decision.",
                    "evidence_span_ids": ["span_wrong_tool_order_lookup"],
                    "failure_mode": "wrong_tool_for_refund",
                    "notes": None,
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "repaired": False,
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    corpus = json.loads(FIXTURE_PATH.read_text())
    client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [fixture["trace"] for fixture in corpus["fixtures"][:2]],
            "spans": [span for fixture in corpus["fixtures"][:2] for span in fixture["spans"]],
        },
    )

    judge_definition = {
        "judge_id": "judge_wrong_tool_acceptance",
        "judge_type": "rubric_judge",
        "name": "Wrong refund tool acceptance judge",
        "require_span_citations": True,
        "rubric": {
            "pass": "Refund workflow uses policy lookup or no inappropriate lookup.",
            "fail": "Refund workflow uses order lookup as the decisive tool.",
            "unsure": "The trace lacks enough tool evidence.",
        },
    }
    judge = client.post(
        "/v1/judges/drafts",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "Wrong refund tool acceptance judge",
            "judge_type": "rubric_judge",
            "definition": judge_definition,
            "trace_id": "trace_wrong_tool",
        },
    )
    assert judge.status_code == 201
    version = client.post(
        f"/v1/judges/{judge.json()['judge_id']}/versions",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "definition": judge_definition},
    )
    assert version.status_code == 201
    judge_definition["judge_id"] = judge.json()["judge_id"]
    judge_definition["judge_version_id"] = version.json()["judge_version_id"]

    score = client.post(
        "/v1/judges/rubric/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": "trace_wrong_tool",
            "judge": judge_definition,
        },
    )
    assert score.status_code == 201
    assert score.json()["status"] == "succeeded"
    assert score.json()["evidence_span_ids"] == ["span_wrong_tool_order_lookup"]

    behavior = client.post(
        "/v1/behaviors",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "wrong_tool_for_refund",
            "severity": "high",
            "detector": {
                "type": "rule",
                "scope": "span",
                "match_semantics": "any_match_is_behavior",
                "conditions": {
                    "combine": "all",
                    "items": [
                        {
                            "field": "attributes.tool.name",
                            "op": "eq",
                            "value": "order_lookup",
                        }
                    ],
                },
            },
        },
    )
    assert behavior.status_code == 201
    backtest = client.post(
        f"/v1/behaviors/{behavior.json()['behavior_id']}/backtest",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "filters": {"status": "error"}},
    )
    assert backtest.status_code == 200
    assert backtest.json()["positive_examples"][0]["trace_id"] == "trace_wrong_tool"
    assert backtest.json()["positive_examples"][0]["evidence_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]

    dataset = client.post(
        "/v1/datasets",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "name": "Core loop eval"},
    )
    assert dataset.status_code == 201
    example = client.post(
        f"/v1/datasets/{dataset.json()['dataset_id']}/examples/from-trace",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "trace_id": "trace_wrong_tool",
            "labels": ["wrong_tool_for_refund"],
        },
    )
    assert example.status_code == 201
    assert example.json()["source_trace_id"] == "trace_wrong_tool"

    baseline = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "dataset_version_id": dataset.json()["latest_version_id"],
            "judges": [_wrong_tool_judge()],
        },
    )
    candidate = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "dataset_version_id": dataset.json()["latest_version_id"],
            "judges": [_wrong_tool_judge()],
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
        },
    )
    assert baseline.status_code == 201
    assert candidate.status_code == 201
    assert candidate.json()["results"][0]["offline_trace_id"] == "trace_wrong_tool"
    comparison = client.post(
        "/v1/evals/compare",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
            "candidate_eval_run_id": candidate.json()["eval_run_id"],
        },
    )
    assert comparison.status_code == 200
    assert comparison.json()["baseline_eval_run_id"] == baseline.json()["eval_run_id"]

    mcp_trace = call_tool(
        "get_trace",
        {"project_id": "proj_demo", "trace_id": "trace_wrong_tool"},
        client=_TestClientMcpAdapter(client),
    )
    mcp_context_pack = call_tool(
        "create_agent_context_pack",
        {
            "project_id": "proj_demo",
            "source_trace_ids": ["trace_wrong_tool"],
            "allowed_next_actions": ["inspect_trace", "draft_fix"],
        },
        client=_TestClientMcpAdapter(client),
    )
    scores = client.get(
        "/v1/scores",
        headers=auth_headers(),
        params={"project_id": "proj_demo", "trace_id": "trace_wrong_tool"},
    )
    assert scores.json()["data"][0]["score_id"] == score.json()["score_id"]
    assert mcp_trace["trace"]["trace_id"] == "trace_wrong_tool"
    assert mcp_context_pack["source_trace_ids"] == ["trace_wrong_tool"]
    assert mcp_trace["reconstruction"]["span_tree"][0]["children"][0]["span"][
        "span_id"
    ] == "span_wrong_tool_order_lookup"
    mcp_observations = client.get(
        "/v1/ops/mcp-tool-observations",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    mcp_row = next(
        row for row in mcp_observations.json()["data"] if row["tool_name"] == "get_trace"
    )
    assert mcp_row["request"]["trace_id"] == "trace_wrong_tool"
    assert mcp_row["response"]["trace"]["trace_id"] == "trace_wrong_tool"
    assert "trace_wrong_tool" in mcp_row["citations"]


def test_reported_incident_investigation_acceptance_links_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "suspected_root_causes": [
                        {
                            "hypothesis": (
                                "Refund traces used order lookup while asserting customer "
                                "commitment values without policy evidence."
                            ),
                            "evidence_trace_ids": [
                                "trace_wrong_tool",
                                "trace_fabricated_commitment",
                            ],
                            "evidence_span_ids": [
                                "span_wrong_tool_order_lookup",
                                "span_fabricated_commitment_order_lookup",
                            ],
                            "confidence_or_uncertainty": "two fixture traces with same tool path",
                        }
                    ],
                    "behavior_drafts": [
                        {
                            "name": "fabricated_commitment_after_order_lookup",
                            "description": (
                                "Refund task reaches order lookup before making a customer "
                                "commitment claim."
                            ),
                            "positive_trace_ids": [
                                "trace_wrong_tool",
                                "trace_fabricated_commitment",
                            ],
                            "negative_trace_ids": ["trace_happy_support"],
                        }
                    ],
                    "rubric_drafts": [
                        {
                            "name": "Unsupported customer commitment",
                            "pass": "Customer commitment values are grounded in policy evidence.",
                            "fail": "The trace makes a commitment after unrelated order lookup.",
                            "unsure": "Trace lacks commitment or policy evidence.",
                            "evidence_trace_ids": [
                                "trace_wrong_tool",
                                "trace_fabricated_commitment",
                            ],
                        }
                    ],
                    "recommended_next_actions": [
                        "Backtest the candidate behavior.",
                        "Create a regression dataset from matching traces.",
                    ],
                    "confidence_or_uncertainty": "fixture-scale incident cohort",
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": {"total_tokens": 321},
                "repaired": False,
            }

    monkeypatch.setattr(
        "openabm_api.main.model_provider_from_settings",
        lambda settings: StubProvider(),
    )
    client = make_client(tmp_path)
    corpus = json.loads(FIXTURE_PATH.read_text())
    happy = corpus["fixtures"][0]
    wrong = corpus["fixtures"][1]
    fabricated = _clone_trace_fixture(
        wrong,
        trace_id="trace_fabricated_commitment",
        session_id="session_fabricated_commitment",
        span_id_map={
            "span_wrong_tool_root": "span_fabricated_commitment_root",
            "span_wrong_tool_order_lookup": "span_fabricated_commitment_order_lookup",
        },
        summary="Agent fabricated a customer commitment value after order lookup.",
    )
    ingest = client.post(
        "/v1/ingest/batch",
        headers=auth_headers(),
        json={
            "traces": [happy["trace"], wrong["trace"], fabricated["trace"]],
            "spans": [*happy["spans"], *wrong["spans"], *fabricated["spans"]],
        },
    )
    assert ingest.status_code == 207
    for trace_id, values in {
        "trace_wrong_tool": {
            "task_type": "refund",
            "workflow": "refund_commitment",
            "account_id": "acct_enterprise_1",
            "plan": "enterprise",
        },
        "trace_fabricated_commitment": {
            "task_type": "refund",
            "workflow": "refund_commitment",
            "account_id": "acct_enterprise_1",
            "plan": "enterprise",
        },
        "trace_happy_support": {
            "task_type": "policy_lookup",
            "workflow": "refund_policy",
            "account_id": "acct_starter_2",
            "plan": "starter",
        },
    }.items():
        for key, value in values.items():
            response = client.post(
                "/v1/trace-dimensions",
                headers=auth_headers(),
                json={
                    "project_id": "proj_demo",
                    "trace_id": trace_id,
                    "key": key,
                    "value": value,
                },
            )
            assert response.status_code == 201

    behavior = client.post(
        "/v1/behaviors",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "wrong_tool_for_refund",
            "description": "Refund workflow uses an unrelated order lookup.",
            "severity": "high",
            "detector": {
                "type": "rule",
                "scope": "span",
                "conditions": {
                    "combine": "all",
                    "items": [
                        {
                            "field": "attributes.tool.name",
                            "op": "eq",
                            "value": "order_lookup",
                        }
                    ],
                },
            },
        },
    )
    assert behavior.status_code == 201
    behavior_id = behavior.json()["behavior_id"]
    label = client.post(
        "/v1/traces/trace_wrong_tool/behavior-labels",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "behavior_id": behavior_id,
            "span_id_nullable": "span_wrong_tool_order_lookup",
        },
    )
    assert label.status_code == 201

    issue = client.post(
        "/v1/issues",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "title": "agent fabricated a customer commitment value",
            "description": "Customer-facing refund flow promised an unsupported commitment.",
            "seed_trace_id_nullable": "trace_wrong_tool",
        },
    )
    assert issue.status_code == 201
    issue_id = issue.json()["issue_id"]
    investigation = client.post(
        "/v1/investigations",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "issue_id_nullable": issue_id,
            "seed_trace_id_nullable": "trace_wrong_tool",
            "natural_language_problem_nullable": (
                "agent fabricated a customer commitment value"
            ),
            "filters": {"status": "error"},
        },
    )
    assert investigation.status_code == 201
    result = investigation.json()["result"]
    impact = result["impact_report"]
    assert set(result["evidence_trace_ids"]) == {
        "trace_wrong_tool",
        "trace_fabricated_commitment",
    }
    assert impact["matching_trace_count"] == 2
    assert impact["task_type_distribution"] == {"refund": 2}
    assert impact["dimension_distribution"]["workflow"] == {"refund_commitment": 2}
    assert impact["behavior_distribution"][behavior_id]["name"] == "wrong_tool_for_refund"
    assert impact["behavior_distribution"][behavior_id]["match_count"] == 1
    assert impact["behavior_distribution"][behavior_id]["status_counts"] == {"confirmed": 1}
    assert impact["behavior_distribution"][behavior_id]["trace_ids"] == ["trace_wrong_tool"]
    assert impact["affected_entity_count"] == 1
    assert impact["affected_entities"][0]["entity_id"] == "acct_enterprise_1"
    affected_entities = client.get(
        "/v1/affected-entities",
        headers=auth_headers(),
        params={"project_id": "proj_demo", "issue_id": issue_id},
    )
    assert affected_entities.status_code == 200
    affected_entity = affected_entities.json()["data"][0]
    assert affected_entity["entity_id"] == "acct_enterprise_1"
    assert set(affected_entity["trace_ids"]) == {
        "trace_wrong_tool",
        "trace_fabricated_commitment",
    }
    fetched_affected = client.get(
        f"/v1/affected-entities/{affected_entity['affected_entity_id']}",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert fetched_affected.status_code == 200
    assert fetched_affected.json()["affected_entity_id"] == affected_entity[
        "affected_entity_id"
    ]
    remediated = client.patch(
        f"/v1/affected-entities/{affected_entity['affected_entity_id']}",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "status": "fixed",
            "owner_nullable": "support-ops",
            "notes_nullable": "Customer commitment corrected.",
        },
    )
    assert remediated.status_code == 200
    assert remediated.json()["status"] == "fixed"
    mcp_affected = call_tool(
        "list_affected_entities",
        {"project_id": "proj_demo", "issue_id": issue_id},
        client=_TestClientMcpAdapter(client),
    )
    assert mcp_affected["data"][0]["affected_entity_id"] == affected_entity["affected_entity_id"]
    mcp_single_affected = call_tool(
        "get_affected_entity",
        {
            "project_id": "proj_demo",
            "affected_entity_id": affected_entity["affected_entity_id"],
        },
        client=_TestClientMcpAdapter(client),
    )
    assert mcp_single_affected["affected_entity_id"] == affected_entity["affected_entity_id"]
    affected_resource = read_resource(
        f"affected-entity://{affected_entity['affected_entity_id']}?project_id=proj_demo",
        client=_TestClientMcpAdapter(client),
    )
    assert json.loads(affected_resource["text"])["affected_entity_id"] == affected_entity[
        "affected_entity_id"
    ]
    mcp_remediated = call_tool(
        "update_affected_entity",
        {
            "project_id": "proj_demo",
            "affected_entity_id": affected_entity["affected_entity_id"],
            "status": "contacted",
            "owner_nullable": "support-ops",
            "notes_nullable": "MCP remediation update.",
            "remediation_target_type": "deployment_context",
            "remediation_target_id": "deploy_refund_runtime_v2",
            "confirmed": True,
        },
        client=_TestClientMcpAdapter(client),
    )
    assert mcp_remediated["status"] == "contacted"
    assert set(impact["representative_trace_ids"]) == {
        "trace_wrong_tool",
        "trace_fabricated_commitment",
    }
    assert result["model_assistance"]["suspected_root_causes"][0][
        "evidence_span_ids"
    ] == [
        "span_wrong_tool_order_lookup",
        "span_fabricated_commitment_order_lookup",
    ]
    assert set(result["model_assistance"]["behavior_drafts"][0]["positive_trace_ids"]) == {
        "trace_wrong_tool",
        "trace_fabricated_commitment",
    }

    behavior = client.post(
        "/v1/behaviors",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "issue_id_nullable": issue_id,
            "name": "fabricated_commitment_after_order_lookup",
            "description": "Refund commitment incident uses order lookup evidence.",
            "severity": "high",
            "evidence_trace_ids": [
                "trace_wrong_tool",
                "trace_fabricated_commitment",
            ],
            "evidence_span_ids": [
                "span_wrong_tool_order_lookup",
                "span_fabricated_commitment_order_lookup",
            ],
            "detector": {
                "type": "rule",
                "scope": "span",
                "match_semantics": "any_match_is_behavior",
                "conditions": {
                    "combine": "all",
                    "items": [
                        {
                            "field": "attributes.tool.name",
                            "op": "eq",
                            "value": "order_lookup",
                        }
                    ],
                },
            },
        },
    )
    assert behavior.status_code == 201
    backtest = client.post(
        f"/v1/behaviors/{behavior.json()['behavior_id']}/backtest",
        headers=auth_headers(),
        json={"project_id": "proj_demo", "filters": {"status": "error"}},
    )
    assert backtest.status_code == 200
    assert {item["trace_id"] for item in backtest.json()["positive_examples"]} == {
        "trace_wrong_tool",
        "trace_fabricated_commitment",
    }

    judge = client.post(
        "/v1/judges/drafts",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "name": "Unsupported customer commitment",
            "judge_type": "deterministic_rule",
            "definition": _wrong_tool_judge(),
            "trace_id": "trace_fabricated_commitment",
        },
    )
    assert judge.status_code == 201
    issue_judge_link = client.post(
        f"/v1/issues/{issue_id}/links",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "target_type": "judge",
            "target_id": judge.json()["judge_id"],
            "relation": "proposed_judge",
            "source": "acceptance_test",
            "evidence_trace_ids": ["trace_fabricated_commitment"],
            "evidence_span_ids": ["span_fabricated_commitment_order_lookup"],
        },
    )
    assert issue_judge_link.status_code == 201

    dataset = client.post(
        "/v1/datasets",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "issue_id_nullable": issue_id,
            "name": "Fabricated commitment regression",
        },
    )
    assert dataset.status_code == 201
    examples = []
    for trace_id in ["trace_wrong_tool", "trace_fabricated_commitment"]:
        example = client.post(
            f"/v1/datasets/{dataset.json()['dataset_id']}/examples/from-trace",
            headers=auth_headers(),
            json={
                "project_id": "proj_demo",
                "issue_id_nullable": issue_id,
                "trace_id": trace_id,
                "labels": ["fabricated_commitment_after_order_lookup"],
            },
        )
        assert example.status_code == 201
        examples.append(example.json())
    assert {example["source_trace_id"] for example in examples} == {
        "trace_wrong_tool",
        "trace_fabricated_commitment",
    }

    baseline = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "issue_id_nullable": issue_id,
            "dataset_version_id": dataset.json()["latest_version_id"],
            "judges": [_wrong_tool_judge()],
        },
    )
    candidate = client.post(
        "/v1/evals/run",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "issue_id_nullable": issue_id,
            "dataset_version_id": dataset.json()["latest_version_id"],
            "judges": [_wrong_tool_judge()],
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
        },
    )
    assert baseline.status_code == 201
    assert candidate.status_code == 201
    fixed_by_eval = client.patch(
        f"/v1/affected-entities/{affected_entity['affected_entity_id']}",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "status": "fixed",
            "remediation_target_type": "eval_run",
            "remediation_target_id": candidate.json()["eval_run_id"],
        },
    )
    assert fixed_by_eval.status_code == 200
    invalid_remediation_target = client.patch(
        f"/v1/affected-entities/{affected_entity['affected_entity_id']}",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "remediation_target_type": "prompt_version",
            "remediation_target_id": "prompt_version_1",
        },
    )
    assert invalid_remediation_target.status_code == 400
    comparison = client.post(
        "/v1/evals/compare",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "baseline_eval_run_id": baseline.json()["eval_run_id"],
            "candidate_eval_run_id": candidate.json()["eval_run_id"],
        },
    )
    assert comparison.status_code == 200
    issue_links = client.get(
        f"/v1/issues/{issue_id}/links",
        headers=auth_headers(),
        params={"project_id": "proj_demo"},
    )
    assert issue_links.status_code == 200
    links = issue_links.json()["data"]
    linked_targets = {(link["target_type"], link["target_id"]) for link in links}
    assert {
        ("investigation_run", investigation.json()["investigation_run_id"]),
        ("impact_report", impact["report_id"]),
        ("affected_entity", affected_entity["affected_entity_id"]),
        ("behavior", behavior.json()["behavior_id"]),
        ("judge", judge.json()["judge_id"]),
        ("dataset", dataset.json()["dataset_id"]),
        ("eval_run", baseline.json()["eval_run_id"]),
        ("eval_run", candidate.json()["eval_run_id"]),
        ("deployment_context", "deploy_refund_runtime_v2"),
    } <= linked_targets
    remediation_links = [
        link
        for link in links
        if link["relation"] == "remediated_by"
        and link["source"] == "affected_entity_remediation"
    ]
    assert {
        (link["target_type"], link["target_id"]) for link in remediation_links
    } >= {
        ("eval_run", candidate.json()["eval_run_id"]),
        ("deployment_context", "deploy_refund_runtime_v2"),
    }
    assert {
        link["metadata"]["affected_entity_id"] for link in remediation_links
    } == {affected_entity["affected_entity_id"]}
    assert {
        link["target_type"]
        for link in links
        if link["relation"] in {"evidence_example", "regression_dataset"}
    } >= {"dataset", "dataset_example"}


class _TestClientMcpAdapter:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def request(self, method, path, *, params=None, json_body=None):
        response = self.client.request(
            method,
            path,
            params=params,
            json=json_body,
            headers=auth_headers(),
        )
        assert response.status_code < 400, response.text
        return response.json()


def _wrong_tool_judge() -> dict[str, object]:
    return {
        "judge_id": "judge_wrong_tool_for_refund",
        "judge_type": "deterministic_rule",
        "rule": {
            "match_semantics": "any_match_is_fail",
            "failure_mode": "wrong_tool_for_refund",
            "conditions": {
                "combine": "all",
                "items": [{"field": "attributes.tool.name", "op": "eq", "value": "order_lookup"}],
            },
        },
    }


def _order_lookup_present_judge() -> dict[str, object]:
    return {
        "judge_id": "judge_order_lookup_present",
        "judge_type": "deterministic_rule",
        "rule": {
            "match_semantics": "any_match_is_pass",
            "conditions": {
                "combine": "all",
                "items": [{"field": "attributes.tool.name", "op": "eq", "value": "order_lookup"}],
            },
        },
    }


def _clone_trace_fixture(
    fixture: dict[str, object],
    *,
    trace_id: str,
    session_id: str,
    span_id_map: dict[str, str],
    summary: str,
) -> dict[str, object]:
    clone = json.loads(json.dumps(fixture))
    clone["trace"]["trace_id"] = trace_id
    clone["trace"]["session_id"] = session_id
    clone["trace"]["root_span_id"] = span_id_map[clone["trace"]["root_span_id"]]
    clone["trace"]["summary"] = summary
    clone["trace"]["attributes"] = {
        **clone["trace"].get("attributes", {}),
        "incident.kind": "fabricated_customer_commitment",
    }
    for span in clone["spans"]:
        span["trace_id"] = trace_id
        if span["span_id"] in span_id_map:
            span["span_id"] = span_id_map[span["span_id"]]
        if span.get("parent_span_id") in span_id_map:
            span["parent_span_id"] = span_id_map[span["parent_span_id"]]
        if span["span_id"] == span_id_map["span_wrong_tool_order_lookup"]:
            span["attributes"] = {
                **span.get("attributes", {}),
                "claim.text": "customer commitment value",
            }
    return clone
