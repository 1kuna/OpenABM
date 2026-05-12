import json
from pathlib import Path

from jsonschema import Draft202012Validator

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
}

REQUIRED_INGEST_PATHS = {
    "/api/ingest/traces",
    "/api/ingest/spans",
    "/api/ingest/events",
    "/api/ingest/feedback",
    "/api/ingest/payloads",
    "/api/ingest/batch",
}

REQUIRED_QUERY_PATHS = {
    "/api/projects",
    "/api/traces",
    "/api/traces/{trace_id}",
    "/api/traces/{trace_id}/spans",
    "/api/spans/{span_id}",
    "/api/sessions",
    "/api/search/traces",
    "/api/search/spans",
    "/api/search/similar",
    "/api/scores",
    "/api/behaviors",
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
    assert {"happy_path_support_trace", "wrong_tool_failure_trace", "missing_parent_trace"} <= names
    assert set(corpus["required_fixture_names"]) == names | set(corpus["deferred_fixture_names"])

    for fixture in corpus["fixtures"]:
        trace_validator.validate(fixture["trace"])
        for span in fixture["spans"]:
            span_validator.validate(span)
            assert span["trace_id"] == fixture["trace"]["trace_id"]
            assert span["project_id"] == fixture["trace"]["project_id"]
        assert "expected" in fixture


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

