import asyncio
import json
from pathlib import Path

import httpx
import pytest
from openabm_api.settings import Settings
from openabm_mcp.tools import all_tool_definitions
from openabm_worker.agent_flow_smoke import (
    OPENABM_AGENT_FLOW_TOOL_NAMES,
    run_agent_flow_tool_smoke,
)
from openabm_worker.context_packets import build_trace_context_packet
from openabm_worker.investigation import assist_investigation
from openabm_worker.judges import (
    run_deterministic_rule_judge,
    run_rubric_judge,
    validate_judge_output,
)
from openabm_worker.model_benchmark import (
    _benchmark_judge,
    compare_model_runtime_benchmarks,
    run_model_runtime_benchmark,
)
from openabm_worker.model_runtime import (
    ModelResourceGuardError,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleModelProvider,
    model_provider_from_settings,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "evals" / "golden-fixtures" / "trace_fixtures.json"


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


def test_tool_completion_parses_openai_compatible_tool_calls() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tool_choice"] == "required"
        assert body["tools"][0]["function"]["name"] == "extract_claims"
        assert "timeout" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "extract_claims",
                                        "arguments": json.dumps({"claims": ["delivered"]}),
                                    },
                                }
                            ],
                        },
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
        provider.tool_completion(
            {
                "messages": [{"role": "user", "content": "extract"}],
                "tool_choice": {"type": "function", "function": {"name": "extract_claims"}},
            },
            [
                {
                    "type": "function",
                    "function": {
                        "name": "extract_claims",
                        "description": "Extract claims.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "claims": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                }
                            },
                            "required": ["claims"],
                        },
                    },
                }
            ],
        )
    )
    assert result["status"] == "succeeded"
    assert result["tool_calls"][0]["name"] == "extract_claims"
    assert result["tool_calls"][0]["arguments"] == {"claims": ["delivered"]}


def test_embedding_provider_parses_openai_compatible_embeddings_without_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert body["model"] == "local-embed"
        assert body["input"] == ["refund trace", "shipping trace"]
        assert "timeout" not in body
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 1.0]},
                ],
                "usage": {"total_tokens": 4},
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://test/v1",
        embedding_model="local-embed",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        provider.embed_documents(
            [
                {"document_id": "trace_refund", "text": "refund trace"},
                {"document_id": "trace_shipping", "text": "shipping trace"},
            ],
        )
    )
    assert result["status"] == "succeeded"
    assert result["model"] == "local-embed"
    assert result["embeddings"][0]["document_id"] == "trace_refund"
    assert result["embeddings"][0]["embedding"] == [1.0, 0.0]


def test_agent_flow_tool_smoke_validates_required_tool_call() -> None:
    class StubHealth:
        adapter_name = "stub"
        status = "configured"
        supported_capabilities = ["tool_completion"]
        details = {
            "chat_model": "qwen3.5-9b-mlx",
            "context_length": 262144,
            "memory_guard_status": "ready",
            "available_memory_mb": 40000,
            "min_available_memory_mb": 8192,
            "timeout_behavior": "No generation timeout is applied by OpenABM.",
        }

    class StubProvider:
        def health_check(self):
            return StubHealth()

        async def tool_completion(self, request, tools):
            assert request["tool_choice"]["function"]["name"] == "record_agent_flow_plan"
            assert tools[0]["function"]["name"] == "record_agent_flow_plan"
            return {
                "status": "succeeded",
                "tool_calls": [
                    {
                        "name": "record_agent_flow_plan",
                        "arguments": {
                            "queries": ["refund wrong tool"],
                            "expected_tools": ["search_traces", "create_agent_context_pack"],
                            "risk_notes": ["single fixture smoke"],
                            "confidence": "medium",
                        },
                    }
                ],
                "provider": "stub",
                "model": "qwen3.5-9b-mlx",
                "usage": {"total_tokens": 32},
            }

    result = asyncio.run(run_agent_flow_tool_smoke(StubProvider()))

    assert result["status"] == "succeeded"
    assert result["requested_tool"] == "record_agent_flow_plan"
    assert result["provider_health"]["context_length"] == 262144
    assert result["provider_health"]["memory_guard_status"] == "ready"


def test_agent_flow_tool_choices_are_real_mcp_tools() -> None:
    mcp_tool_names = {tool["name"] for tool in all_tool_definitions()}
    assert set(OPENABM_AGENT_FLOW_TOOL_NAMES) <= mcp_tool_names


def test_agent_flow_tool_smoke_rejects_missing_required_arguments() -> None:
    class StubHealth:
        adapter_name = "stub"
        status = "configured"
        supported_capabilities = ["tool_completion"]
        details = {}

    class StubProvider:
        def health_check(self):
            return StubHealth()

        async def tool_completion(self, request, tools):
            del request, tools
            return {
                "status": "succeeded",
                "tool_calls": [{"name": "record_agent_flow_plan", "arguments": {}}],
                "provider": "stub",
                "model": "stub-model",
            }

    result = asyncio.run(run_agent_flow_tool_smoke(StubProvider()))

    assert result["status"] == "invalid_output"
    assert "queries" in " ".join(result["validation_errors"])


def test_model_provider_from_settings_configures_memory_guard() -> None:
    provider = model_provider_from_settings(
        Settings(
            model_mode="local",
            chat_model="local-test",
            model_min_available_memory_mb=12345,
        )
    )

    health = provider.health_check()

    assert health.details["min_available_memory_mb"] == 12345
    assert health.details["memory_guard_status"] in {"ready", "blocked", "unknown"}


def test_chat_provider_blocks_new_calls_when_memory_guard_fails() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("model call should be skipped before transport")

    provider = OpenAICompatibleModelProvider(
        base_url="http://test/v1",
        chat_model="local-test",
        min_available_memory_mb=8192,
        available_memory_mb=lambda: 1024.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelResourceGuardError, match="Available system memory"):
        asyncio.run(
            provider.chat_completion(
                {"messages": [{"role": "user", "content": "judge"}]},
            )
        )


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
    assert score["failure_reason"] is None
    assert score["evidence_span_ids"] == ["span_tool"]
    assert score["cost"]["model"] == "stub-model"
    assert score["cost"]["context_packet_hash"]
    assert score["cost"]["context_version"] == "ctx_2"


def test_judge_outputs_include_contract_failure_reasons() -> None:
    invalid = validate_judge_output(
        {
            "verdict": "fail",
            "score": 0.0,
            "confidence": 0.4,
            "reasoning": "Missing evidence.",
            "evidence_span_ids": [],
        },
        trace_id="trace_1",
        judge_id="judge_1",
        judge_version_id=None,
        preserved_span_ids=set(),
        require_span_citations=True,
    )
    deterministic = run_deterministic_rule_judge(
        {"trace_id": "trace_1"},
        [
            {
                "span_id": "span_tool",
                "attributes": {"tool": {"name": "lookup_order"}},
            }
        ],
        {
            "judge_id": "judge_rule",
            "judge_version_id": "judge_ver_1",
            "rule": {
                "match_semantics": "any_match_is_fail",
                "failure_mode": "wrong_tool",
                "conditions": {
                    "combine": "all",
                    "items": [
                        {"field": "attributes.tool.name", "op": "eq", "value": "lookup_order"}
                    ],
                },
            },
        },
    )

    assert invalid["status"] == "invalid_output"
    assert invalid["failure_reason"] == "invalid_result"
    assert deterministic["status"] == "succeeded"
    assert deterministic["failure_reason"] is None
    assert deterministic["failure_mode"] == "wrong_tool"


def test_trace_context_packet_summarizes_long_payloads_and_records_hash() -> None:
    packet = build_trace_context_packet(
        {"trace_id": "trace_1", "status": "ok", "summary": "Long payload trace."},
        [
            {
                "span_id": "span_root",
                "parent_span_id": None,
                "name": "agent",
                "span_type": "agent",
                "status": "ok",
                "started_at": "2026-05-12T00:00:00Z",
                "ended_at": "2026-05-12T00:00:01Z",
                "input": {
                    "mode": "inline",
                    "value": {"text": "x" * 5000},
                    "redaction_state": "raw",
                },
                "output": {
                    "mode": "inline",
                    "value": {"answer": "y" * 5000},
                    "redaction_state": "raw",
                },
                "events": [],
                "attributes": {},
            }
        ],
        token_budget=32768,
    )

    assert packet["context_version"] == "ctx_2"
    assert packet["context_packet_hash"]
    assert packet["span_tree"][0]["input"]["omission_reason"] == "context_payload_summary"
    assert packet["span_tree"][0]["output"]["omission_reason"] == "context_payload_summary"
    assert {summary["field"] for summary in packet["summaries"]} == {"input", "output"}
    assert packet["preserved_span_ids"] == ["span_root"]


def test_trace_context_packet_truncates_low_priority_spans_before_evidence_spans() -> None:
    spans = [
        {
            "span_id": "span_root",
            "parent_span_id": None,
            "name": "agent",
            "span_type": "agent",
            "status": "ok",
            "started_at": "2026-05-12T00:00:00Z",
            "ended_at": "2026-05-12T00:00:01Z",
            "input": None,
            "output": {"mode": "inline", "value": "root"},
            "events": [],
            "attributes": {"blob": "r" * 50000},
        },
        {
            "span_id": "span_tool",
            "parent_span_id": "span_root",
            "name": "tool",
            "span_type": "tool",
            "status": "ok",
            "started_at": "2026-05-12T00:00:02Z",
            "ended_at": "2026-05-12T00:00:03Z",
            "input": {"mode": "inline", "value": "tool"},
            "output": {"mode": "inline", "value": "tool"},
            "events": [],
            "attributes": {"blob": "t" * 50000},
        },
        {
            "span_id": "span_low_signal",
            "parent_span_id": "span_root",
            "name": "scratchpad",
            "span_type": "other",
            "status": "ok",
            "started_at": "2026-05-12T00:00:04Z",
            "ended_at": "2026-05-12T00:00:05Z",
            "input": {"mode": "inline", "value": "scratch"},
            "output": {"mode": "inline", "value": "scratch"},
            "events": [],
            "attributes": {"blob": "l" * 50000},
        },
    ]
    packet = build_trace_context_packet(
        {"trace_id": "trace_budget", "status": "ok"},
        spans,
        token_budget=32768,
    )

    assert "span_root" in packet["preserved_span_ids"]
    assert "span_tool" in packet["preserved_span_ids"]
    assert "span_low_signal" in packet["omitted_span_ids"]
    assert packet["truncation_notes"][0]["reason"] == "context_budget_exceeded"


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


def test_model_runtime_benchmark_reports_quality_and_promotion_gate() -> None:
    class StubHealth:
        adapter_name = "stub"
        details = {"chat_model": "stub-model"}

    class StubProvider:
        adapter_name = "stub"

        def health_check(self):
            return StubHealth()

        async def structured_completion(self, request, schema):
            del schema
            text = json.dumps(request)
            trace_id = text.split("'trace_id': '", 1)[1].split("'", 1)[0]
            unsure_trace_ids = {
                "trace_missing_parent",
                "trace_clock_skew",
                "trace_malformed_partial",
                "trace_duplicate_span_update",
                "trace_multi_root",
            }
            if trace_id == "trace_wrong_tool":
                verdict = "fail"
                evidence_span_ids = ["span_wrong_tool_order_lookup"]
            elif trace_id in unsure_trace_ids:
                verdict = "unsure"
                evidence_span_ids = []
            else:
                verdict = "pass"
                evidence_span_ids = []
            return {
                "status": "succeeded",
                "value": {
                    "verdict": verdict,
                    "score": {"pass": 1.0, "fail": 0.0, "unsure": 0.5}[verdict],
                    "confidence": 0.8,
                    "reasoning": "Fixture-controlled benchmark result.",
                    "evidence_span_ids": evidence_span_ids,
                    "failure_mode": None if verdict != "fail" else "wrong_tool_for_refund",
                    "notes": None,
                },
                "provider": "stub",
                "model": "stub-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "repaired": False,
            }

    corpus = json.loads(FIXTURE_PATH.read_text())
    result = asyncio.run(
        run_model_runtime_benchmark(
            StubProvider(),
            fixtures=corpus["fixtures"],
            fixture_version=corpus["fixture_version"],
            model_config={"chat_model": "stub-model", "model_context_length": 32768},
            token_budget=32768,
        )
    )

    assert result["provider_adapter"] == "stub"
    assert result["model_identifier"] == "stub-model"
    assert result["fixture_version"] == corpus["fixture_version"]
    assert result["metrics"]["total_fixtures"] == len(corpus["fixtures"])
    assert result["metrics"]["judge_accuracy"] == 1.0
    assert result["metrics"]["structured_output_validity_rate"] == 1.0
    assert result["metrics"]["citation_validity_rate"] == 1.0
    assert result["metrics"]["cost"]["usage"]["total_tokens"] == 15 * len(corpus["fixtures"])
    assert result["promotion_gate"]["status"] == "eligible"


def test_model_runtime_benchmark_judge_is_narrow_wrong_refund_tool_contract() -> None:
    judge = _benchmark_judge()
    rubric_text = json.dumps(judge["rubric"]).lower()

    assert "not a general trace-quality" in judge["description"]
    assert "unrelated failure modes pass" in rubric_text
    assert "refund decision" in rubric_text
    assert "malformed or incomplete" in rubric_text


def test_model_runtime_benchmark_blocks_invalid_outputs() -> None:
    class StubHealth:
        adapter_name = "stub"
        details = {"chat_model": "bad-model"}

    class InvalidProvider:
        def health_check(self):
            return StubHealth()

        async def structured_completion(self, request, schema):
            del request, schema
            return {
                "status": "invalid_output",
                "provider": "stub",
                "model": "bad-model",
                "usage": None,
                "raw_output": "not json",
            }

    corpus = json.loads(FIXTURE_PATH.read_text())
    result = asyncio.run(
        run_model_runtime_benchmark(
            InvalidProvider(),
            fixtures=corpus["fixtures"][:1],
            fixture_version=corpus["fixture_version"],
            model_config={"chat_model": "bad-model", "model_context_length": 32768},
            token_budget=32768,
        )
    )
    assert result["promotion_gate"]["status"] == "blocked"
    assert "invalid_output_rate_above_threshold" in result["promotion_gate"]["blocking_reasons"]

    comparison = compare_model_runtime_benchmarks(
        {
            "benchmark_run_id": "baseline",
            "model_identifier": "baseline-model",
            "metrics": {"judge_accuracy": 1.0, "invalid_output_rate": 0.0},
        },
        result,
    )
    assert comparison["candidate_run_id"] == result["benchmark_run_id"]
    assert comparison["metric_deltas"]["judge_accuracy"] < 0
