from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ai_extraction.orchestrator import ExtractionOrchestrator
from backend.app.schemas.shift import (
    ShiftCalculationRequest,
    ShiftExtractionResponse,
    TokenUsageSchema,
)
from backend.app.services.extraction_service import (
    MAX_UPLOAD_SIZE_BYTES,
    get_extraction_service,
    sanitize_manual_entry_reason,
    validate_upload_file,
)
from backend.app.services.shift_calculations import (
    calculate_shifts,
    load_flag_messages,
    load_known_locations,
    load_rules,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/shifts",
    tags=["Shifts"],
)

# Locate the backend configuration directory independently
# of the directory from which the application is started.
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Load trusted, server-controlled configuration.
PAY_RULES = load_rules(CONFIG_DIR / "pay_rules.csv")
KNOWN_LOCATIONS = load_known_locations(CONFIG_DIR / "locations.csv")
FLAG_MESSAGES = load_flag_messages()


@router.post("/calculate")
async def calculate_shift_endpoint(request: ShiftCalculationRequest):
    """Validate submitted shifts and calculate weekly gross earnings."""

    payload = request.model_dump(
        exclude={"include_unconfirmed"}
    )

    result = calculate_shifts(
        payload,
        flag_messages=FLAG_MESSAGES,
        known_locations=KNOWN_LOCATIONS,
        include_unconfirmed=request.include_unconfirmed,
        rules=PAY_RULES,
    )

    return result


@router.post("/extract", response_model=ShiftExtractionResponse)
async def extract_shifts_endpoint(
    file: UploadFile = File(..., description="Schedule document file (PDF, PNG, JPEG, WebP)"),
    target_worker: str | None = Form(default=None, description="Optional target worker name for disambiguation"),
    orchestrator: ExtractionOrchestrator = Depends(get_extraction_service),
):
    """Extract structured shift records from an uploaded PDF or image schedule."""
    file_bytes = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)

    # Validate file extension, size, and magic bytes
    validate_upload_file(file.filename, file_bytes)

    try:
        result = orchestrator.extract_bytes(
            file_bytes,
            file_name=file.filename or "uploaded_schedule",
            target_worker=target_worker.strip() if target_worker and target_worker.strip() else None,
        )
    except Exception:
        logger.exception("Unexpected error during schedule extraction for %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal error occurred during schedule extraction. Please try again or enter shifts manually.",
        )

    # Invariant enforcement: Ensure every extracted shift mandates worker review
    for shift in result.shifts:
        shift.confirmation_status = "needs_review"
        shift.requires_worker_confirmation = True
        shift.requires_individual_review = True
        shift.eligible_for_bulk_confirmation = False

    token_schema = None
    if result.token_usage:
        token_schema = TokenUsageSchema(
            prompt_tokens=result.token_usage.prompt_tokens,
            completion_tokens=result.token_usage.completion_tokens,
            reasoning_tokens=result.token_usage.reasoning_tokens,
            total_tokens=result.token_usage.total_tokens,
        )

    return ShiftExtractionResponse(
        file_name=result.file_name,
        target_worker=result.target_worker,
        page_count=result.page_count,
        extraction_status=result.extraction_status,
        succeeded=result.succeeded,
        is_complete=result.is_complete,
        is_partial=result.is_partial,
        is_failed=result.is_failed,
        is_empty_schedule=result.is_empty_schedule,
        manual_entry_required=result.manual_entry_required,
        manual_entry_reason=sanitize_manual_entry_reason(result.manual_entry_reason),
        active_provider=result.active_provider,
        active_model_id=result.active_model_id,
        fallback_triggered=result.fallback_triggered,
        fallback_trigger_category=result.fallback_trigger_category,
        processing_time_seconds=result.processing_time_seconds,
        token_usage=token_schema,
        total_shifts_extracted=len(result.shifts),
        shifts=result.shifts,
    )
