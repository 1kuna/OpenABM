from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from openabm_api.settings import Settings


class ModelCallsDisabled(RuntimeError):
    pass


class ModelConfigurationError(RuntimeError):
    pass


class ModelResourceGuardError(ModelConfigurationError):
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
            details={"reason": "Model calls are disabled by configuration."},
        )

    async def chat_completion(
        self,
        request: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del request, timeout_seconds
        raise ModelCallsDisabled("Model-backed chat completion is disabled.")

    async def structured_completion(
        self,
        request: dict[str, Any],
        schema: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del request, schema, timeout_seconds
        raise ModelCallsDisabled("Model-backed structured completion is disabled.")

    async def tool_completion(
        self,
        request: dict[str, Any],
        tools: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del request, tools, timeout_seconds
        raise ModelCallsDisabled("Model-backed tool completion is disabled.")


class DisabledEmbeddingProvider:
    adapter_name = "disabled-embedding"
    supported_capabilities: list[str] = []

    def __init__(
        self,
        reason: str = "Embeddings are disabled until a provider is configured.",
    ) -> None:
        self.reason = reason

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            adapter_name=self.adapter_name,
            status="disabled",
            supported_capabilities=[],
            details={"reason": self.reason},
        )

    async def embed_documents(
        self,
        documents: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del documents, timeout_seconds
        raise ModelCallsDisabled(self.reason)


class OpenAICompatibleModelProvider:
    adapter_name = "openai-compatible-chat"
    supported_capabilities = ["chat_completion", "structured_completion", "tool_completion"]
    configuration_schema = {
        "type": "object",
        "required": ["base_url", "chat_model"],
        "properties": {
            "base_url": {"type": "string"},
            "chat_model": {"type": "string"},
            "context_length": {"type": "integer", "minimum": 32768},
        },
    }
    request_shape = "OpenAI-compatible /chat/completions"
    response_shape = "OpenAI-compatible choices[0].message.content/tool_calls"
    timeout_behavior = "No generation timeout is applied by OpenABM."
    rate_limit_behavior = "Provider-defined; OpenABM surfaces transport errors."
    cost_reporting_behavior = "Uses provider usage metadata when returned."
    privacy_mode_support = "Local endpoints allowed without enabling external calls."
    structured_output_support_level = "JSON prompt with strict parse and repair."
    known_limitations = [
        "JSON schema response_format support varies by serving runtime.",
        "Repair is bounded and never invents evidence citations.",
    ]
    conformance_tests = ["tests/unit/test_model_runtime.py"]

    def __init__(
        self,
        *,
        base_url: str,
        chat_model: str,
        api_key: str | None = None,
        context_length: int = 262144,
        min_available_memory_mb: int = 0,
        available_memory_mb: Callable[[], float | None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if context_length < 32768:
            raise ModelConfigurationError("Model context length must be at least 32768.")
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.api_key = api_key
        self.context_length = context_length
        self.min_available_memory_mb = max(0, int(min_available_memory_mb))
        self._available_memory_mb = available_memory_mb or system_available_memory_mb
        self._transport = transport

    def health_check(self) -> ProviderHealth:
        available_memory_mb = _safe_available_memory_mb(self._available_memory_mb)
        return ProviderHealth(
            adapter_name=self.adapter_name,
            status="configured",
            supported_capabilities=self.supported_capabilities,
            details={
                "base_url": self.base_url,
                "chat_model": self.chat_model,
                "context_length": self.context_length,
                "min_available_memory_mb": self.min_available_memory_mb,
                "available_memory_mb": available_memory_mb,
                "memory_guard_status": _memory_guard_status(
                    available_memory_mb,
                    self.min_available_memory_mb,
                ),
                "timeout_behavior": self.timeout_behavior,
            },
        )

    async def chat_completion(
        self,
        request: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del timeout_seconds
        payload = {
            "model": request.get("model") or self.chat_model,
            "messages": request["messages"],
        }
        for key in ["temperature", "top_p", "metadata", "max_tokens", "max_completion_tokens"]:
            if key in request:
                payload[key] = request[key]
        return await self._post_chat(payload)

    async def structured_completion(
        self,
        request: dict[str, Any],
        schema: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del timeout_seconds
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        messages = _with_structured_output_instruction(request["messages"], schema)
        response = await self._post_chat(
            {
                "model": request.get("model") or self.chat_model,
                "messages": messages,
                "temperature": request.get("temperature", 0.1),
                **_completion_length(request),
            }
        )
        text = _message_text(response)
        parsed, parse_error = _parse_json(text)
        validation_errors = list(validator.iter_errors(parsed)) if parsed is not None else []
        if parsed is not None and not validation_errors:
            return _structured_success(parsed, text, response, self, repaired=False)

        repair = await self._repair_structured_output(
            messages=messages,
            schema=schema,
            invalid_output=text,
            parse_error=parse_error,
            validation_errors=validation_errors,
            request=request,
        )
        repaired_text = _message_text(repair)
        repaired, repaired_parse_error = _parse_json(repaired_text)
        repaired_errors = list(validator.iter_errors(repaired)) if repaired is not None else []
        if repaired is not None and not repaired_errors:
            return _structured_success(repaired, repaired_text, repair, self, repaired=True)

        return {
            "status": "invalid_output",
            "raw_output": repaired_text or text,
            "parse_error": repaired_parse_error or parse_error,
            "validation_errors": [error.message for error in repaired_errors or validation_errors],
            "provider": self.adapter_name,
            "model": self.chat_model,
        }

    async def tool_completion(
        self,
        request: dict[str, Any],
        tools: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del timeout_seconds
        for tool in tools:
            parameters = tool.get("function", {}).get("parameters")
            if isinstance(parameters, dict):
                Draft202012Validator.check_schema(parameters)
        payload = {
            "model": request.get("model") or self.chat_model,
            "messages": request["messages"],
            "tools": tools,
            "temperature": request.get("temperature", 0.1),
            **_completion_length(request),
        }
        if "tool_choice" in request:
            payload["tool_choice"] = _tool_choice(request["tool_choice"])
        try:
            response = await self._post_chat(payload)
        except httpx.HTTPStatusError as exc:
            return {
                "status": "invalid_output",
                "raw_message": {},
                "finish_reason": None,
                "parse_errors": [
                    f"tool request rejected: {exc.response.status_code} {exc.response.text}"
                ],
                "usage": None,
                "provider": self.adapter_name,
                "model": self.chat_model,
            }
        parsed, errors = _tool_calls(response)
        if parsed and not errors:
            return {
                "status": "succeeded",
                "tool_calls": parsed,
                "raw_message": response["choices"][0]["message"],
                "usage": response.get("usage"),
                "provider": self.adapter_name,
                "model": self.chat_model,
            }
        return {
            "status": "invalid_output",
            "raw_message": response["choices"][0].get("message", {}),
            "finish_reason": response["choices"][0].get("finish_reason"),
            "parse_errors": errors or ["model did not return parsed tool_calls"],
            "usage": response.get("usage"),
            "provider": self.adapter_name,
            "model": self.chat_model,
        }

    async def _repair_structured_output(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        invalid_output: str,
        parse_error: str | None,
        validation_errors: list[Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        repair_prompt = {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Repair the previous answer so it is valid JSON matching the schema. "
                    "Do not add evidence span IDs that were not present in the trace context.",
                    "schema": schema,
                    "invalid_output": invalid_output,
                    "parse_error": parse_error,
                    "validation_errors": [error.message for error in validation_errors],
                },
                sort_keys=True,
            ),
        }
        return await self._post_chat(
            {
                "model": request.get("model") or self.chat_model,
                "messages": [*messages, repair_prompt],
                "temperature": request.get("temperature", 0.1),
                **_completion_length(request),
            }
        )

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        _enforce_memory_guard(
            available_memory_mb=self._available_memory_mb,
            min_available_memory_mb=self.min_available_memory_mb,
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=None, transport=self._transport) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        return response.json()


class OpenAICompatibleEmbeddingProvider:
    adapter_name = "openai-compatible-embedding"
    supported_capabilities = ["embedding"]
    configuration_schema = {
        "type": "object",
        "required": ["base_url", "embedding_model"],
        "properties": {
            "base_url": {"type": "string"},
            "embedding_model": {"type": "string"},
        },
    }
    request_shape = "OpenAI-compatible /embeddings"
    response_shape = "OpenAI-compatible data[index].embedding"
    timeout_behavior = "No generation timeout is applied by OpenABM."
    rate_limit_behavior = "Provider-defined; OpenABM surfaces transport errors."
    cost_reporting_behavior = "Uses provider usage metadata when returned."
    privacy_mode_support = "Local endpoints allowed without enabling external calls."
    structured_output_support_level = "Not applicable for embeddings."
    known_limitations = [
        "Embedding dimensions are provider-defined and must be consistent per response.",
        "This adapter only records vectors returned by the provider; it does not choose an index.",
    ]
    conformance_tests = ["tests/unit/test_model_runtime.py"]

    def __init__(
        self,
        *,
        base_url: str,
        embedding_model: str,
        api_key: str | None = None,
        min_available_memory_mb: int = 0,
        available_memory_mb: Callable[[], float | None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.api_key = api_key
        self.min_available_memory_mb = max(0, int(min_available_memory_mb))
        self._available_memory_mb = available_memory_mb or system_available_memory_mb
        self._transport = transport

    def health_check(self) -> ProviderHealth:
        available_memory_mb = _safe_available_memory_mb(self._available_memory_mb)
        return ProviderHealth(
            adapter_name=self.adapter_name,
            status="configured",
            supported_capabilities=self.supported_capabilities,
            details={
                "base_url": self.base_url,
                "embedding_model": self.embedding_model,
                "min_available_memory_mb": self.min_available_memory_mb,
                "available_memory_mb": available_memory_mb,
                "memory_guard_status": _memory_guard_status(
                    available_memory_mb,
                    self.min_available_memory_mb,
                ),
                "timeout_behavior": self.timeout_behavior,
            },
        )

    async def embed_documents(
        self,
        documents: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del timeout_seconds
        payload = {
            "model": self.embedding_model,
            "input": [str(document.get("text") or "") for document in documents],
        }
        response = await self._post_embeddings(payload)
        embeddings, errors = _embedding_vectors(response, documents)
        if errors:
            return {
                "status": "invalid_output",
                "embeddings": [],
                "parse_errors": errors,
                "usage": response.get("usage"),
                "provider": self.adapter_name,
                "model": self.embedding_model,
            }
        return {
            "status": "succeeded",
            "embeddings": embeddings,
            "usage": response.get("usage"),
            "provider": self.adapter_name,
            "model": self.embedding_model,
        }

    async def _post_embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        _enforce_memory_guard(
            available_memory_mb=self._available_memory_mb,
            min_available_memory_mb=self.min_available_memory_mb,
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=None, transport=self._transport) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        return response.json()


def model_provider_from_settings(
    settings: Settings,
) -> DisabledModelProvider | OpenAICompatibleModelProvider:
    if settings.model_mode == "disabled":
        return DisabledModelProvider()
    if settings.model_mode not in {"local", "external", "mixed"}:
        raise ModelConfigurationError(f"Unknown model mode: {settings.model_mode}")
    if not settings.chat_model:
        raise ModelConfigurationError("OPENABM_CHAT_MODEL is required when model mode is enabled.")
    if not settings.model_endpoint_is_local and not settings.allow_external_model_calls:
        raise ModelConfigurationError(
            "External model endpoint configured while OPENABM_ALLOW_EXTERNAL_MODEL_CALLS is false."
        )
    return OpenAICompatibleModelProvider(
        base_url=settings.model_base_url,
        chat_model=settings.chat_model,
        api_key=settings.model_api_key,
        context_length=settings.model_context_length,
        min_available_memory_mb=settings.model_min_available_memory_mb,
    )


def embedding_provider_from_settings(
    settings: Settings,
) -> DisabledEmbeddingProvider | OpenAICompatibleEmbeddingProvider:
    if settings.model_mode == "disabled":
        return DisabledEmbeddingProvider()
    if settings.model_mode not in {"local", "external", "mixed"}:
        raise ModelConfigurationError(f"Unknown model mode: {settings.model_mode}")
    if not settings.embedding_model:
        return DisabledEmbeddingProvider("OPENABM_EMBEDDING_MODEL is not configured.")
    if not settings.model_endpoint_is_local and not settings.allow_external_model_calls:
        raise ModelConfigurationError(
            "External model endpoint configured while OPENABM_ALLOW_EXTERNAL_MODEL_CALLS is false."
        )
    return OpenAICompatibleEmbeddingProvider(
        base_url=settings.model_base_url,
        embedding_model=settings.embedding_model,
        api_key=settings.model_api_key,
        min_available_memory_mb=settings.model_min_available_memory_mb,
    )


def system_available_memory_mb() -> float | None:
    if sys.platform == "darwin":
        return _darwin_available_memory_mb()
    if sys.platform.startswith("linux"):
        return _linux_available_memory_mb()
    return None


def _enforce_memory_guard(
    *,
    available_memory_mb: Callable[[], float | None],
    min_available_memory_mb: int,
) -> None:
    if min_available_memory_mb <= 0:
        return
    available = available_memory_mb()
    if available is None:
        return
    if available < min_available_memory_mb:
        raise ModelResourceGuardError(
            "Available system memory "
            f"({available:.0f} MB) is below OPENABM_MODEL_MIN_AVAILABLE_MEMORY_MB "
            f"({min_available_memory_mb} MB); skipping the model call."
        )


def _safe_available_memory_mb(
    available_memory_mb: Callable[[], float | None],
) -> float | None:
    try:
        return available_memory_mb()
    except Exception:
        return None


def _memory_guard_status(
    available_memory_mb: float | None,
    min_available_memory_mb: int,
) -> str:
    if min_available_memory_mb <= 0:
        return "disabled"
    if available_memory_mb is None:
        return "unknown"
    if available_memory_mb < min_available_memory_mb:
        return "blocked"
    return "ready"


def _darwin_available_memory_mb() -> float | None:
    try:
        result = subprocess.run(
            ["vm_stat"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    page_size_match = re.search(r"page size of (\d+) bytes", result.stdout)
    if page_size_match is None:
        return None
    page_size = int(page_size_match.group(1))
    page_counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        name, separator, value = line.partition(":")
        if not separator:
            continue
        if name not in {"Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"}:
            continue
        cleaned = re.sub(r"[^0-9]", "", value)
        if cleaned.isdigit():
            page_counts[name] = int(cleaned)
    available_pages = sum(page_counts.values())
    return available_pages * page_size / 1024 / 1024


def _linux_available_memory_mb() -> float | None:
    try:
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) / 1024
    except OSError:
        return None
    return None


def _with_structured_output_instruction(
    messages: list[dict[str, str]],
    schema: dict[str, Any],
) -> list[dict[str, str]]:
    instruction = {
        "role": "system",
        "content": (
            "Return exactly one JSON object and no markdown. The JSON must validate "
            "against this schema: "
            + json.dumps(schema, sort_keys=True)
        ),
    }
    return [instruction, *messages]


def _completion_length(request: dict[str, Any]) -> dict[str, int]:
    if "max_completion_tokens" in request:
        return {"max_completion_tokens": int(request["max_completion_tokens"])}
    if "max_tokens" in request:
        return {"max_tokens": int(request["max_tokens"])}
    return {}


def _tool_choice(value: Any) -> Any:
    if isinstance(value, dict):
        return "required"
    return value


def _message_text(response: dict[str, Any]) -> str:
    return str(response["choices"][0]["message"].get("content") or "")


def _tool_calls(response: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    message = response["choices"][0].get("message", {})
    tool_calls = message.get("tool_calls") or []
    parsed = []
    errors = []
    for index, tool_call in enumerate(tool_calls):
        function = tool_call.get("function") or {}
        name = function.get("name")
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except JSONDecodeError as exc:
            errors.append(f"tool_call[{index}] arguments JSON parse failed: {exc}")
            continue
        if not isinstance(arguments, dict):
            errors.append(f"tool_call[{index}] arguments must be an object")
            continue
        if not isinstance(name, str) or not name:
            errors.append(f"tool_call[{index}] function.name is required")
            continue
        parsed.append(
            {
                "id": tool_call.get("id"),
                "type": tool_call.get("type"),
                "name": name,
                "arguments": arguments,
            }
        )
    return parsed, errors


def _parse_json(text: str) -> tuple[Any | None, str | None]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:]
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end >= start:
        candidate = candidate[start : end + 1]
    try:
        return json.loads(candidate), None
    except JSONDecodeError as exc:
        return None, str(exc)


def _structured_success(
    value: dict[str, Any],
    raw_output: str,
    response: dict[str, Any],
    provider: OpenAICompatibleModelProvider,
    *,
    repaired: bool,
) -> dict[str, Any]:
    return {
        "status": "succeeded",
        "value": value,
        "raw_output": raw_output,
        "repaired": repaired,
        "usage": response.get("usage"),
        "provider": provider.adapter_name,
        "model": provider.chat_model,
    }


def _embedding_vectors(
    response: dict[str, Any],
    documents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    data = response.get("data")
    if not isinstance(data, list):
        return [], ["embedding response data must be a list"]
    by_index = {}
    errors = []
    for item in data:
        if not isinstance(item, dict):
            errors.append("embedding data item must be an object")
            continue
        index = item.get("index")
        raw_embedding = item.get("embedding")
        if not isinstance(index, int):
            errors.append("embedding data item index must be an integer")
            continue
        if not isinstance(raw_embedding, list) or not raw_embedding:
            errors.append(f"embedding[{index}] must be a non-empty list")
            continue
        vector = []
        for value in raw_embedding:
            if not isinstance(value, int | float):
                errors.append(f"embedding[{index}] contains a non-numeric value")
                vector = []
                break
            vector.append(float(value))
        if vector:
            by_index[index] = vector
    if errors:
        return [], errors
    if set(by_index) != set(range(len(documents))):
        return [], ["embedding response indexes must match input document indexes"]
    dimensions = {len(vector) for vector in by_index.values()}
    if len(dimensions) != 1:
        return [], ["embedding vectors must have a consistent dimension"]
    return [
        {
            "document_id": str(
                documents[index].get("document_id")
                or documents[index].get("id")
                or index
            ),
            "embedding": by_index[index],
            "index": index,
        }
        for index in range(len(documents))
    ], []
