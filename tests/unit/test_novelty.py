import json
from pathlib import Path

from openabm_worker.novelty import (
    detect_novel_behavior_candidates,
    run_novelty_clustering_benchmark,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"


def test_novelty_detection_includes_timeout_tool_loop_candidates() -> None:
    corpus = json.loads(FIXTURE_PATH.read_text())
    fixture = next(
        item for item in corpus["fixtures"] if item["trace"]["trace_id"] == "trace_tool_loop"
    )

    result = detect_novel_behavior_candidates(
        [fixture["trace"]],
        {fixture["trace"]["trace_id"]: fixture["spans"]},
        [],
    )

    candidates = result["new_behavior_candidates"]
    assert candidates[0]["representative_positive_traces"] == ["trace_tool_loop"]
    assert candidates[0]["name"].startswith("tool_sequence_")


def test_novelty_clustering_benchmark_covers_labeled_fixture_behaviors() -> None:
    corpus = json.loads(FIXTURE_PATH.read_text())

    result = run_novelty_clustering_benchmark(corpus["fixtures"])

    assert result["status"] == "passed"
    assert result["metrics"]["labeled_recall"] == 1.0
    assert result["missed_labeled_trace_ids"] == []
    assert "trace_tool_loop" in result["detected_labeled_trace_ids"]
    assert result["negative_example_selection"]["status"] == "succeeded"
    assert any(
        "tool_loop" in candidate["expected_behavior_labels"]
        for candidate in result["candidates"]
    )
