from __future__ import annotations

import json
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


class DisabledEmbeddingProvider:
    adapter_name = "disabled-embedding"
    supported_capabilities: list[str] = []

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            adapter_name=self.adapter_name,
            status="disabled",
            supported_capabilities=[],
            details={"reason": "Embeddings are disabled until a provider is configured."},
        )

    async def embed_documents(
        self,
        documents: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del documents, timeout_seconds
        raise ModelCallsDisabled("Embedding generation is disabled.")


class OpenAICompatibleModelProvider:
    adapter_name = "openai-compatible-chat"
    supported_capabilities = ["chat_completion", "structured_completion"]
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
    response_shape = "OpenAI-compatible choices[0].message.content"
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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if context_length < 32768:
            raise ModelConfigurationError("Model context length must be at least 32768.")
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.api_key = api_key
        self.context_length = context_length
        self._transport = transport

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            adapter_name=self.adapter_name,
            status="configured",
            supported_capabilities=self.supported_capabilities,
            details={
                "base_url": self.base_url,
                "chat_model": self.chat_model,
                "context_length": self.context_length,
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
    )


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


def _message_text(response: dict[str, Any]) -> str:
    return str(response["choices"][0]["message"]["content"])


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
