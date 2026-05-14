from __future__ import annotations

import asyncio
import json

from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore
from openabm_worker.synthetic_pilot import (
    COMPANY_WORKFLOWS,
    DEFAULT_PROJECT_ID,
    PILOT_JUDGE_FAILURE_MODES,
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


def test_synthetic_pilot_applies_model_generated_conversation_feedback(tmp_path) -> None:
    class ConversationProvider:
        adapter_name = "stub-conversation-provider"

        async def tool_completion(self, request, tools):
            assert request["tool_choice"]["function"]["name"] == (
                "submit_synthetic_agent_conversations"
            )
            assert tools[0]["function"]["name"] == "submit_synthetic_agent_conversations"
            return {
                "status": "succeeded",
                "tool_calls": [
                    {
                        "name": "submit_synthetic_agent_conversations",
                        "arguments": {
                            "conversations": [
                                {
                                    "scenario_name": "generated enterprise refund loop",
                                    "workflow": "refund",
                                    "customer_tier": "enterprise",
                                    "status": "error",
                                    "summary": (
                                        "Generated agent conversation used the wrong "
                                        "refund tool and missed escalation."
                                    ),
                                    "turns": [
                                        {
                                            "role": "user",
                                            "content": "Our enterprise refund is blocking launch.",
                                        },
                                        {
                                            "role": "agent",
                                            "content": (
                                                "I checked order status but did not escalate."
                                            ),
                                        },
                                    ],
                                    "tool_calls": [
                                        {
                                            "tool_name": "order_lookup",
                                            "input": {"order_id": "synthetic-100"},
                                            "output": {"status": "delivered"},
                                            "success": True,
                                            "failure_mode": "wrong_tool",
                                        }
                                    ],
                                    "expected_failure_modes": [
                                        "wrong_tool",
                                        "missed_escalation",
                                    ],
                                    "grounding_claim_text": None,
                                    "feedback": (
                                        "OpenABM should convert this generated "
                                        "conversation into eval labels and behavior review."
                                    ),
                                }
                            ]
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "provider": "stub",
                "model": "stub-model",
            }

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        payload_dir=tmp_path / "payloads",
    )
    store = SQLiteStore(settings.sqlite_path)

    report = asyncio.run(
        run_synthetic_pilot(
            store,
            settings=settings,
            config=SyntheticPilotConfig(
                trace_count=8,
                generate_agent_conversations=True,
                generated_conversation_count=1,
            ),
            model_provider=ConversationProvider(),
        )
    )

    generated = report["results"]["agent_generated_conversations"]
    assert generated["status"] == "completed"
    assert generated["fixture_count"] == 1
    assert report["trace_count"] == 9
    assert report["validations"]["checks"]["agent_generated_conversations_ingested"] is True
    assert report["validations"]["checks"]["agent_generated_feedback_applied"] is True
    assert any(
        action["action"] == "converted_model_feedback_to_dataset_labels"
        for action in generated["feedback_actions"]
    )
    trace = store.get_trace(
        DEFAULT_PROJECT_ID,
        "trace_agentgen_20260514_000_generated_enterprise_refund_loop",
    )
    assert trace is not None
    assert trace["attributes"]["synthetic_source"] == "model_generated_agent_conversation"


def test_synthetic_company_simulation_exercises_workflow_and_failure_coverage(
    tmp_path,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}",
        payload_dir=tmp_path / "payloads",
    )
    store = SQLiteStore(settings.sqlite_path)

    report = asyncio.run(
        run_synthetic_pilot(
            store,
            settings=settings,
            config=SyntheticPilotConfig(
                trace_count=8,
                company_simulation=True,
                company_trace_count=120,
                company_days=4,
            ),
        )
    )

    company = report["results"]["company_simulation"]
    assert company["status"] == "completed"
    assert company["trace_count"] == 120
    assert set(company["workflow_counts"]) >= set(COMPANY_WORKFLOWS)
    assert set(company["failure_counts"]) >= set(PILOT_JUDGE_FAILURE_MODES)
    assert report["trace_count"] == 128
    assert report["validations"]["checks"]["company_simulation_volume_met"] is True
    assert report["validations"]["checks"]["company_simulation_workflow_coverage"] is True
    assert report["validations"]["checks"]["company_simulation_failure_coverage"] is True
    assert report["validations"]["checks"]["company_simulation_eval_scale"] is True
    traces = store.search_traces(
        DEFAULT_PROJECT_ID,
        filters={"environment": "synthetic-company"},
        limit=5,
    )
    assert traces
