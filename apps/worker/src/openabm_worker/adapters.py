from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from openabm_worker.model_runtime import ProviderHealth

ADAPTER_CONTRACT_NAMES = {
    "ModelProviderAdapter",
    "EmbeddingProviderAdapter",
    "TraceStore",
    "MetadataStore",
    "PayloadStore",
    "SearchIndex",
    "SimilarityIndex",
    "QueueAdapter",
    "CodeSandboxAdapter",
    "EvalRunner",
    "NotificationAdapter",
    "SdkIntegrationPlugin",
    "InvestigationRunner",
    "ImpactReportBuilder",
    "RootCauseAnalyzer",
    "AgentContextPackBuilder",
    "GroundingCheckAdapter",
}


@runtime_checkable
class ModelProviderAdapter(Protocol):
    def health_check(self) -> ProviderHealth: ...

    async def chat_completion(
        self,
        request: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]: ...

    async def structured_completion(
        self,
        request: dict[str, Any],
        schema: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]: ...

    async def tool_completion(
        self,
        request: dict[str, Any],
        tools: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]: ...


@runtime_checkable
class EmbeddingProviderAdapter(Protocol):
    def health_check(self) -> ProviderHealth: ...

    async def embed_documents(
        self,
        documents: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]: ...


class TraceStore(Protocol):
    async def ingest_spans(self, spans: list[dict[str, Any]]) -> dict[str, Any]: ...

    async def get_trace(self, project_id: str, trace_id: str) -> dict[str, Any]: ...

    async def search_traces(self, query: dict[str, Any]) -> dict[str, Any]: ...

    async def apply_retention(self, policy: dict[str, Any]) -> dict[str, Any]: ...


class MetadataStore(Protocol):
    async def create_project(self, request: dict[str, Any]) -> dict[str, Any]: ...

    async def create_judge_version(self, request: dict[str, Any]) -> dict[str, Any]: ...

    async def create_dataset_version(self, request: dict[str, Any]) -> dict[str, Any]: ...

    async def append_audit_log(self, event: dict[str, Any]) -> None: ...


class PayloadStore(Protocol):
    async def put_payload(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get_payload(
        self,
        ref: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def delete_payload(self, ref: dict[str, Any]) -> dict[str, Any]: ...


class SearchIndex(Protocol):
    async def index_document(self, document: dict[str, Any]) -> None: ...

    async def search(self, query: dict[str, Any]) -> dict[str, Any]: ...

    async def rebuild(self, scope: dict[str, Any]) -> dict[str, Any]: ...


class SimilarityIndex(Protocol):
    async def upsert_representation(self, item: dict[str, Any]) -> None: ...

    async def search_similar(self, query: dict[str, Any]) -> dict[str, Any]: ...

    async def rebuild(self, scope: dict[str, Any]) -> dict[str, Any]: ...


class QueueAdapter(Protocol):
    async def enqueue(
        self,
        job: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def lease(self, queue_name: str, timeout_seconds: int) -> dict[str, Any]: ...

    async def ack(self, lease: dict[str, Any]) -> None: ...

    async def nack(self, lease: dict[str, Any], retry: dict[str, Any]) -> None: ...


class CodeSandboxAdapter(Protocol):
    async def run_code_judge(
        self,
        bundle: dict[str, Any],
        trace: dict[str, Any],
        limits: dict[str, Any],
    ) -> dict[str, Any]: ...


class EvalRunner(Protocol):
    async def run_example(
        self,
        example: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]: ...


class NotificationAdapter(Protocol):
    async def send(self, request: dict[str, Any]) -> dict[str, Any]: ...

    async def validate_target(self, target: dict[str, Any]) -> dict[str, Any]: ...


class SdkIntegrationPlugin(Protocol):
    def instrument(self, tracer: Any, target: object, config: dict[str, Any]) -> object: ...

    def supported_versions(self) -> dict[str, Any]: ...

    def captured_metadata(self) -> list[str]: ...


class InvestigationRunner(Protocol):
    async def start(self, request: dict[str, Any]) -> dict[str, Any]: ...

    async def get_status(self, investigation_run_id: str) -> dict[str, Any]: ...


class ImpactReportBuilder(Protocol):
    async def build(self, request: dict[str, Any]) -> dict[str, Any]: ...


class RootCauseAnalyzer(Protocol):
    async def compare_cohorts(
        self,
        failing: dict[str, Any],
        baseline: dict[str, Any],
        dimensions: list[str],
    ) -> dict[str, Any]: ...


class AgentContextPackBuilder(Protocol):
    async def build(
        self,
        request: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict[str, Any]: ...


class GroundingCheckAdapter(Protocol):
    async def check_claims(self, request: dict[str, Any]) -> dict[str, Any]: ...
