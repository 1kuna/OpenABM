from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import httpx


class Exporter(Protocol):
    def export(self, item_type: str, payload: dict[str, Any]) -> None:
        ...

    def flush(self) -> None:
        ...


class InMemoryExporter:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def export(self, item_type: str, payload: dict[str, Any]) -> None:
        self.items.append({"type": item_type, "payload": payload})

    def flush(self) -> None:
        return None


class OfflineJsonlExporter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, item_type: str, payload: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": item_type, "payload": payload}, sort_keys=True) + "\n")

    def flush(self) -> None:
        return None


class HttpExporter:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._traces: list[dict[str, Any]] = []
        self._spans: list[dict[str, Any]] = []

    def export(self, item_type: str, payload: dict[str, Any]) -> None:
        if item_type == "trace":
            self._traces.append(payload)
        elif item_type == "span":
            self._spans.append(payload)

    def flush(self) -> None:
        if not self._traces and not self._spans:
            return
        response = httpx.post(
            f"{self.base_url}/api/ingest/batch",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"traces": self._traces, "spans": self._spans},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        self._traces.clear()
        self._spans.clear()

