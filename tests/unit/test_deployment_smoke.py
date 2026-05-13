from __future__ import annotations

import importlib.util
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "deployment_smoke",
    ROOT / "scripts" / "deployment_smoke.py",
)
assert SPEC is not None
deployment_smoke = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = deployment_smoke
SPEC.loader.exec_module(deployment_smoke)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_deployment_smoke_reads_json_with_auth_header(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    def fake_urlopen(request: urllib.request.Request, *, timeout: int) -> FakeResponse:
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = str(timeout)
        return FakeResponse(b'{"status": "ok", "service": "openabm-api"}')

    monkeypatch.setattr(deployment_smoke.urllib.request, "urlopen", fake_urlopen)

    body = deployment_smoke._get(
        "http://127.0.0.1:8787/health",
        api_key="dev-key",
        expect_json=True,
    )

    assert body["status"] == "ok"
    assert captured == {"authorization": "Bearer dev-key", "timeout": "10"}


def test_deployment_smoke_accepts_prometheus_metrics_text(monkeypatch) -> None:
    def fake_urlopen(_request: urllib.request.Request, *, timeout: int) -> FakeResponse:
        assert timeout == 10
        return FakeResponse(b"# TYPE openabm_api_requests counter\nopenabm_api_requests 1\n")

    monkeypatch.setattr(deployment_smoke.urllib.request, "urlopen", fake_urlopen)

    body = deployment_smoke._get(
        "http://127.0.0.1:8787/metrics",
        api_key=None,
        expect_json=False,
    )

    assert "openabm_api_requests" in body
