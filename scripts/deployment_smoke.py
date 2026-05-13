from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SmokeEndpoint:
    path: str
    authenticated: bool = False
    expect_json: bool = True


ENDPOINTS = [
    SmokeEndpoint("/health"),
    SmokeEndpoint("/ready"),
    SmokeEndpoint("/v1/projects", authenticated=True),
    SmokeEndpoint("/v1/auth/contract", authenticated=True),
    SmokeEndpoint("/v1/ops/status?project_id=proj_demo", authenticated=True),
    SmokeEndpoint("/metrics", expect_json=False),
]


def main() -> int:
    base_url = os.getenv("OPENABM_API_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
    api_key = os.getenv("OPENABM_API_KEY", "dev-openabm-key")
    results: list[dict[str, Any]] = []
    failed = False

    for endpoint in ENDPOINTS:
        try:
            body = _get(
                f"{base_url}{endpoint.path}",
                api_key=api_key if endpoint.authenticated else None,
                expect_json=endpoint.expect_json,
            )
            if endpoint.expect_json:
                results.append({"path": endpoint.path, "status": "ok", "keys": sorted(body)[:8]})
            else:
                results.append(
                    {
                        "path": endpoint.path,
                        "status": "ok",
                        "bytes": len(str(body).encode("utf-8")),
                    }
                )
        except Exception as exc:
            failed = True
            results.append({"path": endpoint.path, "status": "failed", "error": str(exc)})

    print(json.dumps({"base_url": base_url, "results": results}, indent=2, sort_keys=True))
    return 1 if failed else 0


def _get(url: str, *, api_key: str | None, expect_json: bool) -> dict[str, Any] | str:
    request = urllib.request.Request(url)
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    if not expect_json:
        if "openabm_" not in payload:
            raise RuntimeError(f"{url} returned metrics text without openabm_ samples")
        return payload
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{url} returned non-object JSON")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
