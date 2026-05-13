import json
from pathlib import Path

from jsonschema import Draft202012Validator
from openabm_api.main import create_app
from openabm_api.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "packages" / "shared-types" / "schemas"
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"
OPENAPI_PATH = ROOT / "packages" / "shared-types" / "openapi" / "openapi.json"

REQUIRED_SCHEMAS = {
    "trace-envelope.schema.json",
    "span-envelope.schema.json",
    "trace-event.schema.json",
    "payload-object.schema.json",
    "judge-definition.schema.json",
    "judge-version.schema.json",
    "score-result.schema.json",
    "behavior-definition.schema.json",
    "behavior-match.schema.json",
    "automation-definition.schema.json",
    "automation-run.schema.json",
    "dataset-definition.schema.json",
    "dataset-example.schema.json",
    "eval-run-config.schema.json",
    "eval-result.schema.json",
    "prompt-definition.schema.json",
    "prompt-version.schema.json",
    "secret-reference.schema.json",
    "mcp-tool-request.schema.json",
    "mcp-tool-response.schema.json",
    "trace-dimension.schema.json",
    "deployment-context.schema.json",
    "code-context.schema.json",
    "saved-search.schema.json",
    "review-task.schema.json",
    "notification-target.schema.json",
    "data-classification-policy.schema.json",
    "retention-policy.schema.json",
    "export-manifest.schema.json",
    "agent-config.schema.json",
    "agent-config-version.schema.json",
    "tool-definition.schema.json",
    "tool-version.schema.json",
    "retrieval-config.schema.json",
    "guardrail-config.schema.json",
    "memory-config.schema.json",
    "runtime-routing-config.schema.json",
    "issue-definition.schema.json",
    "issue-link.schema.json",
    "investigation-run.schema.json",
    "impact-report.schema.json",
    "affected-entity.schema.json",
    "agent-context-pack.schema.json",
    "grounding-check.schema.json",
    "novel-behavior-detection-run.schema.json",
}

REQUIRED_INGEST_PATHS = {
    "/v1/ingest/traces",
    "/v1/ingest/spans",
    "/v1/ingest/events",
    "/v1/ingest/feedback",
    "/v1/ingest/payloads",
    "/v1/ingest/batch",
}

REQUIRED_QUERY_PATHS = {
    "/v1/projects",
    "/v1/auth/api-keys",
    "/v1/auth/api-keys/{api_key_id}/revoke",
    "/v1/auth/contract",
    "/v1/auth/decision-records",
    "/v1/auth/invites",
    "/v1/auth/me",
    "/v1/auth/project-memberships",
    "/v1/auth/sessions",
    "/v1/auth/sessions/{auth_session_id}/revoke",
    "/v1/auth/users",
    "/v1/secrets",
    "/v1/secrets/backend",
    "/v1/secrets/{secret_ref}/access-log",
    "/v1/secrets/{secret_ref}/resolve",
    "/v1/secrets/{secret_ref}/rotate",
    "/v1/ops/dead-letter",
    "/v1/ops/mcp-tool-observations",
    "/v1/ops/status",
    "/v1/ops/worker-heartbeats",
    "/v1/traces",
    "/v1/traces/{trace_id}",
    "/v1/traces/{trace_id}/assertions/check",
    "/v1/traces/{trace_id}/behavior-labels",
    "/v1/traces/{trace_id}/spans",
    "/v1/spans/{span_id}",
    "/v1/sessions",
    "/v1/search/traces",
    "/v1/search/spans",
    "/v1/search/similar",
    "/v1/evals",
    "/v1/evals/analytics",
    "/v1/evals/run",
    "/v1/evals/{eval_run_id}",
    "/v1/evals/{eval_run_id}/results",
    "/v1/evals/compare",
    "/v1/judges",
    "/v1/judges/{judge_id}",
    "/v1/judges/drafts",
    "/v1/judges/{judge_id}/versions",
    "/v1/judges/rubric/run",
    "/v1/docs/search",
    "/v1/scores",
    "/v1/sessions/{session_id}",
    "/v1/behaviors",
    "/v1/behaviors/{behavior_id}",
    "/v1/behaviors/{behavior_id}/backtest",
    "/v1/behavior-matches",
    "/v1/review-tasks",
    "/v1/review-tasks/{review_task_id}",
    "/v1/datasets/{dataset_id}",
    "/v1/deployment-contexts",
    "/v1/deployment-contexts/{deployment_context_id}",
    "/v1/issues/{issue_id}",
    "/v1/issues/{issue_id}/links",
    "/v1/issues/from-screenshot",
    "/v1/chatops/investigate",
    "/v1/context-packs/{context_pack_id}",
    "/v1/investigations/{investigation_run_id}",
    "/v1/impact-reports/{report_id}",
    "/v1/affected-entities",
    "/v1/affected-entities/{affected_entity_id}",
    "/v1/retention-policies",
    "/v1/exports/project",
    "/v1/prompts",
    "/v1/prompts/{prompt_id}",
    "/v1/prompts/{prompt_id}/versions",
    "/v1/prompts/{prompt_id}/render",
    "/v1/prompts/{prompt_id}/diff",
    "/v1/agent-configs",
    "/v1/agent-configs/{agent_config_id}",
    "/v1/agent-configs/{agent_config_id}/versions",
    "/v1/agent-configs/{agent_config_id}/compare",
    "/v1/notification-targets",
    "/v1/automations",
    "/v1/automations/{automation_id}",
    "/v1/automations/{automation_id}/preview",
    "/v1/automations/{automation_id}/run",
    "/v1/automations/{automation_id}/runs",
    "/v1/grounding-checks",
    "/v1/novelty-runs",
    "/v1/data-classification-policies",
    "/v1/data-classification/classify",
    "/v1/context-packs",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_required_schema_files_exist_and_are_valid_json_schema() -> None:
    present = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
    assert REQUIRED_SCHEMAS <= present

    for schema_path in SCHEMA_DIR.glob("*.schema.json"):
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        assert schema["$id"].startswith("https://openabm.dev/schemas/")


def test_trace_fixtures_validate_against_trace_and_span_schemas() -> None:
    trace_schema = load_json(SCHEMA_DIR / "trace-envelope.schema.json")
    span_schema = load_json(SCHEMA_DIR / "span-envelope.schema.json")
    trace_validator = Draft202012Validator(trace_schema)
    span_validator = Draft202012Validator(span_schema)

    corpus = load_json(FIXTURE_PATH)
    assert corpus["fixture_version"]
    assert corpus["fixtures"]

    names = {fixture["name"] for fixture in corpus["fixtures"]}
    assert {
        "happy_path_support_trace",
        "wrong_tool_failure_trace",
        "fabricated_business_value_trace",
        "impact_report_with_affected_entities",
        "missing_parent_trace",
    } <= names
    assert set(corpus["required_fixture_names"]) == names | set(corpus["deferred_fixture_names"])
    assert corpus["deferred_fixture_names"] == []

    for fixture in corpus["fixtures"]:
        trace_validator.validate(fixture["trace"])
        for span in fixture["spans"]:
            span_validator.validate(span)
            assert span["trace_id"] == fixture["trace"]["trace_id"]
            assert span["project_id"] == fixture["trace"]["project_id"]
        assert "expected" in fixture


def test_score_result_schema_enforces_failure_reason_contract() -> None:
    schema = load_json(SCHEMA_DIR / "score-result.schema.json")
    validator = Draft202012Validator(schema)
    succeeded_score = {
        "score_id": "score_1",
        "trace_id": "trace_1",
        "judge_id": "judge_1",
        "status": "succeeded",
        "failure_reason": None,
        "value": {"verdict": "pass"},
    }
    failed_score = {
        **succeeded_score,
        "score_id": "score_2",
        "status": "failed",
        "failure_reason": "invalid_result",
        "value": None,
    }
    invalid_succeeded_score = {
        **succeeded_score,
        "failure_reason": "provider_error",
    }

    validator.validate(succeeded_score)
    validator.validate(failed_score)
    assert list(validator.iter_errors(invalid_succeeded_score))


def test_openapi_has_required_operation_level_contracts() -> None:
    openapi = load_json(OPENAPI_PATH)
    paths = openapi["paths"]
    assert REQUIRED_INGEST_PATHS <= set(paths)
    assert REQUIRED_QUERY_PATHS <= set(paths)

    for path, path_item in paths.items():
        for method, operation in path_item.items():
            assert operation.get("operationId"), f"{method.upper()} {path} missing operationId"
            assert operation.get("summary"), f"{method.upper()} {path} missing summary"
            assert operation.get("responses"), f"{method.upper()} {path} missing responses"


def test_live_openapi_exposes_only_public_v1_paths(tmp_path: Path) -> None:
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}"))
    paths = app.openapi()["paths"]

    assert REQUIRED_INGEST_PATHS <= set(paths)
    assert REQUIRED_QUERY_PATHS <= set(paths)
    assert not [path for path in paths if path.startswith("/api/")]


def test_committed_openapi_matches_live_public_path_methods(tmp_path: Path) -> None:
    committed_paths = load_json(OPENAPI_PATH)["paths"]
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'openabm.sqlite3'}"))
    live_paths = app.openapi()["paths"]

    assert _path_methods(committed_paths) == _path_methods(live_paths)


def _path_methods(paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
    http_methods = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
    return {
        (path, method)
        for path, path_item in paths.items()
        for method in path_item
        if method in http_methods
    }
