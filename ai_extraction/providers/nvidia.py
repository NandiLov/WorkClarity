"""NVIDIA multimodal extraction adapter (OpenAI-compatible Chat Completions)."""

from __future__ import annotations

import time
from typing import Any

from ai_extraction.providers.base import (
    ExtractionAdapter,
    HttpJsonSender,
    ProviderExtractionRequest,
    ProviderRawResponse,
    ProviderRequestError,
    get_api_key,
    parse_token_usage,
    post_json,
    redact_secret,
)

DEFAULT_NVIDIA_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_NVIDIA_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
DEFAULT_NVIDIA_MAX_TOKENS = 8192
DEFAULT_NVIDIA_REASONING_BUDGET = 2048
DEFAULT_NVIDIA_TEMPERATURE = 0.2
DEFAULT_NVIDIA_MAX_RETRIES = 2
DEFAULT_NVIDIA_RETRY_BACKOFF = 1.0


def _extract_nvidia_message_text(message: dict[str, Any]) -> tuple[str, str | None]:
    content = message.get("content")
    reasoning_raw = message.get("reasoning_content")
    reasoning_text = str(reasoning_raw) if reasoning_raw else None

    if isinstance(content, str):
        return content, reasoning_text
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts), reasoning_text
    if content is None:
        return "", reasoning_text
    return str(content), reasoning_text


class NvidiaExtractionAdapter(ExtractionAdapter):
    """Extraction adapter backed by NVIDIA's integrate.api.nvidia.com endpoint."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_NVIDIA_ENDPOINT,
        model_id: str = DEFAULT_NVIDIA_MODEL,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        temperature: float = DEFAULT_NVIDIA_TEMPERATURE,
        max_tokens: int = DEFAULT_NVIDIA_MAX_TOKENS,
        reasoning_budget: int | None = DEFAULT_NVIDIA_REASONING_BUDGET,
        max_retries: int = DEFAULT_NVIDIA_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_NVIDIA_RETRY_BACKOFF,
        http_sender: HttpJsonSender | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if reasoning_budget is not None and reasoning_budget < 0:
            raise ValueError("reasoning_budget must be >= 0 or None")
        self._endpoint = endpoint
        self._model_id = model_id
        self._explicit_api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._reasoning_budget = reasoning_budget
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._http_sender = http_sender

    def __repr__(self) -> str:
        return (
            f"NvidiaExtractionAdapter(model_id={self._model_id!r}, "
            f"endpoint={self._endpoint!r}, max_tokens={self._max_tokens}, "
            f"reasoning_budget={self._reasoning_budget}, temperature={self._temperature})"
        )

    @property
    def provider_name(self) -> str:
        return "nvidia"

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def retry_backoff_seconds(self) -> float:
        return self._retry_backoff_seconds

    def config_snapshot(self) -> dict[str, Any]:
        return {
            **super().config_snapshot(),
            "endpoint": self._endpoint,
            "max_tokens": self._max_tokens,
            "reasoning_budget": self._reasoning_budget,
            "temperature": self._temperature,
            "timeout_seconds": self._timeout_seconds,
        }

    def build_payload(self, request: ProviderExtractionRequest) -> dict[str, Any]:
        """Build the OpenAI-compatible multimodal image_url payload with reasoning_budget."""
        user_content: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": page.data_url},
            }
            for page in request.pages
        ]
        user_content.append({"type": "text", "text": request.user_prompt})

        payload: dict[str, Any] = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if self._reasoning_budget is not None:
            payload["reasoning_budget"] = self._reasoning_budget
        return payload

    def _resolve_api_key(self) -> str:
        if self._explicit_api_key is not None:
            key = self._explicit_api_key.strip()
            if not key:
                raise ProviderRequestError("Provided NVIDIA API key is empty.")
            return key
        return get_api_key("NVIDIA_API_KEY")

    def extract(self, request: ProviderExtractionRequest) -> ProviderRawResponse:
        if not request.pages:
            raise ProviderRequestError(
                f"No rendered pages provided for {request.file_name}"
            )

        secret_for_redaction: str | None = self._explicit_api_key
        payload = self.build_payload(request)
        effective_timeout = (
            self._timeout_seconds
            if request.timeout_seconds is None
            else max(0.001, min(self._timeout_seconds, float(request.timeout_seconds)))
        )
        t0 = time.perf_counter()

        try:
            if self._http_sender is not None:
                headers = (
                    {"Authorization": f"Bearer {self._explicit_api_key}"}
                    if self._explicit_api_key
                    else {}
                )
                response_json = self._http_sender(
                    self._endpoint, headers, payload, effective_timeout
                )
            else:
                api_key = self._resolve_api_key()
                secret_for_redaction = api_key
                headers = {"Authorization": f"Bearer {api_key}"}
                response_json = post_json(
                    self._endpoint,
                    headers,
                    payload,
                    effective_timeout,
                    secret_to_redact=api_key,
                )
        except ProviderRequestError:
            raise
        except Exception as exc:
            raise ProviderRequestError(
                redact_secret(str(exc), secret_for_redaction),
                is_transient=isinstance(exc, TimeoutError),
            ) from exc

        elapsed = time.perf_counter() - t0
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderRequestError(
                f"NVIDIA response for {request.file_name} missing non-empty 'choices' list"
            )
        choice0 = choices[0]
        message = choice0.get("message")
        if not isinstance(message, dict):
            raise ProviderRequestError(
                f"NVIDIA response for {request.file_name} missing 'choices[0].message'"
            )

        raw_finish = choice0.get("finish_reason")
        finish_reason = str(raw_finish) if raw_finish is not None else None
        raw_text, reasoning_text = _extract_nvidia_message_text(message)
        usage = parse_token_usage(response_json.get("usage"))

        return ProviderRawResponse(
            provider_name=self.provider_name,
            model_id=str(response_json.get("model") or self._model_id),
            raw_text=raw_text,
            elapsed_seconds=elapsed,
            token_usage=usage,
            reasoning_text=reasoning_text,
            finish_reason=finish_reason,
        )
