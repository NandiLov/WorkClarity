"""Gemini multimodal extraction adapter adhering to the shared ExtractionAdapter interface."""

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

DEFAULT_GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Gemini OpenAPI-subset structured output schema requiring top-level {week_of, shifts}
GEMINI_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": ["week_of", "shifts"],
    "properties": {
        "week_of": {"type": "STRING", "nullable": True},
        "shifts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": [
                    "shift_date",
                    "start_time",
                    "end_time",
                    "break_minutes",
                    "employer_name",
                    "location",
                    "department",
                    "hourly_rate",
                    "currency",
                    "shift_status",
                    "confidence",
                    "uncertain_fields",
                    "source_page",
                    "source_row",
                ],
                "properties": {
                    "shift_date": {"type": "STRING", "nullable": True},
                    "start_time": {"type": "STRING", "nullable": True},
                    "end_time": {"type": "STRING", "nullable": True},
                    "break_minutes": {"type": "INTEGER", "nullable": True},
                    "employer_name": {"type": "STRING", "nullable": True},
                    "location": {"type": "STRING", "nullable": True},
                    "department": {"type": "STRING", "nullable": True},
                    "hourly_rate": {"type": "NUMBER", "nullable": True},
                    "currency": {"type": "STRING", "nullable": True},
                    "shift_status": {
                        "type": "STRING",
                        "enum": ["scheduled", "cancelled", "changed"],
                    },
                    "confidence": {
                        "type": "STRING",
                        "enum": ["high", "medium", "low"],
                    },
                    "uncertain_fields": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "source_page": {"type": "INTEGER", "nullable": True},
                    "source_row": {"type": "INTEGER", "nullable": True},
                    "worker_name": {"type": "STRING", "nullable": True},
                },
            },
        },
    },
}


class GeminiExtractionAdapter(ExtractionAdapter):
    """Future Gemini provider adapter sharing the benchmark & schema contract."""

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_GEMINI_MODEL,
        endpoint_template: str = DEFAULT_GEMINI_ENDPOINT_TEMPLATE,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        use_response_schema: bool = True,
        http_sender: HttpJsonSender | None = None,
    ) -> None:
        self._model_id = model_id
        self._endpoint_template = endpoint_template
        self._explicit_api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._use_response_schema = use_response_schema
        self._http_sender = http_sender

    def __repr__(self) -> str:
        return f"GeminiExtractionAdapter(model_id={self._model_id!r})"

    @property
    def provider_name(self) -> str:
        return "gemini"

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
            "max_output_tokens": self._max_output_tokens,
            "temperature": self._temperature,
            "timeout_seconds": self._timeout_seconds,
            "use_response_schema": self._use_response_schema,
        }

    def build_payload(self, request: ProviderExtractionRequest) -> dict[str, Any]:
        """Build a Gemini generateContent request payload using inline base64 pages."""
        parts: list[dict[str, Any]] = [
            {
                "inlineData": {
                    "mimeType": page.mime_type,
                    "data": page.base64_data,
                }
            }
            for page in request.pages
        ]
        parts.append({"text": request.user_prompt})

        generation_config: dict[str, Any] = {
            "temperature": self._temperature,
            "maxOutputTokens": self._max_output_tokens,
            "responseMimeType": "application/json",
        }
        if self._use_response_schema:
            generation_config["responseSchema"] = GEMINI_RESPONSE_SCHEMA

        return {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }

    def _resolve_api_key(self) -> str:
        if self._explicit_api_key is not None:
            key = self._explicit_api_key.strip()
            if not key:
                raise ProviderRequestError("Provided GEMINI API key is empty.")
            return key
        return get_api_key("GEMINI_API_KEY")

    def extract(self, request: ProviderExtractionRequest) -> ProviderRawResponse:
        if not request.pages:
            raise ProviderRequestError(
                f"No rendered pages provided for {request.file_name}"
            )

        endpoint = self._endpoint_template.format(model=self._model_id)
        payload = self.build_payload(request)
        secret_for_redaction = self._explicit_api_key
        t0 = time.perf_counter()

        try:
            if self._http_sender is not None:
                headers = (
                    {"x-goog-api-key": self._explicit_api_key}
                    if self._explicit_api_key
                    else {}
                )
                response_json = self._http_sender(
                    endpoint, headers, payload, self._timeout_seconds
                )
            else:
                api_key = self._resolve_api_key()
                secret_for_redaction = api_key
                response_json = post_json(
                    endpoint,
                    {"x-goog-api-key": api_key},
                    payload,
                    self._timeout_seconds,
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
        candidates = response_json.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise ProviderRequestError(
                f"Gemini response for {request.file_name} missing non-empty 'candidates' list"
            )

        cand0 = candidates[0]
        raw_finish = cand0.get("finishReason")
        finish_reason = str(raw_finish).lower() if raw_finish is not None else None
        if finish_reason == "max_tokens":
            finish_reason = "length"

        content = cand0.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        raw_text = "\n".join(
            part["text"]
            for part in (parts or [])
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
        usage = parse_token_usage(response_json.get("usageMetadata"))

        return ProviderRawResponse(
            provider_name=self.provider_name,
            model_id=self._model_id,
            raw_text=raw_text,
            elapsed_seconds=elapsed,
            token_usage=usage,
            finish_reason=finish_reason,
        )
