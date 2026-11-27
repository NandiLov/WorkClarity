"""Provider-independent AI schedule extraction orchestration with bounded retries and automatic failover.

Deadline & timeout model:
    Overall deadlines are cooperative rather than preemptive process kills. Document PDF rendering
    and optional image preprocessing run synchronously in-thread before network calls and are measured
    against `total_deadline_seconds`; per-attempt socket timeouts are clamped to remaining budget via
    stdlib `urllib.request.urlopen`, which cannot forcibly interrupt synchronous C/CPU preprocessing or
    DNS hangs mid-operation.

Data-processing policy notice:
    When `fallback_enabled=True`, schedules failing on the primary provider are dispatched to an
    independently configured secondary AI vendor (`fallback_provider`). Production deployments sending
    real worker schedule documents across providers must have an approved data-processing agreement
    (DPA) and privacy disclosure covering every enabled provider.
"""

from __future__ import annotations

import logging
import math
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ai_extraction.pdf_utils import (
    DEFAULT_PDF_DPI,
    PreparedDocumentPage,
    load_document_pages,
    load_document_pages_from_bytes,
)
from ai_extraction.prompt import SYSTEM_PROMPT, build_user_prompt
from ai_extraction.providers import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_NVIDIA_MAX_TOKENS,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REASONING_BUDGET,
    DEFAULT_NVIDIA_TEMPERATURE,
    ExtractionAdapter,
    ProviderExtractionRequest,
    ProviderRawResponse,
    ProviderRequestError,
    RequestAttemptRecord,
    TokenUsage,
    create_adapter,
    redact_secret,
    sum_token_usage,
)
from ai_extraction.schema import (
    TRUNCATION_FINISH_REASONS,
    DocumentExtractionResult,
    ExtractedShiftRecord,
    parse_and_validate_model_json,
)

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"gemini", "nvidia"})
DEFAULT_PRIMARY_PROVIDER = "gemini"
DEFAULT_PRIMARY_MODEL = DEFAULT_GEMINI_MODEL
DEFAULT_FALLBACK_PROVIDER = "nvidia"
DEFAULT_FALLBACK_MODEL = DEFAULT_NVIDIA_MODEL
DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS = 120.0
DEFAULT_TOTAL_DEADLINE_SECONDS = 240.0

_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV = frozenset({"0", "false", "no", "off"})

FailureCategory = Literal[
    "rate_limit_429",
    "transient_http_5xx",
    "timeout_or_connection_error",
    "authentication_error",
    "missing_credentials",
    "configuration_or_client_error",
    "malformed_or_empty_response",
    "partially_invalid_response",
    "suspicious_empty_shifts",
    "truncated_response",
    "deadline_exhausted",
    "document_preparation_error",
    "unexpected_provider_error",
]


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    norm = raw.strip().lower()
    if norm in _TRUTHY_ENV:
        return True
    if norm in _FALSY_ENV:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {raw!r}")


def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _parse_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw.strip())


def _default_model_for_provider(provider: str | None) -> str | None:
    if not provider:
        return None
    norm = provider.strip().lower()
    if norm == "gemini":
        return DEFAULT_GEMINI_MODEL
    if norm == "nvidia":
        return DEFAULT_NVIDIA_MODEL
    return None


@dataclass(frozen=True, slots=True)
class ExtractionServiceConfig:
    """Secret-free configuration for primary/fallback AI schedule extraction."""

    primary_provider: str = DEFAULT_PRIMARY_PROVIDER
    primary_model_id: str | None = None
    fallback_enabled: bool = False
    fallback_provider: str | None = DEFAULT_FALLBACK_PROVIDER
    fallback_model_id: str | None = None
    primary_max_retries: int = 2
    fallback_max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    per_attempt_timeout_seconds: float = DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS
    total_deadline_seconds: float = DEFAULT_TOTAL_DEADLINE_SECONDS
    max_tokens: int = DEFAULT_NVIDIA_MAX_TOKENS
    reasoning_budget: int | None = DEFAULT_NVIDIA_REASONING_BUDGET
    temperature: float = DEFAULT_NVIDIA_TEMPERATURE
    failover_on_auth_or_config_error: bool = True
    failover_on_partial_extraction: bool = True
    allow_single_provider_empty_schedule: bool = False
    pdf_dpi: int = DEFAULT_PDF_DPI
    preprocess_images: bool = False
    deskew: bool = True
    perspective_correct: bool = False
    enhance_contrast: bool = False

    def __post_init__(self) -> None:
        if not self.primary_provider or not self.primary_provider.strip():
            raise ValueError("primary_provider must be a non-empty provider name")
        primary_norm = self.primary_provider.strip().lower()
        if primary_norm not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported primary_provider {self.primary_provider!r}; "
                f"expected one of {sorted(SUPPORTED_PROVIDERS)}"
            )

        if self.fallback_provider is not None:
            fb_norm = self.fallback_provider.strip().lower()
            if fb_norm not in ("", "none", "off", "disabled") and fb_norm not in SUPPORTED_PROVIDERS:
                raise ValueError(
                    f"Unsupported fallback_provider {self.fallback_provider!r}; "
                    f"expected one of {sorted(SUPPORTED_PROVIDERS)} or 'none'"
                )

        if self.primary_max_retries < 0:
            raise ValueError("primary_max_retries must be >= 0")
        if self.fallback_max_retries < 0:
            raise ValueError("fallback_max_retries must be >= 0")
        if not math.isfinite(self.retry_backoff_seconds) or self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be finite and >= 0")
        if (
            not math.isfinite(self.per_attempt_timeout_seconds)
            or self.per_attempt_timeout_seconds <= 0
        ):
            raise ValueError("per_attempt_timeout_seconds must be finite and > 0")
        if (
            not math.isfinite(self.total_deadline_seconds)
            or self.total_deadline_seconds < 0
        ):
            raise ValueError("total_deadline_seconds must be finite and >= 0")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be > 0")
        if self.reasoning_budget is not None and self.reasoning_budget < 0:
            raise ValueError("reasoning_budget must be >= 0 or None")
        if (
            not math.isfinite(self.temperature)
            or self.temperature < 0.0
            or self.temperature > 2.0
        ):
            raise ValueError("temperature must be finite and between 0.0 and 2.0")
        if self.pdf_dpi < 72 or self.pdf_dpi > 600:
            raise ValueError("pdf_dpi must be between 72 and 600")

        fb_provider = self.resolved_fallback_provider
        if fb_provider is not None and (
            (self.resolved_primary_provider, self.resolved_primary_model_id)
            == (fb_provider, self.resolved_fallback_model_id)
        ):
            raise ValueError(
                "Primary and fallback providers/models must be distinct when fallback is enabled; "
                "set fallback_enabled=False or configure a different fallback provider/model."
            )

    @property
    def resolved_primary_provider(self) -> str:
        return self.primary_provider.strip().lower()

    @property
    def resolved_primary_model_id(self) -> str | None:
        if self.primary_model_id and self.primary_model_id.strip():
            return self.primary_model_id.strip()
        return _default_model_for_provider(self.resolved_primary_provider)

    @property
    def resolved_fallback_provider(self) -> str | None:
        if not self.fallback_enabled:
            return None
        if not self.fallback_provider:
            return None
        norm = self.fallback_provider.strip().lower()
        if norm in ("", "none", "off", "disabled"):
            return None
        return norm

    @property
    def resolved_fallback_model_id(self) -> str | None:
        provider = self.resolved_fallback_provider
        if not provider:
            return None
        if self.fallback_model_id and self.fallback_model_id.strip():
            return self.fallback_model_id.strip()
        return _default_model_for_provider(provider)

    @classmethod
    def from_env(cls) -> ExtractionServiceConfig:
        """Load orchestration configuration from environment variables."""
        primary = (
            os.environ.get("AI_EXTRACTION_PRIMARY_PROVIDER", DEFAULT_PRIMARY_PROVIDER)
            .strip()
            .lower()
            or DEFAULT_PRIMARY_PROVIDER
        )
        raw_fb = os.environ.get("AI_EXTRACTION_FALLBACK_PROVIDER")
        if raw_fb is not None:
            fallback_provider = raw_fb.strip()
        elif primary == "nvidia":
            fallback_provider = "gemini"
        else:
            fallback_provider = DEFAULT_FALLBACK_PROVIDER

        return cls(
            primary_provider=primary,
            primary_model_id=os.environ.get("AI_EXTRACTION_PRIMARY_MODEL") or None,
            fallback_enabled=_parse_bool_env("AI_EXTRACTION_FALLBACK_ENABLED", False),
            fallback_provider=fallback_provider,
            fallback_model_id=os.environ.get("AI_EXTRACTION_FALLBACK_MODEL") or None,
            primary_max_retries=_parse_int_env("AI_EXTRACTION_PRIMARY_MAX_RETRIES", 2),
            fallback_max_retries=_parse_int_env("AI_EXTRACTION_FALLBACK_MAX_RETRIES", 2),
            retry_backoff_seconds=_parse_float_env(
                "AI_EXTRACTION_RETRY_BACKOFF_SECONDS", 1.0
            ),
            per_attempt_timeout_seconds=_parse_float_env(
                "AI_EXTRACTION_TIMEOUT_SECONDS", DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS
            ),
            total_deadline_seconds=_parse_float_env(
                "AI_EXTRACTION_TOTAL_DEADLINE_SECONDS", DEFAULT_TOTAL_DEADLINE_SECONDS
            ),
            allow_single_provider_empty_schedule=_parse_bool_env(
                "AI_EXTRACTION_ALLOW_SINGLE_PROVIDER_EMPTY_SCHEDULE", False
            ),
            preprocess_images=_parse_bool_env("AI_EXTRACTION_PREPROCESS_IMAGES", False),
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Return safe, secret-free configuration metadata for telemetry and responses."""
        return {
            "primary_provider": self.resolved_primary_provider,
            "primary_model_id": self.resolved_primary_model_id,
            "fallback_enabled": self.resolved_fallback_provider is not None,
            "fallback_provider": self.resolved_fallback_provider,
            "fallback_model_id": self.resolved_fallback_model_id,
            "primary_max_retries": self.primary_max_retries,
            "fallback_max_retries": self.fallback_max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "per_attempt_timeout_seconds": self.per_attempt_timeout_seconds,
            "total_deadline_seconds": self.total_deadline_seconds,
            "max_tokens": self.max_tokens,
            "reasoning_budget": self.reasoning_budget,
            "temperature": self.temperature,
            "failover_on_auth_or_config_error": self.failover_on_auth_or_config_error,
            "failover_on_partial_extraction": self.failover_on_partial_extraction,
            "allow_single_provider_empty_schedule": self.allow_single_provider_empty_schedule,
            "pdf_dpi": self.pdf_dpi,
            "preprocess_images": self.preprocess_images,
        }


def classify_provider_exception(exc: Exception) -> tuple[FailureCategory, bool]:
    """
    Classify provider call exceptions into (failure_category, is_retryable_on_same_provider).

    Authentication, missing-key, and non-transient configuration errors MUST NOT be
    repeatedly retried against the failing provider.
    """
    if isinstance(exc, ProviderRequestError):
        msg_low = str(exc).lower()
        if (
            "missing required environment variable" in msg_low
            or "api key is empty" in msg_low
            or "missing api key" in msg_low
        ):
            return "missing_credentials", False
        if (
            exc.status_code in (401, 403)
            or "unauthorized" in msg_low
            or "invalid api key" in msg_low
            or "permission_denied" in msg_low
            or "authentication" in msg_low
        ):
            return "authentication_error", False
        if exc.status_code == 429:
            return "rate_limit_429", True
        if exc.status_code in (408, 500, 502, 503, 504):
            return "transient_http_5xx", True
        if exc.is_transient:
            return "timeout_or_connection_error", True
        return "configuration_or_client_error", False

    if isinstance(exc, TimeoutError):
        return "timeout_or_connection_error", True
    return "unexpected_provider_error", False


def classify_parsed_output(
    raw_resp: ProviderRawResponse,
    parsed_doc: DocumentExtractionResult,
    *,
    reject_empty_shifts: bool = False,
) -> tuple[FailureCategory | None, bool, str | None]:
    """
    Classify parsed provider output into (failure_category, needs_retry, failure_reason).

    Valid extractions that contain legitimately missing (`null`) financial fields have
    `json_validation_failure == False`, `incomplete_extraction == False`, and `len(shifts) > 0`,
    so they return `(None, False, None)` and never trigger retry or failover.
    """
    is_empty = not raw_resp.raw_text.strip()
    if is_empty:
        suffix = (
            f" (finish_reason={raw_resp.finish_reason})"
            if raw_resp.finish_reason
            else ""
        )
        return (
            "malformed_or_empty_response",
            True,
            f"Empty model response content{suffix}",
        )

    is_truncated = bool(
        raw_resp.finish_reason in TRUNCATION_FINISH_REASONS
        or parsed_doc.partial_recovery_triggered
    )
    if is_truncated:
        if parsed_doc.shifts:
            return (
                "truncated_response",
                True,
                (
                    f"Partially recovered truncated response "
                    f"({len(parsed_doc.shifts)} complete shift(s) recovered; "
                    f"finish_reason={raw_resp.finish_reason})"
                ),
            )
        err_detail = "; ".join(parsed_doc.json_validation_errors)
        return (
            "truncated_response",
            True,
            f"Response truncated (finish_reason={raw_resp.finish_reason})"
            + (f": {err_detail}" if err_detail else ""),
        )

    if parsed_doc.invalid_or_empty_records > 0 and parsed_doc.shifts:
        return (
            "partially_invalid_response",
            True,
            (
                f"Response contained {len(parsed_doc.shifts)} valid shift(s) and "
                f"{parsed_doc.invalid_or_empty_records} rejected invalid/empty record(s): "
                + "; ".join(parsed_doc.json_validation_errors)
            ),
        )

    if parsed_doc.json_validation_failure:
        return (
            "malformed_or_empty_response",
            True,
            "; ".join(parsed_doc.json_validation_errors),
        )

    if reject_empty_shifts and len(parsed_doc.shifts) == 0:
        return (
            "suspicious_empty_shifts",
            True,
            "Provider returned zero extracted shifts (shifts=[]); retrying/verifying before accepting an empty schedule.",
        )

    return None, False, None


def _has_positive_empty_schedule_context(doc: DocumentExtractionResult | None) -> bool:
    """Return True only when 0 shifts came cleanly alongside schedule context (header or filtered colleagues)."""
    return bool(
        doc is not None
        and not doc.json_validation_failure
        and not doc.incomplete_extraction
        and doc.invalid_or_empty_records == 0
        and len(doc.shifts) == 0
        and (doc.week_of is not None or doc.filtered_other_worker_shifts > 0)
    )


def _scrub_adapter_secret(adapter: ExtractionAdapter, text: str) -> str:
    """Scrub only this adapter's own explicit or configured environment key (no cross-provider access)."""
    cleaned = text
    explicit = getattr(adapter, "_explicit_api_key", None)
    if isinstance(explicit, str) and explicit:
        cleaned = redact_secret(cleaned, explicit)
    env_name = {
        "gemini": "GEMINI_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
    }.get(getattr(adapter, "provider_name", "").strip().lower())
    if env_name:
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            cleaned = redact_secret(cleaned, env_val)
    return cleaned


@dataclass(slots=True)
class ProviderAttemptOutcome:
    """Result of executing bounded retries against a single extraction adapter."""

    provider_name: str
    model_id: str
    succeeded: bool
    raw_response: ProviderRawResponse | None
    parsed_result: DocumentExtractionResult | None
    token_usage: TokenUsage
    elapsed_seconds: float
    attempt_records: list[RequestAttemptRecord]
    final_request_failure: bool
    final_request_error: str | None
    failure_category: FailureCategory | None
    failure_reason: str | None
    deadline_exhausted: bool = False


def run_provider_attempts(
    adapter: ExtractionAdapter,
    request: ProviderExtractionRequest,
    *,
    max_retries: int | None = None,
    backoff_seconds: float | None = None,
    per_attempt_timeout_seconds: float | None = None,
    deadline_epoch: float | None = None,
    reject_empty_shifts: bool = False,
    clock_fn: Callable[[], float] = time.perf_counter,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ProviderAttemptOutcome:
    """
    Execute up to `(1 + max_retries)` attempts against one adapter while enforcing
    exponential backoff, non-retryable auth/config short-circuiting, and cooperative deadlines.
    """
    allowed_retries = adapter.max_retries if max_retries is None else max_retries
    if allowed_retries < 0:
        raise ValueError("max_retries must be >= 0")
    base_backoff = (
        adapter.retry_backoff_seconds if backoff_seconds is None else backoff_seconds
    )

    attempt_records: list[RequestAttemptRecord] = []
    usage_history: list[TokenUsage] = []
    best_raw: ProviderRawResponse | None = None
    best_parsed: DocumentExtractionResult | None = None
    final_request_failure = False
    final_request_error: str | None = None
    last_failure_category: FailureCategory | None = None
    last_failure_reason: str | None = None
    succeeded = False
    deadline_exhausted = False

    max_attempts = 1 + allowed_retries
    for attempt_idx in range(max_attempts):
        attempt_num = attempt_idx + 1
        remaining_deadline: float | None = None
        if deadline_epoch is not None:
            remaining_deadline = deadline_epoch - clock_fn()
            if remaining_deadline <= 0:
                deadline_exhausted = True
                if last_failure_reason is None:
                    last_failure_category = "deadline_exhausted"
                    last_failure_reason = (
                        f"Overall processing deadline exhausted before {adapter.provider_name} attempt {attempt_num}."
                    )
                    if best_raw is None:
                        final_request_failure = True
                        final_request_error = last_failure_reason
                break

        attempt_timeout = per_attempt_timeout_seconds
        if attempt_timeout is None:
            attempt_timeout = request.timeout_seconds
        if remaining_deadline is not None:
            attempt_timeout = (
                remaining_deadline
                if attempt_timeout is None
                else min(float(attempt_timeout), remaining_deadline)
            )

        attempt_request = ProviderExtractionRequest(
            file_name=request.file_name,
            pages=request.pages,
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            target_worker=request.target_worker,
            timeout_seconds=attempt_timeout,
        )

        t0 = clock_fn()
        try:
            raw_resp = adapter.extract(attempt_request)
        except Exception as exc:
            attempt_elapsed = max(0.0, clock_fn() - t0)
            category, is_retryable = classify_provider_exception(exc)
            raw_msg = (
                str(exc)
                if isinstance(exc, ProviderRequestError)
                else f"Unexpected provider failure: {exc}"
            )
            safe_msg = _scrub_adapter_secret(adapter, raw_msg)
            attempt_records.append(
                RequestAttemptRecord(
                    attempt_number=attempt_num,
                    elapsed_seconds=attempt_elapsed,
                    token_usage=TokenUsage(),
                    finish_reason=None,
                    succeeded=False,
                    failure_reason=safe_msg,
                    transient_error=is_retryable,
                    provider_name=adapter.provider_name,
                    model_id=adapter.model_id,
                    failure_category=category,
                )
            )
            usage_history.append(TokenUsage())
            final_request_failure = True
            final_request_error = safe_msg
            last_failure_category = category
            last_failure_reason = safe_msg

            if not is_retryable:
                break
            if attempt_num < max_attempts:
                delay = base_backoff * (2**attempt_idx)
                if deadline_epoch is not None:
                    rem_after = deadline_epoch - clock_fn()
                    if rem_after <= 0 or delay >= rem_after:
                        deadline_exhausted = True
                        break
                if delay > 0:
                    sleep_fn(delay)
                if deadline_epoch is not None and clock_fn() >= deadline_epoch:
                    deadline_exhausted = True
                    break
                continue
            if deadline_epoch is not None and clock_fn() >= deadline_epoch:
                deadline_exhausted = True
            break

        usage_history.append(raw_resp.token_usage)
        parsed_doc = parse_and_validate_model_json(
            raw_resp.raw_text,
            file_name=request.file_name,
            model_id=raw_resp.model_id,
            target_worker=request.target_worker,
            finish_reason=raw_resp.finish_reason,
            allow_partial_recovery=True,
        )
        category, needs_retry, attempt_failure_reason = classify_parsed_output(
            raw_resp,
            parsed_doc,
            reject_empty_shifts=reject_empty_shifts,
        )
        attempt_records.append(
            RequestAttemptRecord(
                attempt_number=attempt_num,
                elapsed_seconds=raw_resp.elapsed_seconds,
                token_usage=raw_resp.token_usage,
                finish_reason=raw_resp.finish_reason,
                succeeded=not needs_retry,
                failure_reason=attempt_failure_reason,
                transient_error=False,
                provider_name=raw_resp.provider_name or adapter.provider_name,
                model_id=raw_resp.model_id or adapter.model_id,
                failure_category=category,
            )
        )

        final_request_failure = False
        final_request_error = None

        if not needs_retry:
            best_raw = raw_resp
            best_parsed = parsed_doc
            last_failure_category = None
            last_failure_reason = None
            succeeded = True
            break

        last_failure_category = category
        last_failure_reason = attempt_failure_reason
        has_empty_ctx = int(_has_positive_empty_schedule_context(parsed_doc))
        cand_rank = (
            len(parsed_doc.shifts),
            has_empty_ctx,
            -parsed_doc.invalid_or_empty_records,
        )
        best_rank = (
            (
                len(best_parsed.shifts),
                int(_has_positive_empty_schedule_context(best_parsed)),
                -best_parsed.invalid_or_empty_records,
            )
            if best_parsed is not None
            else (-1, -1, -(10**9))
        )
        if best_parsed is None or cand_rank > best_rank:
            best_raw = raw_resp
            best_parsed = parsed_doc

        if attempt_num < max_attempts:
            delay = base_backoff * (2**attempt_idx)
            if deadline_epoch is not None:
                rem_after = deadline_epoch - clock_fn()
                if rem_after <= 0 or delay >= rem_after:
                    deadline_exhausted = True
                    break
            if delay > 0:
                sleep_fn(delay)
            if deadline_epoch is not None and clock_fn() >= deadline_epoch:
                deadline_exhausted = True
                break
        elif deadline_epoch is not None and clock_fn() >= deadline_epoch:
            deadline_exhausted = True

    total_usage = sum_token_usage(usage_history)
    total_elapsed = sum(rec.elapsed_seconds for rec in attempt_records)

    return ProviderAttemptOutcome(
        provider_name=adapter.provider_name,
        model_id=best_parsed.model_id if best_parsed else adapter.model_id,
        succeeded=succeeded,
        raw_response=best_raw,
        parsed_result=best_parsed,
        token_usage=total_usage,
        elapsed_seconds=total_elapsed,
        attempt_records=attempt_records,
        final_request_failure=final_request_failure,
        final_request_error=final_request_error,
        failure_category=last_failure_category,
        failure_reason=last_failure_reason,
        deadline_exhausted=deadline_exhausted,
    )


@dataclass(slots=True)
class OrchestratedExtractionResult:
    """Traceable, safety-preserving result returned by ExtractionOrchestrator."""

    file_name: str
    target_worker: str | None
    page_count: int
    extraction_status: Literal["complete", "partial", "failed"]
    succeeded: bool
    is_complete: bool
    is_partial: bool
    is_failed: bool
    is_empty_schedule: bool
    manual_entry_required: bool
    manual_entry_reason: str | None
    active_provider: str | None
    active_model_id: str | None
    primary_provider: str
    primary_model_id: str | None
    fallback_provider: str | None
    fallback_model_id: str | None
    fallback_triggered: bool
    fallback_trigger_category: FailureCategory | None
    fallback_trigger_reason: str | None
    primary_failure_category: FailureCategory | None
    primary_failure_reason: str | None
    fallback_failure_category: FailureCategory | None
    fallback_failure_reason: str | None
    deadline_exhausted: bool
    processing_time_seconds: float
    token_usage: TokenUsage
    primary_token_usage: TokenUsage
    fallback_token_usage: TokenUsage
    request_attempts: int
    attempt_history: list[dict[str, Any]]
    document_result: DocumentExtractionResult | None
    shifts: list[ExtractedShiftRecord]
    preprocessing_time_seconds: float = 0.0
    raw_response: str = ""
    reasoning_text: str | None = None
    preprocessing_applied: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    config_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_log_summary(self) -> dict[str, Any]:
        """
        Return strictly non-sensitive operational telemetry suitable for server logs.

        Excludes raw_response, reasoning_text, shift field contents, rejected_records,
        local directory paths, API keys, and raw HTTP error bodies.
        """
        doc = self.document_result
        return {
            "file_name": self.file_name,
            "page_count": self.page_count,
            "extraction_status": self.extraction_status,
            "succeeded": self.succeeded,
            "is_complete": self.is_complete,
            "is_partial": self.is_partial,
            "is_failed": self.is_failed,
            "is_empty_schedule": self.is_empty_schedule,
            "manual_entry_required": self.manual_entry_required,
            "active_provider": self.active_provider,
            "active_model_id": self.active_model_id,
            "primary_provider": self.primary_provider,
            "primary_model_id": self.primary_model_id,
            "fallback_provider": self.fallback_provider,
            "fallback_model_id": self.fallback_model_id,
            "fallback_triggered": self.fallback_triggered,
            "fallback_trigger_category": self.fallback_trigger_category,
            "primary_failure_category": self.primary_failure_category,
            "fallback_failure_category": self.fallback_failure_category,
            "deadline_exhausted": self.deadline_exhausted,
            "preprocessing_time_seconds": round(self.preprocessing_time_seconds, 4),
            "processing_time_seconds": round(self.processing_time_seconds, 4),
            "token_usage": self.token_usage.to_dict(),
            "request_attempts": self.request_attempts,
            "extracted_shift_count": len(self.shifts),
            "conflicting_duplicate_count": (
                doc.conflicting_duplicate_count if doc is not None else 0
            ),
            "deduplicated_shifts": doc.deduplicated_shifts if doc is not None else 0,
            "invalid_or_empty_records": (
                doc.invalid_or_empty_records if doc is not None else 0
            ),
        }

    def to_public_summary(self) -> dict[str, Any]:
        """
        Return safe telemetry suitable for structured API metadata.

        Deliberately excludes API keys, provider reasoning_text, raw document images,
        and raw unredacted prompt payloads.
        """
        return {
            **self.to_log_summary(),
            "manual_entry_reason": self.manual_entry_reason,
            "fallback_trigger_reason": self.fallback_trigger_reason,
            "primary_failure_reason": self.primary_failure_reason,
            "fallback_failure_reason": self.fallback_failure_reason,
            "primary_token_usage": self.primary_token_usage.to_dict(),
            "fallback_token_usage": self.fallback_token_usage.to_dict(),
            "attempt_history": list(self.attempt_history),
        }

    def to_payload_dict(self) -> dict[str, Any]:
        """Full structured extraction response payload for downstream services (e.g., FastAPI)."""
        return {
            **self.to_public_summary(),
            "shifts": [s.model_dump() for s in self.shifts],
            "conflict_groups": (
                list(self.document_result.conflict_groups)
                if self.document_result is not None
                else []
            ),
            "rejected_records": (
                list(self.document_result.rejected_records)
                if self.document_result is not None
                else []
            ),
            "preprocessing_applied": [list(steps) for steps in self.preprocessing_applied],
            "config": dict(self.config_snapshot),
        }

    def to_backend_calculation_payload(
        self,
        *,
        worker_id: str = "W001",
        simulate_individual_confirmation: bool = False,
    ) -> dict[str, Any]:
        """
        Format extracted shifts for backend/app/services/shift_calculations.calculate_shifts.

        As-extracted shifts ALWAYS stay in `needs_review`; when simulating confirmation,
        unresolved conflict-group members remain blocked in `needs_review`.
        """
        shift_dicts: list[dict[str, Any]] = []
        for idx, rec in enumerate(self.shifts, start=1):
            eff = rec.effective_values()
            status = (
                rec.apply_worker_correction(
                    {}, confirm_individually=True
                ).confirmation_status
                if simulate_individual_confirmation
                else rec.confirmation_status
            )
            shift_dicts.append(
                {
                    "shift_id": f"{self.file_name}#{idx}",
                    "shift_date": eff.shift_date,
                    "start_time": eff.start_time,
                    "end_time": eff.end_time,
                    "break_minutes": eff.break_minutes,
                    "employer_name": eff.employer_name,
                    "location": eff.location,
                    "hourly_rate": eff.hourly_rate,
                    "currency": eff.currency,
                    "shift_status": eff.shift_status,
                    "confirmation_status": status,
                }
            )
        return {"worker_id": worker_id, "shifts": shift_dicts}


class ExtractionOrchestrator:
    """
    Reusable provider-independent extraction orchestrator supporting primary + fallback
    providers, bounded retries, total deadline budgets, and worker-safety invariants.
    """

    def __init__(
        self,
        config: ExtractionServiceConfig | None = None,
        *,
        primary_adapter: ExtractionAdapter | None = None,
        fallback_adapter: ExtractionAdapter | None = None,
        clock_fn: Callable[[], float] = time.perf_counter,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config or ExtractionServiceConfig()
        self._clock_fn = clock_fn
        self._sleep_fn = sleep_fn

        if primary_adapter is not None:
            self._primary_adapter = primary_adapter
        else:
            self._primary_adapter = create_adapter(
                self._config.resolved_primary_provider,
                model_id=self._config.resolved_primary_model_id,
                timeout_seconds=self._config.per_attempt_timeout_seconds,
                max_tokens=self._config.max_tokens,
                reasoning_budget=self._config.reasoning_budget,
                temperature=self._config.temperature,
                max_retries=self._config.primary_max_retries,
                retry_backoff_seconds=self._config.retry_backoff_seconds,
            )

        if fallback_adapter is not None:
            self._fallback_adapter: ExtractionAdapter | None = (
                fallback_adapter if self._config.fallback_enabled else None
            )
        elif self._config.resolved_fallback_provider is not None:
            self._fallback_adapter = create_adapter(
                self._config.resolved_fallback_provider,
                model_id=self._config.resolved_fallback_model_id,
                timeout_seconds=self._config.per_attempt_timeout_seconds,
                max_tokens=self._config.max_tokens,
                reasoning_budget=self._config.reasoning_budget,
                temperature=self._config.temperature,
                max_retries=self._config.fallback_max_retries,
                retry_backoff_seconds=self._config.retry_backoff_seconds,
            )
        else:
            self._fallback_adapter = None

        if self._fallback_adapter is not None and (
            self._fallback_adapter is self._primary_adapter
            or (
                self._fallback_adapter.provider_name,
                self._fallback_adapter.model_id,
            )
            == (
                self._primary_adapter.provider_name,
                self._primary_adapter.model_id,
            )
        ):
            raise ValueError(
                "Primary and fallback adapters must use distinct provider/model targets "
                "when fallback is enabled."
            )

    @property
    def config(self) -> ExtractionServiceConfig:
        return self._config

    @property
    def primary_adapter(self) -> ExtractionAdapter:
        return self._primary_adapter

    @property
    def fallback_adapter(self) -> ExtractionAdapter | None:
        return self._fallback_adapter

    def extract_prepared_pages(
        self,
        pages: Sequence[PreparedDocumentPage],
        *,
        file_name: str,
        target_worker: str | None = None,
        start_epoch: float | None = None,
    ) -> OrchestratedExtractionResult:
        """Run schedule extraction over pre-rendered document pages with failover."""
        cfg = self._config
        t_start = self._clock_fn() if start_epoch is None else float(start_epoch)
        prep_elapsed = max(0.0, self._clock_fn() - t_start)
        deadline_epoch = (
            t_start + cfg.total_deadline_seconds
            if cfg.total_deadline_seconds > 0
            else None
        )

        primary_name = self._primary_adapter.provider_name
        primary_model = self._primary_adapter.model_id
        fallback_name = (
            self._fallback_adapter.provider_name
            if self._fallback_adapter is not None
            else cfg.resolved_fallback_provider
        )
        fallback_model = (
            self._fallback_adapter.model_id
            if self._fallback_adapter is not None
            else cfg.resolved_fallback_model_id
        )
        page_steps = tuple(p.preprocessing_applied for p in pages)

        if not pages:
            msg = f"No prepared pages available for {file_name}"
            res = self._build_prep_failure_result(
                file_name=file_name,
                target_worker=target_worker,
                error_msg=msg,
                preprocessing_time_seconds=prep_elapsed,
                processing_time_seconds=prep_elapsed,
                preprocessing_applied=page_steps,
            )
            logger.warning("AI extraction failed: %s", res.to_log_summary())
            return res

        if deadline_epoch is not None and self._clock_fn() >= deadline_epoch:
            msg = (
                f"Overall processing deadline exhausted during document preparation "
                f"({prep_elapsed:.2f}s >= {cfg.total_deadline_seconds:.2f}s)."
            )
            res = OrchestratedExtractionResult(
                file_name=file_name,
                target_worker=target_worker,
                page_count=len(pages),
                extraction_status="failed",
                succeeded=False,
                is_complete=False,
                is_partial=False,
                is_failed=True,
                is_empty_schedule=False,
                manual_entry_required=True,
                manual_entry_reason=msg,
                active_provider=None,
                active_model_id=None,
                primary_provider=primary_name,
                primary_model_id=primary_model,
                fallback_provider=fallback_name,
                fallback_model_id=fallback_model,
                fallback_triggered=False,
                fallback_trigger_category=None,
                fallback_trigger_reason=None,
                primary_failure_category="deadline_exhausted",
                primary_failure_reason=msg,
                fallback_failure_category=None,
                fallback_failure_reason=None,
                deadline_exhausted=True,
                preprocessing_time_seconds=prep_elapsed,
                processing_time_seconds=prep_elapsed,
                token_usage=TokenUsage(),
                primary_token_usage=TokenUsage(),
                fallback_token_usage=TokenUsage(),
                request_attempts=0,
                attempt_history=[],
                document_result=None,
                shifts=[],
                preprocessing_applied=page_steps,
                config_snapshot=cfg.to_public_dict(),
            )
            logger.warning("AI extraction aborted at deadline: %s", res.to_log_summary())
            return res

        request = ProviderExtractionRequest(
            file_name=file_name,
            pages=tuple(pages),
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(
                target_worker=target_worker,
                page_count=len(pages),
            ),
            target_worker=target_worker,
            timeout_seconds=cfg.per_attempt_timeout_seconds,
        )

        primary_run = run_provider_attempts(
            self._primary_adapter,
            request,
            max_retries=cfg.primary_max_retries,
            backoff_seconds=cfg.retry_backoff_seconds,
            per_attempt_timeout_seconds=cfg.per_attempt_timeout_seconds,
            deadline_epoch=deadline_epoch,
            reject_empty_shifts=True,
            clock_fn=self._clock_fn,
            sleep_fn=self._sleep_fn,
        )

        combined_history = [rec.to_dict() for rec in primary_run.attempt_records]

        if primary_run.succeeded and primary_run.parsed_result is not None:
            doc = primary_run.parsed_result
            raw_text = (
                primary_run.raw_response.raw_text
                if primary_run.raw_response is not None
                else ""
            )
            reasoning_text = (
                primary_run.raw_response.reasoning_text
                if primary_run.raw_response is not None
                else None
            )
            res = OrchestratedExtractionResult(
                file_name=file_name,
                target_worker=target_worker,
                page_count=len(pages),
                extraction_status="complete",
                succeeded=True,
                is_complete=True,
                is_partial=False,
                is_failed=False,
                is_empty_schedule=False,
                manual_entry_required=False,
                manual_entry_reason=None,
                active_provider=primary_name,
                active_model_id=doc.model_id,
                primary_provider=primary_name,
                primary_model_id=primary_model,
                fallback_provider=fallback_name,
                fallback_model_id=fallback_model,
                fallback_triggered=False,
                fallback_trigger_category=None,
                fallback_trigger_reason=None,
                primary_failure_category=None,
                primary_failure_reason=None,
                fallback_failure_category=None,
                fallback_failure_reason=None,
                deadline_exhausted=False,
                preprocessing_time_seconds=prep_elapsed,
                processing_time_seconds=prep_elapsed + primary_run.elapsed_seconds,
                token_usage=primary_run.token_usage,
                primary_token_usage=primary_run.token_usage,
                fallback_token_usage=TokenUsage(),
                request_attempts=len(combined_history),
                attempt_history=combined_history,
                document_result=doc,
                shifts=list(doc.shifts),
                raw_response=raw_text,
                reasoning_text=reasoning_text,
                preprocessing_applied=page_steps,
                config_snapshot=cfg.to_public_dict(),
            )
            logger.info("AI extraction complete: %s", res.to_log_summary())
            return res

        # Primary failed, returned suspicious empty shifts, or produced only partial extraction.
        primary_has_partial = bool(
            primary_run.parsed_result is not None and primary_run.parsed_result.shifts
        )
        deadline_hit = primary_run.deadline_exhausted or (
            deadline_epoch is not None and self._clock_fn() >= deadline_epoch
        )
        can_failover = bool(
            cfg.fallback_enabled
            and self._fallback_adapter is not None
            and not deadline_hit
        )
        if (
            primary_run.failure_category
            in (
                "missing_credentials",
                "authentication_error",
                "configuration_or_client_error",
            )
            and not cfg.failover_on_auth_or_config_error
        ):
            can_failover = False
        if primary_has_partial and not cfg.failover_on_partial_extraction:
            can_failover = False

        fallback_triggered = False
        fallback_run: ProviderAttemptOutcome | None = None
        if can_failover and self._fallback_adapter is not None:
            fallback_triggered = True
            logger.warning(
                "Triggering AI provider failover: file=%s primary=%s reason_category=%s fallback=%s",
                file_name,
                primary_name,
                primary_run.failure_category,
                self._fallback_adapter.provider_name,
            )
            fallback_run = run_provider_attempts(
                self._fallback_adapter,
                request,
                max_retries=cfg.fallback_max_retries,
                backoff_seconds=cfg.retry_backoff_seconds,
                per_attempt_timeout_seconds=cfg.per_attempt_timeout_seconds,
                deadline_epoch=deadline_epoch,
                reject_empty_shifts=True,
                clock_fn=self._clock_fn,
                sleep_fn=self._sleep_fn,
            )
            combined_history.extend(
                rec.to_dict() for rec in fallback_run.attempt_records
            )
            deadline_hit = deadline_hit or fallback_run.deadline_exhausted

            if fallback_run.succeeded and fallback_run.parsed_result is not None:
                doc = fallback_run.parsed_result
                raw_text = (
                    fallback_run.raw_response.raw_text
                    if fallback_run.raw_response is not None
                    else ""
                )
                reasoning_text = (
                    fallback_run.raw_response.reasoning_text
                    if fallback_run.raw_response is not None
                    else None
                )
                total_tok = sum_token_usage(
                    [primary_run.token_usage, fallback_run.token_usage]
                )
                total_elapsed = (
                    prep_elapsed
                    + primary_run.elapsed_seconds
                    + fallback_run.elapsed_seconds
                )
                res = OrchestratedExtractionResult(
                    file_name=file_name,
                    target_worker=target_worker,
                    page_count=len(pages),
                    extraction_status="complete",
                    succeeded=True,
                    is_complete=True,
                    is_partial=False,
                    is_failed=False,
                    is_empty_schedule=False,
                    manual_entry_required=False,
                    manual_entry_reason=None,
                    active_provider=self._fallback_adapter.provider_name,
                    active_model_id=doc.model_id,
                    primary_provider=primary_name,
                    primary_model_id=primary_model,
                    fallback_provider=fallback_name,
                    fallback_model_id=fallback_model,
                    fallback_triggered=True,
                    fallback_trigger_category=primary_run.failure_category,
                    fallback_trigger_reason=primary_run.failure_reason,
                    primary_failure_category=primary_run.failure_category,
                    primary_failure_reason=primary_run.failure_reason,
                    fallback_failure_category=None,
                    fallback_failure_reason=None,
                    deadline_exhausted=False,
                    preprocessing_time_seconds=prep_elapsed,
                    processing_time_seconds=total_elapsed,
                    token_usage=total_tok,
                    primary_token_usage=primary_run.token_usage,
                    fallback_token_usage=fallback_run.token_usage,
                    request_attempts=len(combined_history),
                    attempt_history=combined_history,
                    document_result=doc,
                    shifts=list(doc.shifts),
                    raw_response=raw_text,
                    reasoning_text=reasoning_text,
                    preprocessing_applied=page_steps,
                    config_snapshot=cfg.to_public_dict(),
                )
                logger.info(
                    "AI extraction recovered via fallback: %s", res.to_log_summary()
                )
                return res

        total_tok = sum_token_usage(
            [
                primary_run.token_usage,
                fallback_run.token_usage if fallback_run is not None else TokenUsage(),
            ]
        )
        total_elapsed = (
            prep_elapsed
            + primary_run.elapsed_seconds
            + (fallback_run.elapsed_seconds if fallback_run is not None else 0.0)
        )

        # Corroborated genuinely empty schedule check (requires positive schedule context).
        primary_empty_ctx = _has_positive_empty_schedule_context(
            primary_run.parsed_result
        )
        fallback_empty_ctx = (
            fallback_run is not None
            and _has_positive_empty_schedule_context(fallback_run.parsed_result)
        )
        corroborated_empty = bool(primary_empty_ctx and fallback_empty_ctx)
        single_provider_empty_allowed = bool(
            cfg.allow_single_provider_empty_schedule
            and primary_empty_ctx
            and primary_run.parsed_result is not None
            and primary_run.parsed_result.week_of is not None
            and primary_run.parsed_result.filtered_other_worker_shifts > 0
            and (fallback_run is None or fallback_empty_ctx)
        )
        if corroborated_empty or single_provider_empty_allowed:
            chosen_empty_doc = primary_run.parsed_result
            raw_text = (
                primary_run.raw_response.raw_text
                if primary_run.raw_response is not None
                else ""
            )
            res = OrchestratedExtractionResult(
                file_name=file_name,
                target_worker=target_worker,
                page_count=len(pages),
                extraction_status="complete",
                succeeded=True,
                is_complete=True,
                is_partial=False,
                is_failed=False,
                is_empty_schedule=True,
                manual_entry_required=True,
                manual_entry_reason=(
                    "No shifts detected for worker across corroborated schedule extraction; "
                    "worker confirmation required."
                ),
                active_provider=primary_name,
                active_model_id=(
                    chosen_empty_doc.model_id if chosen_empty_doc else primary_model
                ),
                primary_provider=primary_name,
                primary_model_id=primary_model,
                fallback_provider=fallback_name,
                fallback_model_id=fallback_model,
                fallback_triggered=fallback_triggered,
                fallback_trigger_category=(
                    primary_run.failure_category if fallback_triggered else None
                ),
                fallback_trigger_reason=(
                    primary_run.failure_reason if fallback_triggered else None
                ),
                primary_failure_category=None,
                primary_failure_reason=None,
                fallback_failure_category=None,
                fallback_failure_reason=None,
                deadline_exhausted=deadline_hit,
                preprocessing_time_seconds=prep_elapsed,
                processing_time_seconds=total_elapsed,
                token_usage=total_tok,
                primary_token_usage=primary_run.token_usage,
                fallback_token_usage=(
                    fallback_run.token_usage
                    if fallback_run is not None
                    else TokenUsage()
                ),
                request_attempts=len(combined_history),
                attempt_history=combined_history,
                document_result=chosen_empty_doc,
                shifts=[],
                raw_response=raw_text,
                reasoning_text=None,
                preprocessing_applied=page_steps,
                config_snapshot=cfg.to_public_dict(),
            )
            logger.info("AI extraction corroborated empty schedule: %s", res.to_log_summary())
            return res

        # Select at most one best partial extraction if any shifts were validly recovered (never merge).
        candidates: list[ProviderAttemptOutcome] = []
        if primary_run.parsed_result is not None and primary_run.parsed_result.shifts:
            candidates.append(primary_run)
        if (
            fallback_run is not None
            and fallback_run.parsed_result is not None
            and fallback_run.parsed_result.shifts
        ):
            candidates.append(fallback_run)

        if candidates:
            chosen = max(
                candidates,
                key=lambda o: (
                    len(o.parsed_result.shifts if o.parsed_result else []),
                    -(o.parsed_result.invalid_or_empty_records if o.parsed_result else 0),
                ),
            )
            chosen_doc = chosen.parsed_result
            raw_text = chosen.raw_response.raw_text if chosen.raw_response else ""
            reasoning_text = (
                chosen.raw_response.reasoning_text if chosen.raw_response else None
            )
            if chosen_doc is not None and chosen_doc.invalid_or_empty_records > 0 and not chosen_doc.partial_recovery_triggered:
                manual_reason = (
                    f"Extraction was incomplete ({len(chosen_doc.shifts)} valid shift(s) kept and "
                    f"{chosen_doc.invalid_or_empty_records} invalid/empty record(s) rejected from "
                    f"{chosen.provider_name}); review surviving shifts and manually enter any missing shifts."
                )
            else:
                manual_reason = (
                    f"Extraction was incomplete/truncated ({len(chosen_doc.shifts) if chosen_doc else 0} "
                    f"shift(s) partially recovered from {chosen.provider_name}); review recovered shifts "
                    "and manually enter any missing shifts."
                )
            res = OrchestratedExtractionResult(
                file_name=file_name,
                target_worker=target_worker,
                page_count=len(pages),
                extraction_status="partial",
                succeeded=False,
                is_complete=False,
                is_partial=True,
                is_failed=False,
                is_empty_schedule=False,
                manual_entry_required=True,
                manual_entry_reason=manual_reason,
                active_provider=chosen.provider_name,
                active_model_id=chosen_doc.model_id if chosen_doc else chosen.model_id,
                primary_provider=primary_name,
                primary_model_id=primary_model,
                fallback_provider=fallback_name,
                fallback_model_id=fallback_model,
                fallback_triggered=fallback_triggered,
                fallback_trigger_category=(
                    primary_run.failure_category if fallback_triggered else None
                ),
                fallback_trigger_reason=(
                    primary_run.failure_reason if fallback_triggered else None
                ),
                primary_failure_category=primary_run.failure_category,
                primary_failure_reason=primary_run.failure_reason,
                fallback_failure_category=(
                    fallback_run.failure_category if fallback_run is not None else None
                ),
                fallback_failure_reason=(
                    fallback_run.failure_reason if fallback_run is not None else None
                ),
                deadline_exhausted=deadline_hit,
                preprocessing_time_seconds=prep_elapsed,
                processing_time_seconds=total_elapsed,
                token_usage=total_tok,
                primary_token_usage=primary_run.token_usage,
                fallback_token_usage=(
                    fallback_run.token_usage
                    if fallback_run is not None
                    else TokenUsage()
                ),
                request_attempts=len(combined_history),
                attempt_history=combined_history,
                document_result=chosen_doc,
                shifts=list(chosen_doc.shifts) if chosen_doc is not None else [],
                raw_response=raw_text,
                reasoning_text=reasoning_text,
                preprocessing_applied=page_steps,
                config_snapshot=cfg.to_public_dict(),
            )
            logger.warning("AI extraction partial: %s", res.to_log_summary())
            return res

        # Total failure across configured provider chain -> explicit failure + manual entry required.
        reasons: list[str] = []
        if primary_run.failure_reason:
            reasons.append(f"Primary ({primary_name}): {primary_run.failure_reason}")
        if fallback_run is not None and fallback_run.failure_reason:
            reasons.append(
                f"Fallback ({fallback_run.provider_name}): {fallback_run.failure_reason}"
            )
        if deadline_hit:
            reasons.append("Overall processing deadline exhausted.")
        combined_reason = " | ".join(reasons) or "AI schedule extraction failed."

        res = OrchestratedExtractionResult(
            file_name=file_name,
            target_worker=target_worker,
            page_count=len(pages),
            extraction_status="failed",
            succeeded=False,
            is_complete=False,
            is_partial=False,
            is_failed=True,
            is_empty_schedule=False,
            manual_entry_required=True,
            manual_entry_reason=combined_reason,
            active_provider=None,
            active_model_id=None,
            primary_provider=primary_name,
            primary_model_id=primary_model,
            fallback_provider=fallback_name,
            fallback_model_id=fallback_model,
            fallback_triggered=fallback_triggered,
            fallback_trigger_category=(
                primary_run.failure_category if fallback_triggered else None
            ),
            fallback_trigger_reason=(
                primary_run.failure_reason if fallback_triggered else None
            ),
            primary_failure_category=primary_run.failure_category,
            primary_failure_reason=primary_run.failure_reason,
            fallback_failure_category=(
                fallback_run.failure_category if fallback_run is not None else None
            ),
            fallback_failure_reason=(
                fallback_run.failure_reason if fallback_run is not None else None
            ),
            deadline_exhausted=deadline_hit,
            preprocessing_time_seconds=prep_elapsed,
            processing_time_seconds=total_elapsed,
            token_usage=total_tok,
            primary_token_usage=primary_run.token_usage,
            fallback_token_usage=(
                fallback_run.token_usage if fallback_run is not None else TokenUsage()
            ),
            request_attempts=len(combined_history),
            attempt_history=combined_history,
            document_result=(
                fallback_run.parsed_result
                if fallback_run is not None and fallback_run.parsed_result is not None
                else primary_run.parsed_result
            ),
            shifts=[],
            raw_response=(
                fallback_run.raw_response.raw_text
                if fallback_run is not None and fallback_run.raw_response is not None
                else (
                    primary_run.raw_response.raw_text
                    if primary_run.raw_response is not None
                    else ""
                )
            ),
            reasoning_text=None,
            preprocessing_applied=page_steps,
            config_snapshot=cfg.to_public_dict(),
        )
        logger.warning("AI extraction failed: %s", res.to_log_summary())
        return res

    def _build_prep_failure_result(
        self,
        *,
        file_name: str,
        target_worker: str | None,
        error_msg: str,
        preprocessing_time_seconds: float = 0.0,
        processing_time_seconds: float = 0.0,
        preprocessing_applied: tuple[tuple[str, ...], ...] = (),
    ) -> OrchestratedExtractionResult:
        cfg = self._config
        return OrchestratedExtractionResult(
            file_name=file_name,
            target_worker=target_worker,
            page_count=0,
            extraction_status="failed",
            succeeded=False,
            is_complete=False,
            is_partial=False,
            is_failed=True,
            is_empty_schedule=False,
            manual_entry_required=True,
            manual_entry_reason=error_msg,
            active_provider=None,
            active_model_id=None,
            primary_provider=self._primary_adapter.provider_name,
            primary_model_id=self._primary_adapter.model_id,
            fallback_provider=(
                self._fallback_adapter.provider_name
                if self._fallback_adapter is not None
                else cfg.resolved_fallback_provider
            ),
            fallback_model_id=(
                self._fallback_adapter.model_id
                if self._fallback_adapter is not None
                else cfg.resolved_fallback_model_id
            ),
            fallback_triggered=False,
            fallback_trigger_category=None,
            fallback_trigger_reason=None,
            primary_failure_category="document_preparation_error",
            primary_failure_reason=error_msg,
            fallback_failure_category=None,
            fallback_failure_reason=None,
            deadline_exhausted=False,
            preprocessing_time_seconds=preprocessing_time_seconds,
            processing_time_seconds=processing_time_seconds,
            token_usage=TokenUsage(),
            primary_token_usage=TokenUsage(),
            fallback_token_usage=TokenUsage(),
            request_attempts=0,
            attempt_history=[],
            document_result=None,
            shifts=[],
            preprocessing_applied=preprocessing_applied,
            config_snapshot=cfg.to_public_dict(),
        )

    def extract_file(
        self,
        file_path: str | Path,
        *,
        target_worker: str | None = None,
        dpi: int | None = None,
        preprocess_images: bool | None = None,
        deskew: bool | None = None,
        perspective_correct: bool | None = None,
        enhance_contrast: bool | None = None,
    ) -> OrchestratedExtractionResult:
        """Load and extract a schedule document from disk (never opens any answer key)."""
        path = Path(file_path)
        cfg = self._config
        overall_start = self._clock_fn()
        try:
            pages = load_document_pages(
                path,
                dpi=cfg.pdf_dpi if dpi is None else dpi,
                preprocess_images=(
                    cfg.preprocess_images
                    if preprocess_images is None
                    else preprocess_images
                ),
                deskew=cfg.deskew if deskew is None else deskew,
                perspective_correct=(
                    cfg.perspective_correct
                    if perspective_correct is None
                    else perspective_correct
                ),
                enhance_contrast=(
                    cfg.enhance_contrast
                    if enhance_contrast is None
                    else enhance_contrast
                ),
            )
        except Exception as exc:
            prep_elapsed = max(0.0, self._clock_fn() - overall_start)
            err = f"Document preparation error ({type(exc).__name__}): {exc}"
            logger.warning(
                "AI document load failed: file=%s error_type=%s",
                path.name,
                type(exc).__name__,
            )
            return self._build_prep_failure_result(
                file_name=path.name,
                target_worker=target_worker,
                error_msg=err,
                preprocessing_time_seconds=prep_elapsed,
                processing_time_seconds=prep_elapsed,
            )

        return self.extract_prepared_pages(
            pages,
            file_name=path.name,
            target_worker=target_worker,
            start_epoch=overall_start,
        )

    def extract_bytes(
        self,
        file_bytes: bytes,
        *,
        file_name: str,
        target_worker: str | None = None,
        dpi: int | None = None,
        preprocess_images: bool | None = None,
        deskew: bool | None = None,
        perspective_correct: bool | None = None,
        enhance_contrast: bool | None = None,
    ) -> OrchestratedExtractionResult:
        """Load and extract a schedule document from uploaded bytes (FastAPI-ready)."""
        cfg = self._config
        overall_start = self._clock_fn()
        try:
            pages = load_document_pages_from_bytes(
                file_bytes,
                file_name=file_name,
                dpi=cfg.pdf_dpi if dpi is None else dpi,
                preprocess_images=(
                    cfg.preprocess_images
                    if preprocess_images is None
                    else preprocess_images
                ),
                deskew=cfg.deskew if deskew is None else deskew,
                perspective_correct=(
                    cfg.perspective_correct
                    if perspective_correct is None
                    else perspective_correct
                ),
                enhance_contrast=(
                    cfg.enhance_contrast
                    if enhance_contrast is None
                    else enhance_contrast
                ),
            )
        except Exception as exc:
            prep_elapsed = max(0.0, self._clock_fn() - overall_start)
            err = f"Document preparation error ({type(exc).__name__}): {exc}"
            logger.warning(
                "AI uploaded bytes load failed: file=%s error_type=%s",
                file_name,
                type(exc).__name__,
            )
            return self._build_prep_failure_result(
                file_name=file_name,
                target_worker=target_worker,
                error_msg=err,
                preprocessing_time_seconds=prep_elapsed,
                processing_time_seconds=prep_elapsed,
            )

        return self.extract_prepared_pages(
            pages,
            file_name=file_name,
            target_worker=target_worker,
            start_epoch=overall_start,
        )
