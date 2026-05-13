import json
from pathlib import Path

from openabm_api.storage import SQLiteStore, ingest_fixture
from openabm_worker.retention import run_retention_once

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"


def test_retention_worker_dry_run_and_apply_records_heartbeat(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "openabm.sqlite3")
    store.init_db()
    corpus = json.loads(FIXTURE_PATH.read_text())
    ingest_fixture(store, [corpus["fixtures"][0]])
    policy = store.create_retention_policy(
        {
            "project_id": "proj_demo",
            "name": "Immediate trace retention",
            "status": "active",
            "rules": [{"entity": "traces", "ttl_days": 0}],
        }
    )

    planned = run_retention_once(
        store,
        project_id="proj_demo",
        dry_run=True,
        worker_id="retention-test-worker",
    )

    assert planned["status"] == "succeeded"
    assert planned["dry_run"] is True
    assert planned["policy_count"] == 1
    assert planned["results"][0]["retention_policy_id"] == policy["retention_policy_id"]
    assert planned["results"][0]["candidate_trace_ids"] == ["trace_happy_support"]
    assert store.get_trace("proj_demo", "trace_happy_support")["status"] == "ok"

    applied = run_retention_once(
        store,
        project_id="proj_demo",
        dry_run=False,
        worker_id="retention-test-worker",
    )

    assert applied["status"] == "succeeded"
    assert applied["deleted_trace_count"] == 1
    assert applied["results"][0]["deleted_trace_ids"] == ["trace_happy_support"]
    assert store.get_trace("proj_demo", "trace_happy_support")["status"] == "deleted"
    heartbeat = store.list_worker_heartbeats("proj_demo")[0]
    assert heartbeat["worker_id"] == "retention-test-worker"
    assert heartbeat["worker_type"] == "retention"
    assert heartbeat["status"] == "ok"
    assert heartbeat["details"]["applied_policy_count"] == 1
    ops_status = store.ops_status("proj_demo")
    assert ops_status["retention_job_status"]["target_id"] == policy["retention_policy_id"]
