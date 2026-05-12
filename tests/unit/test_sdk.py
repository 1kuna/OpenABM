import json

from openabm import Tracer, observe
from openabm.exporters import InMemoryExporter, OfflineJsonlExporter


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
