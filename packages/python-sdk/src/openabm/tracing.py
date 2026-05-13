from __future__ import annotations

import contextvars
import functools
import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ParamSpec, TypeVar

from openabm.exporters import Exporter, InMemoryExporter
from openabm.ids import new_span_id, new_trace_id
from openabm.time import utc_now

P = ParamSpec("P")
R = TypeVar("R")

_current_span: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "openabm_current_span", default=None
)
_current_tracer: contextvars.ContextVar[Tracer | None] = contextvars.ContextVar(
    "openabm_current_tracer", default=None
)


PayloadRedactor = Callable[[Any], Any]
HIGH_PRIORITY_VALUES = {"high", "critical", "p0", "p1"}
ALWAYS_KEEP_STATUSES = {"error", "timeout", "cancelled"}
STREAM_EVENT_HINTS = ("stream", "delta", "token")


@dataclass(frozen=True)
class SamplingConfig:
    sample_rate: float = 1.0
    payload_max_bytes: int | None = None
    max_events_per_span: int | None = None
    stream_event_sample_rate: int = 1


class Tracer:
    def __init__(
        self,
        project: str,
        *,
        environment: str = "local",
        exporter: Exporter | None = None,
        capture_payloads: bool = True,
        redactors: list[PayloadRedactor] | None = None,
        sampling: SamplingConfig | None = None,
        sdk_name: str = "openabm-python",
        sdk_version: str = "0.0.0",
        prompt_version_id: str | None = None,
        agent_config_version_id: str | None = None,
        deployment_context_id: str | None = None,
        tool_version_ids: list[str] | None = None,
    ) -> None:
        self.project_id = project
        self.environment = environment
        self.exporter = exporter or InMemoryExporter()
        self.capture_payloads = capture_payloads
        self.redactors = redactors or []
        self.sampling = sampling or SamplingConfig()
        self.sdk_name = sdk_name
        self.sdk_version = sdk_version
        self.prompt_version_id = prompt_version_id
        self.agent_config_version_id = agent_config_version_id
        self.deployment_context_id = deployment_context_id
        self.tool_version_ids = sorted(set(tool_version_ids or []))
        if not 0 <= self.sampling.sample_rate <= 1:
            raise ValueError("sampling.sample_rate must be between 0 and 1")
        if self.sampling.stream_event_sample_rate < 1:
            raise ValueError("sampling.stream_event_sample_rate must be at least 1")

    def span(
        self,
        name: str,
        *,
        span_type: str = "function",
        attributes: dict[str, Any] | None = None,
        input: Any = None,
    ) -> Span:
        parent = _current_span.get()
        trace_id = parent.trace_id if parent else new_trace_id()
        sampled = (
            parent.sampled
            if parent
            else self._trace_is_sampled(trace_id, attributes or {})
        )
        return Span(
            tracer=self,
            trace_id=trace_id,
            span_id=new_span_id(),
            parent_span_id=parent.span_id if parent else None,
            name=name,
            span_type=span_type,
            attributes=attributes or {},
            input=input,
            sampled=sampled,
        )

    def flush(self) -> None:
        self.exporter.flush()

    def _payload(
        self,
        value: Any,
        *,
        force_capture: bool = False,
        sampled: bool = True,
    ) -> dict[str, Any]:
        if value is None:
            return {"mode": "omitted", "redaction_state": "omitted"}
        if not sampled and not force_capture:
            return {
                "mode": "omitted",
                "redaction_state": "omitted",
                "omission_reason": "sdk_trace_sampling",
            }
        if not self.capture_payloads:
            return {
                "mode": "omitted",
                "redaction_state": "omitted",
                "omission_reason": "payload_capture_disabled",
            }
        redacted = value
        for redactor in self.redactors:
            redacted = redactor(redacted)
        byte_size = _json_byte_size(redacted)
        max_bytes = self.sampling.payload_max_bytes
        if max_bytes is not None and byte_size > max_bytes and not force_capture:
            return {
                "mode": "omitted",
                "redaction_state": "omitted",
                "omission_reason": "sdk_payload_sampling",
                "byte_size_nullable": byte_size,
                "sampling_policy": {"payload_max_bytes": max_bytes},
            }
        return {"mode": "inline", "value": redacted, "redaction_state": "raw"}

    def _base_attributes(self) -> dict[str, Any]:
        attributes = {
            "openabm.project_id": self.project_id,
            "openabm.environment": self.environment,
            "openabm.sdk.name": self.sdk_name,
            "openabm.sdk.version": self.sdk_version,
        }
        if self.prompt_version_id:
            attributes["prompt_version_id"] = self.prompt_version_id
        if self.agent_config_version_id:
            attributes["agent_config_version_id"] = self.agent_config_version_id
        if self.deployment_context_id:
            attributes["deployment_context_id"] = self.deployment_context_id
        if self.tool_version_ids:
            attributes["tool_version_ids"] = self.tool_version_ids
        return attributes

    def _trace_is_sampled(self, trace_id: str, attributes: dict[str, Any]) -> bool:
        if _attributes_are_high_priority(attributes):
            return True
        if self.sampling.sample_rate >= 1:
            return True
        if self.sampling.sample_rate <= 0:
            return False
        digest = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()
        bucket = int(digest[:12], 16) / float(0xFFFFFFFFFFFF)
        return bucket < self.sampling.sample_rate


class Span:
    def __init__(
        self,
        *,
        tracer: Tracer,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        name: str,
        span_type: str,
        attributes: dict[str, Any],
        input: Any,
        sampled: bool,
    ) -> None:
        self.tracer = tracer
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.span_type = span_type
        self.sampled = sampled
        self.attributes = {
            **tracer._base_attributes(),
            "openabm.sampling.sampled": sampled,
            **attributes,
        }
        self.input = input
        self.output: Any = None
        self.status = "unknown"
        self.started_at = utc_now()
        self.ended_at: str | None = None
        self.events: list[dict[str, Any]] = []
        self._span_token: contextvars.Token[Span | None] | None = None
        self._tracer_token: contextvars.Token[Tracer | None] | None = None

    def __enter__(self) -> Span:
        self._span_token = _current_span.set(self)
        self._tracer_token = _current_tracer.set(self.tracer)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del traceback
        if exc is not None:
            self.status = "error"
            self.events.append(
                {
                    "name": "exception",
                    "time": utc_now(),
                    "attributes": {
                        "exception.type": exc_type.__name__ if exc_type else type(exc).__name__,
                        "exception.message": str(exc),
                    },
                }
            )
        elif self.status == "unknown":
            self.status = "ok"
        self.ended_at = utc_now()
        self._export()
        if self._span_token is not None:
            _current_span.reset(self._span_token)
        if self._tracer_token is not None:
            _current_tracer.reset(self._tracer_token)
        return False

    def set_output(self, output: Any) -> None:
        self.output = output

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "time": utc_now(), "attributes": attributes or {}})

    def _export(self) -> None:
        force_capture = self._preserve_full_fidelity()
        events = (
            self.events
            if force_capture
            else _sample_events(self.events, self.tracer.sampling, sampled=self.sampled)
        )
        span_payload = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "project_id": self.tracer.project_id,
            "name": self.name,
            "span_type": self.span_type,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "input": self.tracer._payload(
                self.input,
                force_capture=force_capture,
                sampled=self.sampled,
            ),
            "output": self.tracer._payload(
                self.output,
                force_capture=force_capture,
                sampled=self.sampled,
            ),
            "attributes": self.attributes,
            "events": events,
            "links": [],
        }
        self.tracer.exporter.export("span", span_payload)
        if self.parent_span_id is None:
            trace_payload = {
                "trace_id": self.trace_id,
                "project_id": self.tracer.project_id,
                "session_id": None,
                "user_external_id": None,
                "root_span_id": self.span_id,
                "environment": self.tracer.environment,
                "status": self.status,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "tags": [],
                "attributes": {
                    **self.tracer._base_attributes(),
                    "openabm.sampling.sampled": self.sampled,
                },
                "prompt_version_id": self.tracer.prompt_version_id,
                "agent_config_version_id": self.tracer.agent_config_version_id,
                "deployment_context_id": self.tracer.deployment_context_id,
                "tool_version_ids": self.tracer.tool_version_ids,
                "summary": self.name,
            }
            self.tracer.exporter.export("trace", trace_payload)

    def _preserve_full_fidelity(self) -> bool:
        return (
            self.status in ALWAYS_KEEP_STATUSES
            or _attributes_are_high_priority(self.attributes)
        )


def observe(
    *,
    name: str | None = None,
    span_type: str = "function",
    attributes: dict[str, Any] | None = None,
    tracer: Tracer | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        span_name = name or func.__name__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                active_tracer = tracer or _current_tracer.get()
                if active_tracer is None:
                    return await func(*args, **kwargs)
                with active_tracer.span(span_name, span_type=span_type, attributes=attributes):
                    result = await func(*args, **kwargs)
                    current = _current_span.get()
                    if current:
                        current.set_output(result)
                    return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            active_tracer = tracer or _current_tracer.get()
            if active_tracer is None:
                return func(*args, **kwargs)
            with active_tracer.span(span_name, span_type=span_type, attributes=attributes):
                result = func(*args, **kwargs)
                current = _current_span.get()
                if current:
                    current.set_output(result)
                return result

        return wrapper

    return decorator


def _attributes_are_high_priority(attributes: dict[str, Any]) -> bool:
    return (
        _truthy(attributes.get("openabm.keep"))
        or str(attributes.get("openabm.priority", "")).lower() in HIGH_PRIORITY_VALUES
        or bool(attributes.get("openabm.feedback"))
        or bool(attributes.get("openabm.behavior_ids"))
        or bool(attributes.get("openabm.dataset_ids"))
    )


def _sample_events(
    events: list[dict[str, Any]],
    config: SamplingConfig,
    *,
    sampled: bool,
) -> list[dict[str, Any]]:
    if not events:
        return []
    if not sampled:
        return [
            {
                "name": "openabm.events_omitted",
                "time": utc_now(),
                "attributes": {
                    "omission_reason": "sdk_trace_sampling",
                    "stream_events_omitted": 0,
                    "other_events_omitted": len(events),
                    "preserved_metadata": True,
                },
            }
        ]
    sampled_events, stream_omitted = _sample_stream_events(
        events,
        config.stream_event_sample_rate,
    )
    capped, capped_omitted = _cap_events(sampled_events, config.max_events_per_span)
    if stream_omitted or capped_omitted:
        capped.append(
            {
                "name": "openabm.events_omitted",
                "time": utc_now(),
                "attributes": {
                    "omission_reason": "sdk_event_sampling",
                    "stream_events_omitted": stream_omitted,
                    "other_events_omitted": capped_omitted,
                    "preserved_metadata": True,
                },
            }
        )
    return capped


def _sample_stream_events(
    events: list[dict[str, Any]],
    sample_rate: int,
) -> tuple[list[dict[str, Any]], int]:
    if sample_rate <= 1:
        return events, 0
    kept: list[dict[str, Any]] = []
    omitted = 0
    stream_index = 0
    for event in events:
        if _is_stream_event(event):
            if stream_index % sample_rate == 0:
                kept.append(event)
            else:
                omitted += 1
            stream_index += 1
            continue
        kept.append(event)
    return kept, omitted


def _cap_events(
    events: list[dict[str, Any]],
    max_events: int | None,
) -> tuple[list[dict[str, Any]], int]:
    if max_events is None or max_events <= 0 or len(events) <= max_events:
        return events, 0
    if max_events == 1:
        return [events[-1]], len(events) - 1
    head_count = max_events // 2
    tail_count = max_events - head_count
    return events[:head_count] + events[-tail_count:], len(events) - max_events


def _is_stream_event(event: dict[str, Any]) -> bool:
    name = event.get("name", "").lower()
    if any(hint in name for hint in STREAM_EVENT_HINTS):
        return True
    attributes = event.get("attributes") if isinstance(event.get("attributes"), dict) else {}
    return str(attributes.get("openabm.event_kind", "")).lower() in {
        "stream_delta",
        "model_delta",
        "token_delta",
    }


def _json_byte_size(value: Any) -> int:
    return len(json.dumps(value, default=str, sort_keys=True).encode("utf-8"))


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
