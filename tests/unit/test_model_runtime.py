import asyncio
import json

import httpx
from openabm_worker.investigation import assist_investigation
from openabm_worker.judges import run_rubric_judge
from openabm_worker.model_runtime import OpenAICompatibleModelProvider


def test_structured_completion_parses_json_without_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "timeout" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"verdict": "pass", "evidence_span_ids": []})
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    provider = OpenAICompatibleModelProvider(
        base_url="http://test/v1",
        chat_model="local-test",
        context_length=32768,
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        provider.structured_completion(
            {"messages": [{"role": "user", "content": "judge"}]},
            {
                "type": "object",
                "required": ["verdict", "evidence_span_ids"],
                "properties": {
                    "verdict": {"enum": ["pass", "fail", "unsure"]},
                    "evidence_span_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        )
    )
    assert result["status"] == "succeeded"
    assert result["model"] == "local-test"


def test_rubric_judge_requires_preserved_span_citations() -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "verdict": "fail",
                    "score": 0.0,
                    "confidence": 0.8,
                    "reasoning": "The trace used the wrong tool.",
                    "evidence_span_ids": ["span_tool"],
                    "failure_mode": "wrong_tool",
                    "notes": None,
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": None,
                "repaired": False,
            }

    score = asyncio.run(
        run_rubric_judge(
            StubProvider(),
            {"trace_id": "trace_1", "status": "error"},
            [
                {
                    "span_id": "span_tool",
                    "name": "lookup_order",
                    "span_type": "tool",
                    "status": "ok",
                    "started_at": "2026-05-12T00:00:00Z",
                    "ended_at": "2026-05-12T00:00:01Z",
                    "attributes": {"tool.name": "order_lookup"},
                }
            ],
            {
                "judge_id": "judge_wrong_tool",
                "judge_type": "rubric_judge",
                "rubric": {"fail": "Wrong tool was used."},
            },
            token_budget=32768,
        )
    )
    assert score["status"] == "succeeded"
    assert score["evidence_span_ids"] == ["span_tool"]
    assert score["cost"]["model"] == "stub-model"


def test_investigation_assistance_drops_invented_citations() -> None:
    class StubProvider:
        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "succeeded",
                "value": {
                    "suspected_root_causes": [
                        {
                            "hypothesis": "The cited tool span chose the wrong workflow.",
                            "evidence_trace_ids": ["trace_1", "trace_missing"],
                            "evidence_span_ids": ["span_tool", "span_missing"],
                            "confidence_or_uncertainty": "one cited span",
                        },
                        {
                            "hypothesis": "This candidate has only invented citations.",
                            "evidence_trace_ids": ["trace_missing"],
                            "evidence_span_ids": ["span_missing"],
                            "confidence_or_uncertainty": "unsupported",
                        },
                    ],
                    "behavior_drafts": [
                        {
                            "name": "wrong_tool",
                            "description": "A trace uses an unrelated tool.",
                            "positive_trace_ids": ["trace_1", "trace_missing"],
                            "negative_trace_ids": ["trace_missing"],
                        }
                    ],
                    "rubric_drafts": [
                        {
                            "name": "Wrong tool",
                            "pass": "Uses the expected tool.",
                            "fail": "Uses an unrelated tool.",
                            "unsure": "Tool evidence is absent.",
                            "evidence_trace_ids": ["trace_1", "trace_missing"],
                        }
                    ],
                    "recommended_next_actions": ["backtest wrong_tool"],
                    "confidence_or_uncertainty": "single fixture trace",
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": None,
                "repaired": False,
            }

    result = asyncio.run(
        assist_investigation(
            StubProvider(),
            issue=None,
            traces=[{"trace_id": "trace_1"}],
            spans_by_trace={"trace_1": [{"span_id": "span_tool"}]},
            impact_report={},
        )
    )

    assert len(result["suspected_root_causes"]) == 1
    assert result["suspected_root_causes"][0]["evidence_trace_ids"] == ["trace_1"]
    assert result["suspected_root_causes"][0]["evidence_span_ids"] == ["span_tool"]
    assert result["behavior_drafts"][0]["positive_trace_ids"] == ["trace_1"]
    assert result["behavior_drafts"][0]["negative_trace_ids"] == []
    assert result["rubric_drafts"][0]["evidence_trace_ids"] == ["trace_1"]
