from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from openabm.tracing import observe


@dataclass(frozen=True)
class IntegrationWrapperContract:
    name: str
    supported_package: str
    supported_versions: str
    instrumentation_hooks: tuple[str, ...]
    captured_metadata: tuple[str, ...]
    payload_capture_behavior: str
    redaction_behavior: str
    known_limitations: tuple[str, ...] = field(default_factory=tuple)
    example_code: str = ""
    acceptance_tests: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        required_strings = {
            "name": self.name,
            "supported_package": self.supported_package,
            "supported_versions": self.supported_versions,
            "payload_capture_behavior": self.payload_capture_behavior,
            "redaction_behavior": self.redaction_behavior,
        }
        for field_name, value in required_strings.items():
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        if not self.instrumentation_hooks:
            raise ValueError("instrumentation_hooks must include at least one hook")
        if not self.captured_metadata:
            raise ValueError("captured_metadata must include at least one metadata field")
        if not self.acceptance_tests:
            raise ValueError("acceptance_tests must include at least one test or check")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "supported_package": self.supported_package,
            "supported_versions": self.supported_versions,
            "instrumentation_hooks": list(self.instrumentation_hooks),
            "captured_metadata": list(self.captured_metadata),
            "payload_capture_behavior": self.payload_capture_behavior,
            "redaction_behavior": self.redaction_behavior,
            "known_limitations": list(self.known_limitations),
            "example_code": self.example_code,
            "acceptance_tests": list(self.acceptance_tests),
        }


@runtime_checkable
class SdkIntegrationPlugin(Protocol):
    @property
    def contract(self) -> IntegrationWrapperContract: ...

    def instrument(
        self,
        tracer: Any,
        target: object,
        config: Mapping[str, Any] | None = None,
    ) -> object: ...


class IntegrationRegistry:
    def __init__(self, plugins: list[SdkIntegrationPlugin] | None = None) -> None:
        self._plugins: dict[str, SdkIntegrationPlugin] = {}
        for plugin in plugins or []:
            self.register(plugin)

    def register(self, plugin: SdkIntegrationPlugin) -> None:
        contract = plugin.contract
        contract.validate()
        if contract.name in self._plugins:
            raise ValueError(f"Integration plugin already registered: {contract.name}")
        self._plugins[contract.name] = plugin

    def get(self, name: str) -> SdkIntegrationPlugin:
        try:
            return self._plugins[name]
        except KeyError as exc:
            raise KeyError(f"Integration plugin is not registered: {name}") from exc

    def list_contracts(self) -> list[dict[str, Any]]:
        return [
            self._plugins[name].contract.as_dict()
            for name in sorted(self._plugins)
        ]

    def instrument(
        self,
        name: str,
        tracer: Any,
        target: object,
        config: Mapping[str, Any] | None = None,
    ) -> object:
        return self.get(name).instrument(tracer, target, config or {})


class MethodSpanIntegrationPlugin:
    @property
    def contract(self) -> IntegrationWrapperContract:
        return IntegrationWrapperContract(
            name="generic-method-span",
            supported_package="any Python callable or object with callable methods",
            supported_versions="n/a",
            instrumentation_hooks=("callable", "method"),
            captured_metadata=("method_name", "span_type", "configured_attributes"),
            payload_capture_behavior=(
                "uses the supplied tracer's payload capture and redaction settings"
            ),
            redaction_behavior="delegates input/output payload handling to the supplied tracer",
            known_limitations=(
                "does not patch class-level special methods",
                "does not auto-discover framework-specific callback hooks",
            ),
            example_code=(
                "registry.instrument('generic-method-span', tracer, agent, "
                "{'methods': ['run'], 'span_type': 'agent'})"
            ),
            acceptance_tests=(
                "wraps a callable method and records an OpenABM span",
                "wraps standalone callables without changing their return value",
            ),
        )

    def instrument(
        self,
        tracer: Any,
        target: object,
        config: Mapping[str, Any] | None = None,
    ) -> object:
        settings = dict(config or {})
        methods = [str(method) for method in settings.get("methods", [])]
        span_type = str(settings.get("span_type") or "function")
        attributes = dict(settings.get("attributes") or {})
        span_name_prefix = str(settings.get("span_name_prefix") or "")

        if callable(target) and not methods:
            span_name = span_name_prefix + getattr(target, "__name__", target.__class__.__name__)
            return observe(
                name=span_name,
                span_type=span_type,
                attributes=attributes,
                tracer=tracer,
            )(target)

        if not methods:
            methods = ["run"]
        for method_name in methods:
            method = getattr(target, method_name, None)
            if not callable(method):
                raise AttributeError(f"Target has no callable method: {method_name}")
            span_name = span_name_prefix + method_name
            wrapped = observe(
                name=span_name,
                span_type=span_type,
                attributes={"openabm.integration.method": method_name, **attributes},
                tracer=tracer,
            )(method)
            setattr(target, method_name, wrapped)
        return target


def default_integration_registry() -> IntegrationRegistry:
    return IntegrationRegistry([MethodSpanIntegrationPlugin()])
