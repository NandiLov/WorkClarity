"""Provider adapters and factory helper for AI schedule extraction."""

from __future__ import annotations

from ai_extraction.providers.base import (
    ExtractionAdapter,
    HttpJsonSender,
    ProviderExtractionRequest,
    ProviderRawResponse,
    ProviderRequestError,
    RequestAttemptRecord,
    TokenUsage,
    get_api_key,
    parse_token_usage,
    redact_secret,
    sum_token_usage,
)
from ai_extraction.providers.gemini import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_RESPONSE_SCHEMA,
    GeminiExtractionAdapter,
)
from ai_extraction.providers.nvidia import (
    DEFAULT_NVIDIA_ENDPOINT,
    DEFAULT_NVIDIA_MAX_RETRIES,
    DEFAULT_NVIDIA_MAX_TOKENS,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REASONING_BUDGET,
    DEFAULT_NVIDIA_RETRY_BACKOFF,
    DEFAULT_NVIDIA_TEMPERATURE,
    NvidiaExtractionAdapter,
)


def create_adapter(
    provider: str,
    *,
    model_id: str | None = None,
    timeout_seconds: float = 120.0,
    max_tokens: int | None = None,
    reasoning_budget: int | None = DEFAULT_NVIDIA_REASONING_BUDGET,
    temperature: float = DEFAULT_NVIDIA_TEMPERATURE,
    max_retries: int = DEFAULT_NVIDIA_MAX_RETRIES,
    retry_backoff_seconds: float = DEFAULT_NVIDIA_RETRY_BACKOFF,
    http_sender: HttpJsonSender | None = None,
) -> ExtractionAdapter:
    """Instantiate a configured extraction adapter by provider name."""
    norm = provider.strip().lower()
    if norm == "nvidia":
        return NvidiaExtractionAdapter(
            model_id=model_id or DEFAULT_NVIDIA_MODEL,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens or DEFAULT_NVIDIA_MAX_TOKENS,
            reasoning_budget=reasoning_budget,
            temperature=temperature,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            http_sender=http_sender,
        )
    if norm == "gemini":
        return GeminiExtractionAdapter(
            model_id=model_id or DEFAULT_GEMINI_MODEL,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_tokens or DEFAULT_NVIDIA_MAX_TOKENS,
            temperature=temperature,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            http_sender=http_sender,
        )
    raise ValueError(f"Unsupported provider {provider!r}; expected 'nvidia' or 'gemini'")


__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "GEMINI_RESPONSE_SCHEMA",
    "DEFAULT_NVIDIA_ENDPOINT",
    "DEFAULT_NVIDIA_MAX_RETRIES",
    "DEFAULT_NVIDIA_MAX_TOKENS",
    "DEFAULT_NVIDIA_MODEL",
    "DEFAULT_NVIDIA_REASONING_BUDGET",
    "DEFAULT_NVIDIA_RETRY_BACKOFF",
    "DEFAULT_NVIDIA_TEMPERATURE",
    "ExtractionAdapter",
    "GeminiExtractionAdapter",
    "HttpJsonSender",
    "NvidiaExtractionAdapter",
    "ProviderExtractionRequest",
    "ProviderRawResponse",
    "ProviderRequestError",
    "RequestAttemptRecord",
    "TokenUsage",
    "create_adapter",
    "get_api_key",
    "parse_token_usage",
    "redact_secret",
    "sum_token_usage",
]
