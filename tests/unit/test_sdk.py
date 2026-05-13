import json

from openabm import (
    IntegrationRegistry,
    IntegrationWrapperContract,
    MethodSpanIntegrationPlugin,
    SamplingConfig,
    Tracer,
    default_integration_registry,
    extract_baggage,
    observe,
)
from openabm.exporters import HttpExporter, InMemoryExporter, OfflineJsonlExporter


def test_tracer_records_nested_spans_in_memory() -> None:
    exporter = InMemoryExporter()
    tracer = Tracer(
        "proj_demo",
        environment="test",
        exporter=exporter,
        resource={"service.name": "refund-api", "service.version": "test"},
    )

    @observe(name="lookup_policy", span_type="tool")
    def lookup_policy() -> dict[str, int]:
        return {"eligible_days": 30}

    with tracer.span("refund_agent", span_type="agent", input="refund?") as span:
        result = lookup_policy()
        span.set_output(result)

    spans = [item for item in exporter.items if item["type"] == "span"]
    traces = [item for item in exporter.items if item["type"] == "trace"]
    assert len(spans) == 2
    assert len(traces) == 1
    root_span = next(item["payload"] for item in spans if item["payload"]["parent_span_id"] is None)
    child_span = next(
        item["payload"] for item in spans if item["payload"]["parent_span_id"] is not None
    )
    assert child_span["parent_span_id"] == root_span["span_id"]
    assert root_span["attributes"]["openabm.project_id"] == "proj_demo"
    assert root_span["attributes"]["openabm.span_type"] == "agent"
    assert child_span["attributes"]["openabm.span_type"] == "tool"
    assert root_span["resource"]["service.name"] == "refund-api"
    assert child_span["resource"]["service.version"] == "test"


def test_payload_capture_can_be_disabled(tmp_path) -> None:
    output_path = tmp_path / "trace.jsonl"
    tracer = Tracer(
        "proj_demo",
        environment="test",
        exporter=OfflineJsonlExporter(output_path),
        capture_payloads=False,
    )

    with tracer.span(
        "sensitive_agent",
        span_type="agent",
        input={"secret": "do-not-export"},
    ) as span:
        span.set_output({"answer": "also-hidden"})

    lines = [json.loads(line) for line in output_path.read_text().splitlines()]
    span_payload = next(line["payload"] for line in lines if line["type"] == "span")
    assert span_payload["input"]["mode"] == "omitted"
    assert span_payload["output"]["mode"] == "omitted"
    assert "do-not-export" not in output_path.read_text()


def test_sdk_payload_and_stream_event_sampling_are_visible() -> None:
    exporter = InMemoryExporter()
    tracer = Tracer(
        "proj_demo",
        environment="test",
        exporter=exporter,
        sampling=SamplingConfig(
            payload_max_bytes=12,
            max_events_per_span=3,
            stream_event_sample_rate=2,
        ),
    )

    with tracer.span("chat_agent", span_type="agent", input={"prompt": "x" * 40}) as span:
        for index in range(8):
            span.add_event(
                "model.stream.delta",
                {"index": index, "text": "partial"},
            )
        span.set_output({"answer": "y" * 40})

    span_payload = next(item["payload"] for item in exporter.items if item["type"] == "span")
    assert span_payload["input"]["mode"] == "omitted"
    assert span_payload["input"]["omission_reason"] == "sdk_payload_sampling"
    assert span_payload["output"]["omission_reason"] == "sdk_payload_sampling"
    assert span_payload["events"][-1]["name"] == "openabm.events_omitted"
    assert span_payload["events"][-1]["attributes"]["stream_events_omitted"] == 4


def test_sdk_exports_runtime_provenance_on_root_trace() -> None:
    exporter = InMemoryExporter()
    tracer = Tracer(
        "proj_demo",
        environment="test",
        exporter=exporter,
        session_id="session_runtime",
        user_external_id="user_external_1",
        redaction_policy_handle="redaction_policy_default",
        prompt_version_id="prompt_version_prod",
        agent_config_version_id="agent_config_runtime_v2",
        deployment_context_id="deploy_runtime_v2",
        tool_version_ids=["tool_lookup_v1"],
    )

    with tracer.span("runtime_agent", span_type="agent"):
        pass

    trace_payload = next(item["payload"] for item in exporter.items if item["type"] == "trace")
    assert trace_payload["prompt_version_id"] == "prompt_version_prod"
    assert trace_payload["session_id"] == "session_runtime"
    assert trace_payload["user_external_id"] == "user_external_1"
    assert trace_payload["agent_config_version_id"] == "agent_config_runtime_v2"
    assert trace_payload["deployment_context_id"] == "deploy_runtime_v2"
    assert trace_payload["tool_version_ids"] == ["tool_lookup_v1"]
    assert trace_payload["attributes"]["agent_config_version_id"] == "agent_config_runtime_v2"
    assert trace_payload["attributes"]["openabm.session_id"] == "session_runtime"
    assert trace_payload["attributes"]["openabm.redaction_policy_handle"] == (
        "redaction_policy_default"
    )


def test_sdk_baggage_continuation_preserves_parent_child_without_payloads() -> None:
    upstream_exporter = InMemoryExporter()
    upstream = Tracer(
        "proj_demo",
        environment="prod",
        exporter=upstream_exporter,
        session_id="session_1",
        user_external_id="user_1",
        redaction_policy_handle="redaction_policy_v1",
    )

    with upstream.span(
        "upstream_agent",
        span_type="agent",
        attributes={"openabm.priority": "p1"},
        input={"prompt": "never propagate me"},
    ) as span:
        baggage = upstream.inject_baggage(span)
        span.set_output({"answer": "do not propagate"})

    assert baggage["openabm-project-id"] == "proj_demo"
    assert baggage["openabm-environment"] == "prod"
    assert baggage["openabm-session-id"] == "session_1"
    assert baggage["openabm-user-external-id"] == "user_1"
    assert baggage["openabm-sampling-priority"] == "p1"
    assert baggage["openabm-redaction-policy"] == "redaction_policy_v1"
    assert "prompt" not in json.dumps(baggage)
    assert extract_baggage({"openabm-trace-id": baggage["openabm-trace-id"], "secret": "x"}) == {
        "trace_id": baggage["openabm-trace-id"]
    }

    downstream_exporter = InMemoryExporter()
    downstream = Tracer("proj_demo", environment="prod", exporter=downstream_exporter)
    with downstream.continue_from_baggage("downstream_tool", baggage, span_type="tool"):
        pass

    downstream_span = next(item["payload"] for item in downstream_exporter.items)
    assert downstream_span["trace_id"] == baggage["openabm-trace-id"]
    assert downstream_span["parent_span_id"] == baggage["openabm-span-id"]
    assert downstream_span["attributes"]["openabm.project_id"] == "proj_demo"


def test_sdk_probabilistic_sampling_preserves_metadata_and_omits_bodies() -> None:
    exporter = InMemoryExporter()
    tracer = Tracer(
        "proj_demo",
        environment="test",
        exporter=exporter,
        sampling=SamplingConfig(sample_rate=0),
    )

    with tracer.span(
        "sampled_out_agent",
        span_type="agent",
        input={"prompt": "keep metadata"},
    ) as span:
        span.add_event("debug.step", {"detail": "low signal"})
        span.set_output({"answer": "sampled"})

    span_payload = next(item["payload"] for item in exporter.items if item["type"] == "span")
    trace_payload = next(item["payload"] for item in exporter.items if item["type"] == "trace")
    assert trace_payload["attributes"]["openabm.sampling.sampled"] is False
    assert span_payload["input"]["omission_reason"] == "sdk_trace_sampling"
    assert span_payload["output"]["omission_reason"] == "sdk_trace_sampling"
    assert span_payload["events"] == [
        {
            "name": "openabm.events_omitted",
            "time": span_payload["events"][0]["time"],
            "attributes": {
                "omission_reason": "sdk_trace_sampling",
                "stream_events_omitted": 0,
                "other_events_omitted": 1,
                "preserved_metadata": True,
            },
        }
    ]


def test_sdk_partial_flush_marks_whether_span_is_still_open() -> None:
    exporter = InMemoryExporter()
    tracer = Tracer("proj_demo", environment="test", exporter=exporter)

    with tracer.span("long_agent", span_type="agent") as span:
        span.flush_partial()

    span_payloads = [item["payload"] for item in exporter.items if item["type"] == "span"]
    partial_span = span_payloads[0]
    final_span = span_payloads[-1]
    partial_flush_event = next(
        event for event in partial_span["events"] if event["name"] == "openabm.partial_flush"
    )

    assert partial_span["status"] == "incomplete"
    assert partial_span["ended_at"] is None
    assert partial_flush_event["attributes"]["span_is_open"] is True
    assert partial_flush_event["attributes"]["ended_at_nullable"] is None
    assert final_span["status"] == "ok"
    assert final_span["ended_at"] is not None


def test_http_exporter_caps_buffer_and_preserves_high_priority_items() -> None:
    exporter = HttpExporter(
        "http://127.0.0.1:8787",
        "dev-openabm-key",
        max_buffered_items=1,
    )

    exporter.export(
        "span",
        {
            "trace_id": "trace_ok",
            "span_id": "span_ok",
            "status": "ok",
            "attributes": {},
        },
    )
    exporter.export(
        "span",
        {
            "trace_id": "trace_error",
            "span_id": "span_error",
            "status": "error",
            "attributes": {},
        },
    )

    assert [span["span_id"] for span in exporter._spans] == ["span_error"]
    assert exporter.dropped_items[0]["reason"] == "evicted_for_high_priority_item"


def test_sdk_integration_registry_validates_wrapper_contracts() -> None:
    class EchoIntegration:
        contract = IntegrationWrapperContract(
            name="echo-agent",
            supported_package="echo-agent",
            supported_versions=">=1,<2",
            instrumentation_hooks=("run",),
            captured_metadata=("model", "tool.name"),
            payload_capture_behavior="uses tracer capture settings before export",
            redaction_behavior="delegates payloads to tracer redactors",
            known_limitations=("test-only wrapper",),
            example_code="registry.instrument('echo-agent', tracer, agent)",
            acceptance_tests=("records a span around run()",),
        )

        def instrument(self, tracer, target, config=None):
            return {"tracer": tracer, "target": target, "config": dict(config or {})}

    registry = IntegrationRegistry([EchoIntegration()])
    assert registry.list_contracts()[0]["name"] == "echo-agent"
    assert registry.list_contracts()[0]["instrumentation_hooks"] == ["run"]

    tracer = Tracer("proj_demo", exporter=InMemoryExporter())
    instrumented = registry.instrument("echo-agent", tracer, object(), {"capture_payloads": False})
    assert instrumented["tracer"] is tracer
    assert instrumented["config"] == {"capture_payloads": False}

    try:
        registry.register(EchoIntegration())
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("duplicate integration registration should fail")


def test_sdk_generic_method_integration_records_spans() -> None:
    class Agent:
        def run(self, prompt: str) -> str:
            return f"answer: {prompt}"

    exporter = InMemoryExporter()
    tracer = Tracer("proj_demo", environment="test", exporter=exporter)
    registry = default_integration_registry()
    agent = registry.instrument(
        "generic-method-span",
        tracer,
        Agent(),
        {
            "methods": ["run"],
            "span_type": "agent",
            "attributes": {"integration": "generic"},
        },
    )

    assert agent.run("refund") == "answer: refund"

    span_payload = next(item["payload"] for item in exporter.items if item["type"] == "span")
    assert span_payload["name"] == "run"
    assert span_payload["span_type"] == "agent"
    assert span_payload["output"]["value"] == "answer: refund"
    assert span_payload["attributes"]["openabm.integration.method"] == "run"
    assert span_payload["attributes"]["integration"] == "generic"


def test_sdk_generic_callable_integration_preserves_return_value() -> None:
    exporter = InMemoryExporter()
    tracer = Tracer("proj_demo", environment="test", exporter=exporter)
    plugin = MethodSpanIntegrationPlugin()

    def lookup_policy() -> dict[str, int]:
        return {"eligible_days": 30}

    instrumented = plugin.instrument(
        tracer,
        lookup_policy,
        {"span_type": "tool", "span_name_prefix": "sdk_"},
    )

    assert instrumented() == {"eligible_days": 30}
    span_payload = next(item["payload"] for item in exporter.items if item["type"] == "span")
    assert span_payload["name"] == "sdk_lookup_policy"
    assert span_payload["span_type"] == "tool"


def test_sdk_integration_contract_rejects_incomplete_metadata() -> None:
    contract = IntegrationWrapperContract(
        name="bad-agent",
        supported_package="bad-agent",
        supported_versions=">=1",
        instrumentation_hooks=(),
        captured_metadata=("model",),
        payload_capture_behavior="uses tracer capture settings before export",
        redaction_behavior="delegates payloads to tracer redactors",
        acceptance_tests=("records spans",),
    )

    try:
        contract.validate()
    except ValueError as exc:
        assert "instrumentation_hooks" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid integration contract should fail validation")
