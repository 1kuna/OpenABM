import json

from openabm import SamplingConfig, Tracer, observe
from openabm.exporters import HttpExporter, InMemoryExporter, OfflineJsonlExporter


def test_tracer_records_nested_spans_in_memory() -> None:
    exporter = InMemoryExporter()
    tracer = Tracer("proj_demo", environment="test", exporter=exporter)

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
        prompt_version_id="prompt_version_prod",
        agent_config_version_id="agent_config_runtime_v2",
        deployment_context_id="deploy_runtime_v2",
        tool_version_ids=["tool_lookup_v1"],
    )

    with tracer.span("runtime_agent", span_type="agent"):
        pass

    trace_payload = next(item["payload"] for item in exporter.items if item["type"] == "trace")
    assert trace_payload["prompt_version_id"] == "prompt_version_prod"
    assert trace_payload["agent_config_version_id"] == "agent_config_runtime_v2"
    assert trace_payload["deployment_context_id"] == "deploy_runtime_v2"
    assert trace_payload["tool_version_ids"] == ["tool_lookup_v1"]
    assert trace_payload["attributes"]["agent_config_version_id"] == "agent_config_runtime_v2"


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
