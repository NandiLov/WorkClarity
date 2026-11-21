from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_extraction.schema import ExtractedShiftRecord


class ShiftCalculationRequest(BaseModel):
    """Request body for validating shifts and calculating earnings."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str

    shifts: list[dict[str, Any]] = Field(default_factory=list)

    include_unconfirmed: bool = False


class TokenUsageSchema(BaseModel):
    """Token consumption summary for model execution."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0


class ShiftExtractionResponse(BaseModel):
    """Structured response payload for schedule document extraction."""

    file_name: str
    target_worker: str | None = None
    page_count: int
    extraction_status: str
    succeeded: bool
    is_complete: bool
    is_partial: bool
    is_failed: bool
    is_empty_schedule: bool
    manual_entry_required: bool
    manual_entry_reason: str | None = None
    active_provider: str | None = None
    active_model_id: str | None = None
    fallback_triggered: bool = False
    fallback_trigger_category: str | None = None
    processing_time_seconds: float
    token_usage: TokenUsageSchema | None = None
    total_shifts_extracted: int
    shifts: list[ExtractedShiftRecord] = Field(default_factory=list)
