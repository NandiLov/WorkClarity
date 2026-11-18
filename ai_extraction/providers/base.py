"""Provider-independent extraction adapter interface and shared telemetry/HTTP helpers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_extraction.pdf_utils import PreparedDocumentPage

TRANSIENT_HTTP_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


class ProviderRequestError(RuntimeError):
    """Raised when an AI provider request fails or returns an invalid envelope."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.is_transient = is_transient


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts reported by a provider API."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


def sum_token_usage(usages: list[TokenUsage] | tuple[TokenUsage, ...]) -> TokenUsage:
    """Aggregate token consumption across multiple request attempts."""
    return TokenUsage(
        prompt_tokens=sum(u.prompt_tokens for u in usages),
        completion_tokens=sum(u.completion_tokens for u in usages),
        reasoning_tokens=sum(u.reasoning_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        total_tokens=sum(u.total_tokens for u in usages),
    )


def parse_token_usage(usage_raw: Any) -> TokenUsage:
    """
    Normalise OpenAI/NVIDIA `usage` and Gemini `usageMetadata` consistently.

    Invariant: `completion_tokens == reasoning_tokens + output_tokens` unless provider reports a
    separate cached/tool token total in `total_tokens`.
    """
    if not isinstance(usage_raw, dict):
        return TokenUsage()

    is_gemini_metadata = any(
        k in usage_raw
        for k in (
            "promptTokenCount",
            "candidatesTokenCount",
            "thoughtsTokenCount",
            "totalTokenCount",
        )
    )
    if is_gemini_metadata:
        prompt_tokens = int(usage_raw.get("promptTokenCount") or 0)
        # Gemini `candidatesTokenCount` excludes `thoughtsTokenCount`.
        output_tokens = int(usage_raw.get("candidatesTokenCount") or 0)
        reasoning_tokens = int(usage_raw.get("thoughtsTokenCount") or 0)
        completion_tokens = output_tokens + reasoning_tokens
        total_tokens = int(
            usage_raw.get("totalTokenCount") or (prompt_tokens + completion_tokens)
        )
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    prompt_tokens = int(usage_raw.get("prompt_tokens") or 0)
    completion_tokens = int(usage_raw.get("completion_tokens") or 0)
    details = usage_raw.get("completion_tokens_details")
    details_dict = details if isinstance(details, dict) else {}
    reasoning_tokens = int(
        usage_raw.get("reasoning_tokens") or details_dict.get("reasoning_tokens") or 0
    )
    output_tokens = int(
        usage_raw.get("output_tokens") or max(0, completion_tokens - reasoning_tokens)
    )
    total_tokens = int(
        usage_raw.get("total_tokens") or (prompt_tokens + completion_tokens)
    )
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


@dataclass(frozen=True, slots=True)
class RequestAttemptRecord:
    """Per-attempt telemetry covering latency, tokens, finish_reason, and failure reason."""

    attempt_number: int
    elapsed_seconds: float
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None
    succeeded: bool = False
    failure_reason: str | None = None
    transient_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
            "token_usage": self.token_usage.to_dict(),
            "finish_reason": self.finish_reason,
            "succeeded": self.succeeded,
            "failure_reason": self.failure_reason,
            "transient_error": self.transient_error,
        }


@dataclass(frozen=True, slots=True)
class ProviderExtractionRequest:
    """Provider-agnostic request carrying rendered page images and prompts."""

    file_name: str
    pages: tuple[PreparedDocumentPage, ...]
    system_prompt: str
    user_prompt: str
    target_worker: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderRawResponse:
    """Provider response envelope preserved separately from normalised output."""

    provider_name: str
    model_id: str
    raw_text: str
    elapsed_seconds: float
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    reasoning_text: str | None = None
    finish_reason: str | None = None


HttpJsonSender = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def redact_secret(text: str, secret: str | None) -> str:
    """Scrub a credential string from any diagnostic text before exposing/storing it."""
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")


def get_api_key(
    env_var_name: str,
    *,
    env_file: str | Path | None = None,
) -> str:
    """Load an API key from the environment (or optional .env file) without logging it."""
    val = os.environ.get(env_var_name, "").strip()
    if val:
        return val

    candidate_paths: list[Path] = []
    if env_file is not None:
        candidate_paths.append(Path(env_file))
    else:
        candidate_paths.append(Path.cwd() / ".env")
        candidate_paths.append(Path(__file__).resolve().parents[2] / ".env")

    for path in candidate_paths:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key_part, raw_val = line.split("=", 1)
            if key_part.strip() == env_var_name:
                parsed = raw_val.strip().strip("'\"")
                if parsed:
                    return parsed

    raise ProviderRequestError(
        f"Missing required environment variable {env_var_name}. "
        f"Export {env_var_name} in your shell before running live extraction.",
        is_transient=False,
    )


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
    *,
    secret_to_redact: str | None = None,
) -> dict[str, Any]:
    """Send a JSON HTTP POST using stdlib urllib with safe error redaction."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_bytes = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            decoded = raw_bytes.decode(charset, errors="replace")
            return json.loads(decoded)
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            err_body = ""
        finally:
            try:
                exc.close()
            except Exception:
                pass
        msg = redact_secret(
            f"HTTP {exc.code} from {url}: {err_body or exc.reason}",
            secret_to_redact,
        )
        raise ProviderRequestError(
            msg,
            status_code=exc.code,
            is_transient=exc.code in TRANSIENT_HTTP_STATUS_CODES,
        ) from exc
    except urllib.error.URLError as exc:
        msg = redact_secret(f"Network error calling {url}: {exc.reason}", secret_to_redact)
        raise ProviderRequestError(msg, is_transient=True) from exc
    except TimeoutError as exc:
        msg = redact_secret(f"Timeout calling {url}: {exc}", secret_to_redact)
        raise ProviderRequestError(msg, is_transient=True) from exc
    except json.JSONDecodeError as exc:
        msg = redact_secret(f"Invalid JSON envelope returned by {url}: {exc}", secret_to_redact)
        raise ProviderRequestError(msg, is_transient=False) from exc
    except Exception as exc:
        msg = redact_secret(f"Unexpected error calling {url}: {exc}", secret_to_redact)
        raise ProviderRequestError(msg, is_transient=False) from exc


class ExtractionAdapter(ABC):
    """Contract implemented by all multimodal schedule extraction providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier for this provider (e.g., 'nvidia', 'gemini')."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Concrete model identifier used for requests and benchmark logging."""

    @property
    def max_retries(self) -> int:
        """Maximum additional retries for transient/truncated/malformed attempts."""
        return 2

    @property
    def retry_backoff_seconds(self) -> float:
        """Base exponential backoff interval for transient API errors."""
        return 1.0

    def config_snapshot(self) -> dict[str, Any]:
        """Return safe, secret-free adapter configuration parameters for benchmark logs."""
        return {
            "provider_name": self.provider_name,
            "model_id": self.model_id,
            "max_retries": self.max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
        }

    @abstractmethod
    def extract(self, request: ProviderExtractionRequest) -> ProviderRawResponse:
        """Send rendered document pages + prompt to the provider and return raw output."""
