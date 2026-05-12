from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ModelCallsDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderHealth:
    adapter_name: str
    status: str
    supported_capabilities: list[str]
    details: dict[str, Any]


class DisabledModelProvider:
    adapter_name = "disabled"
    supported_capabilities: list[str] = []

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            adapter_name=self.adapter_name,
            status="disabled",
            supported_capabilities=[],
            details={"reason": "Model calls are disabled for this scaffold pass."},
        )

    async def chat_completion(
        self,
        request: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        del request, timeout_seconds
        raise ModelCallsDisabled("Model-backed chat completion is disabled.")

    async def structured_completion(
        self,
        request: dict[str, Any],
        schema: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        del request, schema, timeout_seconds
        raise ModelCallsDisabled("Model-backed structured completion is disabled.")


class DisabledEmbeddingProvider:
    adapter_name = "disabled-embedding"
    supported_capabilities: list[str] = []

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            adapter_name=self.adapter_name,
            status="disabled",
            supported_capabilities=[],
            details={"reason": "Embeddings are disabled until LLM/model work is enabled."},
        )

    async def embed_documents(
        self,
        documents: list[dict[str, Any]],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        del documents, timeout_seconds
        raise ModelCallsDisabled("Embedding generation is disabled.")

