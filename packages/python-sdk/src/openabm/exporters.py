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
        max_buffered_items: int = 1000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_buffered_items = max_buffered_items
        self._traces: list[dict[str, Any]] = []
        self._spans: list[dict[str, Any]] = []
        self.dropped_items: list[dict[str, Any]] = []

    def export(self, item_type: str, payload: dict[str, Any]) -> None:
        if self.max_buffered_items > 0 and self._buffered_count() >= self.max_buffered_items:
            if _is_high_priority(payload):
                self._drop_oldest_buffered_item()
            else:
                self.dropped_items.append(
                    {
                        "type": item_type,
                        "id": _payload_id(item_type, payload),
                        "reason": "sdk_retry_queue_full",
                    }
                )
                return
        if item_type == "trace":
            self._traces.append(payload)
        elif item_type == "span":
            self._spans.append(payload)

    def flush(self) -> None:
        if not self._traces and not self._spans:
            return
        response = httpx.post(
            f"{self.base_url}/v1/ingest/batch",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "traces": self._traces,
                "spans": self._spans,
                "sdk_diagnostics": {"dropped_items": self.dropped_items},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        self._traces.clear()
        self._spans.clear()
        self.dropped_items.clear()

    def _buffered_count(self) -> int:
        return len(self._traces) + len(self._spans)

    def _drop_oldest_buffered_item(self) -> None:
        collections = [("span", self._spans), ("trace", self._traces)]
        for item_type, items in collections:
            for index, item in enumerate(items):
                if not _is_high_priority(item):
                    dropped = items.pop(index)
                    self.dropped_items.append(
                        {
                            "type": item_type,
                            "id": _payload_id(item_type, dropped),
                            "reason": "evicted_for_high_priority_item",
                        }
                    )
                    return
        item_type, items = collections[0] if self._spans else collections[1]
        dropped = items.pop(0)
        self.dropped_items.append(
            {
                "type": item_type,
                "id": _payload_id(item_type, dropped),
                "reason": "evicted_for_high_priority_item",
            }
        )


def _is_high_priority(payload: dict[str, Any]) -> bool:
    attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
    return (
        payload.get("status") in {"error", "timeout", "cancelled"}
        or _truthy(attributes.get("openabm.keep"))
        or str(attributes.get("openabm.priority", "")).lower() in {"high", "critical", "p0", "p1"}
        or bool(attributes.get("openabm.feedback"))
        or bool(attributes.get("openabm.behavior_ids"))
        or bool(attributes.get("openabm.dataset_ids"))
    )


def _payload_id(item_type: str, payload: dict[str, Any]) -> Any:
    return payload.get("trace_id") if item_type == "trace" else payload.get("span_id")


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
