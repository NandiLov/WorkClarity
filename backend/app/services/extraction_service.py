"""Service layer for AI schedule extraction via ExtractionOrchestrator."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from ai_extraction.orchestrator import (
    ExtractionAdapter,
    ExtractionOrchestrator,
    ExtractionServiceConfig,
    OrchestratedExtractionResult,
)

logger = logging.getLogger(__name__)

# Maximum file upload size: 20 MB
MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
)

_cached_orchestrator: ExtractionOrchestrator | None = None


def get_extraction_orchestrator(
    config: ExtractionServiceConfig | None = None,
    *,
    primary_adapter: ExtractionAdapter | None = None,
    fallback_adapter: ExtractionAdapter | None = None,
) -> ExtractionOrchestrator:
    """Return an orchestrator instance, allowing dependency injection in tests."""
    if primary_adapter is not None or fallback_adapter is not None or config is not None:
        return ExtractionOrchestrator(
            config=config or ExtractionServiceConfig.from_env(),
            primary_adapter=primary_adapter,
            fallback_adapter=fallback_adapter,
        )

    global _cached_orchestrator
    if _cached_orchestrator is None:
        _cached_orchestrator = ExtractionOrchestrator(
            config=ExtractionServiceConfig.from_env(),
        )
    return _cached_orchestrator


def get_extraction_service() -> ExtractionOrchestrator:
    """FastAPI dependency for extraction orchestrator."""
    return get_extraction_orchestrator()


def validate_upload_file(
    file_name: str | None,
    file_bytes: bytes,
) -> str:
    """Validate uploaded schedule file name, size, extension, and magic bytes.

    Returns the clean lowercased extension on success.
    Raises HTTPException on validation failure.
    """
    if not file_name or not file_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required and cannot be empty.",
        )

    clean_name = file_name.strip()
    ext = Path(clean_name).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        supported_str = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Supported schedule formats are: {supported_str}",
        )

    if not file_bytes or len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )

    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds maximum permitted size limit of {max_mb} MB.",
        )

    # Magic byte verification
    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PDF file: corrupted header or incorrect file format.",
            )
    elif ext == ".png":
        if not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PNG file: corrupted header or incorrect file format.",
            )
    elif ext in (".jpg", ".jpeg"):
        if not file_bytes.startswith(b"\xff\xd8\xff"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JPEG file: corrupted header or incorrect file format.",
            )
    elif ext == ".webp":
        if len(file_bytes) < 12 or not (
            file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid WebP file: corrupted header or incorrect file format.",
            )

    return ext


_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"nvapi-[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (
        re.compile(r"(?i)(api[_-]?key|token|secret|key)\s*[:=]\s*[^\s&\"',}]+"),
        r"\1=[REDACTED]",
    ),
)
_MAX_REASON_LENGTH = 300


def sanitize_manual_entry_reason(reason: str | None) -> str | None:
    """Redact potential credentials/tokens and truncate provider error text."""
    if not reason or not reason.strip():
        return None

    sanitized = reason
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if len(sanitized) > _MAX_REASON_LENGTH:
        sanitized = sanitized[: _MAX_REASON_LENGTH - 3] + "..."
    return sanitized


def extract_schedule_bytes(
    file_bytes: bytes,
    *,
    file_name: str,
    target_worker: str | None = None,
    orchestrator: ExtractionOrchestrator | None = None,
) -> OrchestratedExtractionResult:
    """Run extraction orchestrator on uploaded document bytes."""
    orch = orchestrator or get_extraction_orchestrator()
    return orch.extract_bytes(
        file_bytes,
        file_name=file_name,
        target_worker=target_worker,
    )
