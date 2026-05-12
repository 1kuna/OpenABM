import json
from pathlib import Path

from fastapi.testclient import TestClient
from openabm_api.main import create_app
from openabm_api.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer dev-openabm-key"}


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}")
    return TestClient(create_app(settings))


def test_batch_ingest_and_trace_detail(tmp_path) -> None:
    client = make_client(tmp_path)
    fixture = json.loads(FIXTURE_PATH.read_text())["fixtures"][0]
    response = client.post(
        "/api/ingest/batch",
        headers=auth_headers(),
        json={"traces": [fixture["trace"]], "spans": fixture["spans"]},
    )
    assert response.status_code == 207
    assert response.json()["accepted"] == 1 + len(fixture["spans"])

    detail = client.get(
        f"/api/traces/{fixture['trace']['trace_id']}",
        params={"project_id": fixture["trace"]["project_id"]},
        headers=auth_headers(),
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["trace"]["trace_id"] == fixture["trace"]["trace_id"]
    assert body["reconstruction"]["span_tree"][0]["span"]["span_id"] == "span_happy_root"


def test_invalid_span_gets_partial_success_rejection(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/api/ingest/batch",
        headers=auth_headers(),
        json={"spans": [{"span_id": "missing-required-fields"}]},
    )
    assert response.status_code == 207
    body = response.json()
    assert body["status"] == "failed"
    assert body["rejected"] == 1
    assert body["items"][0]["error"]["code"] == "schema_validation_failed"


def test_search_similar_fails_closed_without_embeddings(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/api/search/similar",
        headers=auth_headers(),
        json={
            "project_id": "proj_demo",
            "source_id": "trace_missing_parent",
            "source_type": "trace",
        },
    )
    assert response.status_code == 200
    assert response.json()["disabled"] is True
