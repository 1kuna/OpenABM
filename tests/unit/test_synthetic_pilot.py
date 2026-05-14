from __future__ import annotations

import asyncio
import json

from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore
from openabm_worker.synthetic_pilot import (
    DEFAULT_PROJECT_ID,
    RuntimeSurface,
    SyntheticPilotConfig,
    build_synthetic_pilot_fixtures,
    run_synthetic_pilot,
)


def test_synthetic_pilot_fixtures_cover_real_world_failure_shapes() -> None:
    baseline = RuntimeSurface(
        prompt_version_id="prompt_baseline",
        agent_config_version_id="config_baseline",
        deployment_context_id="deploy_baseline",
        tool_version_ids=["policy_lookup@1"],
    )
    candidate = RuntimeSurface(
        prompt_version_id="prompt_candidate",
        agent_config_version_id="config_candidate",
        deployment_context_id="deploy_candidate",
        tool_version_ids=["order_lookup@2"],
    )

    fixtures = build_synthetic_pilot_fixtures(
        SyntheticPilotConfig(trace_count=8),
        baseline_runtime=baseline,
        candidate_runtime=candidate,
    )

    names = {fixture["name"] for fixture in fixtures}
    statuses = {fixture["trace"]["status"] for fixture in fixtures}
    assert {
        "wrong_tool_refund",
        "missed_escalation_enterprise",
        "hallucinated_delivery_status",
        "checkout_loop_timeout",
        "pii_overexposure",
    } <= names
    assert {"ok", "error", "failed", "timeout"} <= statuses
    assert any(fixture["expected"]["grounding_claim_text"] for fixture in fixtures)


def test_synthetic_pilot_runs_local_reference_surfaces(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        payload_dir=tmp_path / "payloads",
    )
    store = SQLiteStore(settings.sqlite_path)
    output_dir = tmp_path / "synthetic-pilot"

    report = asyncio.run(
        run_synthetic_pilot(
            store,
            settings=settings,
            config=SyntheticPilotConfig(trace_count=8, output_dir=output_dir),
        )
    )

    assert report["status"] == "completed_with_expected_findings"
    assert report["validations"]["critical_failure_count"] == 0
    assert report["validations"]["checks"]["deterministic_eval_surfaced_failures"] is True
    assert report["validations"]["checks"]["grounding_needs_review"] is True
    assert report["results"]["model_lanes"]["status"] == "skipped"
    assert store.search_traces(DEFAULT_PROJECT_ID, limit=20)
    assert store.list_review_tasks(DEFAULT_PROJECT_ID)
    assert output_dir.joinpath("report.json").exists()
    persisted = json.loads(output_dir.joinpath("report.json").read_text())
    assert persisted["run_id"] == report["run_id"]
