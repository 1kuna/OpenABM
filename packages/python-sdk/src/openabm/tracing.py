from __future__ import annotations

import contextvars
import functools
import inspect
from collections.abc import Callable
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


class Tracer:
    def __init__(
        self,
        project: str,
        *,
        environment: str = "local",
        exporter: Exporter | None = None,
        capture_payloads: bool = True,
        redactors: list[PayloadRedactor] | None = None,
        sdk_name: str = "openabm-python",
        sdk_version: str = "0.0.0",
    ) -> None:
        self.project_id = project
        self.environment = environment
        self.exporter = exporter or InMemoryExporter()
        self.capture_payloads = capture_payloads
        self.redactors = redactors or []
        self.sdk_name = sdk_name
        self.sdk_version = sdk_version

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
        return Span(
            tracer=self,
            trace_id=trace_id,
            span_id=new_span_id(),
            parent_span_id=parent.span_id if parent else None,
            name=name,
            span_type=span_type,
            attributes=attributes or {},
            input=input,
        )

    def flush(self) -> None:
        self.exporter.flush()

    def _payload(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {"mode": "omitted", "redaction_state": "omitted"}
        if not self.capture_payloads:
            return {"mode": "omitted", "redaction_state": "omitted"}
        redacted = value
        for redactor in self.redactors:
            redacted = redactor(redacted)
        return {"mode": "inline", "value": redacted, "redaction_state": "raw"}

    def _base_attributes(self) -> dict[str, Any]:
        return {
            "openabm.project_id": self.project_id,
            "openabm.environment": self.environment,
            "openabm.sdk.name": self.sdk_name,
            "openabm.sdk.version": self.sdk_version,
        }


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
    ) -> None:
        self.tracer = tracer
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.span_type = span_type
        self.attributes = {**tracer._base_attributes(), **attributes}
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
            "input": self.tracer._payload(self.input),
            "output": self.tracer._payload(self.output),
            "attributes": self.attributes,
            "events": self.events,
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
                "attributes": self.tracer._base_attributes(),
                "summary": self.name,
            }
            self.tracer.exporter.export("trace", trace_payload)


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

