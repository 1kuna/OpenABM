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


def test_search_similar_fails_closed_without_embeddings(tmp_path) -> None:
    client = make_client(tmp_path)
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
