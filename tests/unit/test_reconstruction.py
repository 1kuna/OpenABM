import json
from pathlib import Path

from openabm_api.reconstruction import reconstruct_trace

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"


def fixtures_by_name() -> dict[str, dict]:
    corpus = json.loads(FIXTURE_PATH.read_text())
    return {fixture["name"]: fixture for fixture in corpus["fixtures"]}


def test_reconstructs_missing_parent_group() -> None:
    fixture = fixtures_by_name()["missing_parent_trace"]
    result = reconstruct_trace(fixture["trace"], fixture["spans"])
    warning_types = {warning["type"] for warning in result["warnings"]}
    assert "missing_parent" in warning_types
    assert result["missing_parent_group"][0]["span"]["span_id"] == "span_orphan_tool"


def test_reconstructs_clock_skew_warning() -> None:
    fixture = fixtures_by_name()["clock_skew_trace"]
    result = reconstruct_trace(fixture["trace"], fixture["spans"])
    warning_types = {warning["type"] for warning in result["warnings"]}
    assert "clock_skew" in warning_types
    assert result["span_tree"][0]["span"]["span_id"] == "span_clock_root"

