import json
from pathlib import Path

from fastapi.testclient import TestClient
from openabm_api.main import create_app
from openabm_api.settings import Settings
from openabm_worker.offline_eval import run_deterministic_eval

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
    store.add_trace_to_dataset("proj_demo", dataset["dataset_id"], fixture["trace"]["trace_id"])
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
    assert response.json()["evidence_span_ids"] == ["span_wrong_tool_order_lookup"]
    scores = client.get(
        "/v1/scores",
        params={"project_id": "proj_demo", "trace_id": fixture["trace"]["trace_id"]},
        headers=auth_headers(),
    )
    assert scores.json()["data"][0]["cost"]["model"] == "stub-model"


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
    assistance = response.json()["result"]["model_assistance"]
    assert assistance["suspected_root_causes"][0]["evidence_span_ids"] == [
        "span_wrong_tool_order_lookup"
    ]
    assert assistance["behavior_drafts"][0]["positive_trace_ids"] == ["trace_wrong_tool"]


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
