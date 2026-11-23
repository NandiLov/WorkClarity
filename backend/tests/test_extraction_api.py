"""Backend unit and integration tests for schedule extraction API."""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from ai_extraction.orchestrator import (
    ExtractionAdapter,
    ExtractionOrchestrator,
    ExtractionServiceConfig,
    ProviderExtractionRequest,
    ProviderRawResponse,
    TokenUsage,
)
from backend.app.main import app, get_cors_origins
from backend.app.services import extraction_service
from backend.app.services.extraction_service import (
    MAX_UPLOAD_SIZE_BYTES,
    get_extraction_service,
)

client = TestClient(app)


def test_cached_orchestrator_uses_environment_configuration(monkeypatch):
    """The default API orchestrator should respect deployment environment settings."""
    monkeypatch.setenv("AI_EXTRACTION_PRIMARY_PROVIDER", "nvidia")
    monkeypatch.setenv("AI_EXTRACTION_FALLBACK_ENABLED", "false")

    extraction_service._cached_orchestrator = None

    try:
        orchestrator = extraction_service.get_extraction_orchestrator()
        config = orchestrator._config.to_public_dict()

        assert config["primary_provider"] == "nvidia"
        assert config["fallback_enabled"] is False
    finally:
        extraction_service._cached_orchestrator = None


# Minimal 1-page valid PDF starting with %PDF-1.4
MINIMAL_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj "
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj "
    b"3 0 obj<</Type/Page/MediaBox[0 0 100 100]/Parent 2 0 R/Resources<<>>>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000102 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n185\n%%EOF\n"
)


def make_test_image(fmt: str) -> bytes:
    """Generate minimal valid image bytes for PNG, JPEG, or WEBP."""
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format=fmt)
    return buf.getvalue()


class MockSuccessAdapter(ExtractionAdapter):
    """Deterministic mock extraction adapter returning synthetic shifts."""

    def __init__(
        self,
        name: str = "gemini",
        model: str = "gemini-3.5-flash-lite",
        shifts: list[dict[str, Any]] | None = None,
    ) -> None:
        self._name = name
        self._model = model
        self._shifts = shifts or [
            {
                "shift_date": "2026-11-09",
                "start_time": "09:00",
                "end_time": "17:00",
                "break_minutes": "30",
                "employer_name": "Sunrise Cafe",
                "location": "Downtown",
                "department": "Barista",
                "hourly_rate": "22.50",
                "currency": "USD",
                "shift_status": "scheduled",
                "worker_name": "Ada Okoye",
            },
            {
                "shift_date": "2026-11-10",
                "start_time": "10:00",
                "end_time": "18:00",
                "break_minutes": "0",
                "employer_name": "Sunrise Cafe",
                "location": "Downtown",
                "department": "Barista",
                "hourly_rate": "22.50",
                "currency": "USD",
                "shift_status": "scheduled",
                "worker_name": "Ada Okoye",
            },
        ]

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return self._model

    def extract(self, request: ProviderExtractionRequest) -> ProviderRawResponse:
        payload = {"shifts": self._shifts}
        return ProviderRawResponse(
            provider_name=self.provider_name,
            model_id=self.model_id,
            raw_text=json.dumps(payload),
            finish_reason="stop",
            token_usage=TokenUsage(120, 80, 0, 200),
            elapsed_seconds=0.08,
        )


class MockFailingAdapter(ExtractionAdapter):
    """Mock adapter that raises an error simulating network or quota failure."""

    def __init__(
        self,
        name: str = "gemini",
        model: str = "mock-model",
        error_message: str = "Simulated upstream network timeout or quota exhaustion.",
    ) -> None:
        self._name = name
        self._model = model
        self._error_message = error_message

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return self._model

    def extract(self, request: ProviderExtractionRequest) -> ProviderRawResponse:
        from ai_extraction.providers.base import ProviderRequestError

        raise ProviderRequestError(self._error_message)


@pytest.fixture
def mock_orchestrator():
    """FastAPI dependency override providing deterministic mock extraction orchestrator."""
    adapter = MockSuccessAdapter()
    orch = ExtractionOrchestrator(
        config=ExtractionServiceConfig(
            primary_provider="gemini",
            fallback_enabled=False,
        ),
        primary_adapter=adapter,
    )
    app.dependency_overrides[get_extraction_service] = lambda: orch
    yield orch
    app.dependency_overrides.pop(get_extraction_service, None)


# --- File Validation & Error Rejection Tests ---


def test_extract_rejects_empty_file():
    """Verify empty 0-byte file upload returns 400."""
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_extract_rejects_missing_filename():
    """Verify upload with missing/empty filename returns 400 or 422."""
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("", b"some-content", "image/png")},
    )
    assert response.status_code in (400, 422)


def test_extract_rejects_unsupported_extensions():
    """Verify upload of unsupported file types (.csv, .txt, .docx) returns 400."""
    for bad_name in ("schedule.csv", "rota.txt", "shifts.docx", "script.exe"):
        response = client.post(
            "/api/v1/shifts/extract",
            files={"file": (bad_name, b"some-bytes", "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "unsupported" in response.json()["detail"].lower()


def test_extract_rejects_corrupted_pdf_header():
    """Verify .pdf with invalid magic bytes is rejected."""
    bad_pdf_bytes = b"NOT_A_PDF_HEADER_CONTENT"
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("schedule.pdf", bad_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 400
    assert "invalid pdf" in response.json()["detail"].lower()


def test_extract_rejects_corrupted_png_header():
    """Verify .png with invalid magic bytes is rejected."""
    bad_png_bytes = b"NOT_A_PNG_HEADER"
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("schedule.png", bad_png_bytes, "image/png")},
    )
    assert response.status_code == 400
    assert "invalid png" in response.json()["detail"].lower()


def test_extract_rejects_corrupted_jpeg_header():
    """Verify .jpg with invalid magic bytes is rejected."""
    bad_jpg_bytes = b"NOT_A_JPEG_HEADER"
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("schedule.jpg", bad_jpg_bytes, "image/jpeg")},
    )
    assert response.status_code == 400
    assert "invalid jpeg" in response.json()["detail"].lower()


def test_extract_rejects_corrupted_webp_header():
    """Verify .webp with invalid magic bytes is rejected."""
    bad_webp_bytes = b"RIFF____NOTWEBP"
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("schedule.webp", bad_webp_bytes, "image/webp")},
    )
    assert response.status_code == 400
    assert "invalid webp" in response.json()["detail"].lower()


def test_extract_rejects_oversized_file():
    """Verify files exceeding 20 MB return 413."""
    oversized_bytes = b"X" * (MAX_UPLOAD_SIZE_BYTES + 1024)
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("large.png", oversized_bytes, "image/png")},
    )
    assert response.status_code == 413
    assert "exceeds maximum permitted size" in response.json()["detail"].lower()


# --- Successful Extraction & Format Support Tests ---


def test_extract_valid_png_success(mock_orchestrator):
    """Verify valid PNG file extraction returns structured response with review safeguards."""
    png_bytes = make_test_image("PNG")
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("weekly_rota.png", png_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["file_name"] == "weekly_rota.png"
    assert data["succeeded"] is True
    assert data["is_complete"] is True
    assert data["active_provider"] == "gemini"
    assert data["total_shifts_extracted"] == 2
    assert len(data["shifts"]) == 2

    # Verification of safeguards (Requirement 8)
    for shift in data["shifts"]:
        assert shift["confirmation_status"] == "needs_review"
        assert shift["requires_worker_confirmation"] is True
        assert shift["requires_individual_review"] is True
        assert shift["eligible_for_bulk_confirmation"] is False
        assert shift["normalised"]["employer_name"] == "Sunrise Cafe"


def test_extract_valid_pdf_success(mock_orchestrator):
    """Verify valid PDF document extraction works end-to-end."""
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("roster.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "roster.pdf"
    assert data["page_count"] == 1
    assert data["succeeded"] is True
    assert data["total_shifts_extracted"] == 2


def test_extract_valid_jpeg_success(mock_orchestrator):
    """Verify valid JPEG file extraction."""
    jpg_bytes = make_test_image("JPEG")
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("schedule.jpg", jpg_bytes, "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["succeeded"] is True


def test_extract_valid_webp_success(mock_orchestrator):
    """Verify valid WebP file extraction (Requirement 3)."""
    webp_bytes = make_test_image("WEBP")
    response = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("schedule.webp", webp_bytes, "image/webp")},
    )
    assert response.status_code == 200
    assert response.json()["succeeded"] is True


def test_extract_target_worker_disambiguation():
    """Verify optional target_worker parameter filters other worker shifts (Requirement 6)."""
    shifts_with_two_workers = [
        {
            "shift_date": "2026-11-09",
            "start_time": "09:00",
            "end_time": "17:00",
            "break_minutes": "30",
            "employer_name": "Retail Store",
            "hourly_rate": "20.00",
            "currency": "USD",
            "shift_status": "scheduled",
            "worker_name": "Ada Okoye",
        },
        {
            "shift_date": "2026-11-09",
            "start_time": "10:00",
            "end_time": "18:00",
            "break_minutes": "30",
            "employer_name": "Retail Store",
            "hourly_rate": "20.00",
            "currency": "USD",
            "shift_status": "scheduled",
            "worker_name": "John Smith",
        },
    ]

    adapter = MockSuccessAdapter(shifts=shifts_with_two_workers)
    orch = ExtractionOrchestrator(
        config=ExtractionServiceConfig(primary_provider="gemini", fallback_enabled=False),
        primary_adapter=adapter,
    )
    app.dependency_overrides[get_extraction_service] = lambda: orch

    try:
        png_bytes = make_test_image("PNG")
        response = client.post(
            "/api/v1/shifts/extract",
            data={"target_worker": "Ada Okoye"},
            files={"file": ("roster.png", png_bytes, "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["target_worker"] == "Ada Okoye"
        # John Smith's shift is filtered out as other_worker
        assert data["total_shifts_extracted"] == 1
        assert data["shifts"][0]["worker_name"] == "Ada Okoye"
        assert data["shifts"][0]["worker_attribution_status"] == "verified_target_worker"
    finally:
        app.dependency_overrides.pop(get_extraction_service, None)


# --- Safeguard & Earnings Invariant Verification (Requirements 8 & 9) ---


def test_unconfirmed_extracted_shifts_excluded_from_earnings(mock_orchestrator):
    """Verify extracted shifts default to needs_review and are strictly excluded from gross earnings.

    Only upon explicit worker confirmation do they contribute to earnings.
    """
    png_bytes = make_test_image("PNG")
    extract_resp = client.post(
        "/api/v1/shifts/extract",
        files={"file": ("weekly_rota.png", png_bytes, "image/png")},
    )
    assert extract_resp.status_code == 200
    extracted_data = extract_resp.json()

    # Build calculation payload directly using the extracted shifts
    calc_shifts = []
    for idx, shift in enumerate(extracted_data["shifts"]):
        norm = shift["normalised"]
        calc_shifts.append(
            {
                "shift_id": f"EXTRACTED_{idx + 1}",
                "employer_name": norm["employer_name"],
                "shift_date": norm["shift_date"],
                "start_time": norm["start_time"],
                "end_time": norm["end_time"],
                "break_minutes": norm["break_minutes"],
                "hourly_rate": norm["hourly_rate"],
                "currency": norm["currency"],
                "shift_status": norm["shift_status"],
                "confirmation_status": shift["confirmation_status"],  # "needs_review"
            }
        )

    calc_payload = {
        "worker_id": "W123",
        "shifts": calc_shifts,
        "include_unconfirmed": False,
    }

    # Step A: As extracted (unconfirmed/needs_review) -> gross earnings MUST be excluded
    calc_resp = client.post("/api/v1/shifts/calculate", json=calc_payload)
    assert calc_resp.status_code == 200
    calc_data = calc_resp.json()

    for shift_result in calc_data["shifts"]:
        assert shift_result["eligible_for_earnings"] is False
        assert shift_result["gross_earnings"] is None
        assert shift_result["earnings_status"] == "needs_review"

    # Weekly summary gross earnings must be 0 / None, and shifts are recorded as pending
    summary = calc_data["weekly_summary"][0]
    assert summary["gross_earnings"] is None
    assert summary["pending_shifts"] == 2
    assert summary["paid_hours"] == 0.0

    # Step B: Worker confirms shifts -> earnings MUST now be counted
    for s in calc_shifts:
        s["confirmation_status"] = "confirmed"

    confirmed_resp = client.post(
        "/api/v1/shifts/calculate",
        json={"worker_id": "W123", "shifts": calc_shifts},
    )
    assert confirmed_resp.status_code == 200
    confirmed_data = confirmed_resp.json()

    for shift_result in confirmed_data["shifts"]:
        assert shift_result["eligible_for_earnings"] is True
        assert shift_result["gross_earnings"] is not None
        assert shift_result["earnings_status"] == "counted"

    confirmed_summary = confirmed_data["weekly_summary"][0]
    assert confirmed_summary["gross_earnings"] > 0
    assert confirmed_summary["pending_shifts"] == 0


# --- Provider Failover & Error Handling Tests ---


def test_extract_provider_fallback():
    """Verify primary provider failure triggers seamless fallback to secondary provider."""
    failing_gemini = MockFailingAdapter(name="gemini", model="gemini-3.5-flash-lite")
    successful_nvidia = MockSuccessAdapter(
        name="nvidia",
        model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    )

    orch = ExtractionOrchestrator(
        config=ExtractionServiceConfig(
            primary_provider="gemini",
            fallback_provider="nvidia",
            fallback_enabled=True,
            failover_on_auth_or_config_error=True,
            primary_max_retries=0,
        ),
        primary_adapter=failing_gemini,
        fallback_adapter=successful_nvidia,
    )
    app.dependency_overrides[get_extraction_service] = lambda: orch

    try:
        png_bytes = make_test_image("PNG")
        response = client.post(
            "/api/v1/shifts/extract",
            files={"file": ("rota.png", png_bytes, "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["succeeded"] is True
        assert data["fallback_triggered"] is True
        assert data["active_provider"] == "nvidia"
        assert data["active_model_id"] == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
        assert data["total_shifts_extracted"] == 2
    finally:
        app.dependency_overrides.pop(get_extraction_service, None)


def test_extract_all_providers_fail_gracefully():
    """Verify that when all providers fail, API returns structured manual entry notice without 500 error."""
    failing_primary = MockFailingAdapter(name="gemini")
    failing_fallback = MockFailingAdapter(name="nvidia")

    orch = ExtractionOrchestrator(
        config=ExtractionServiceConfig(
            primary_provider="gemini",
            fallback_provider="nvidia",
            fallback_enabled=True,
            primary_max_retries=0,
            fallback_max_retries=0,
        ),
        primary_adapter=failing_primary,
        fallback_adapter=failing_fallback,
    )
    app.dependency_overrides[get_extraction_service] = lambda: orch

    try:
        png_bytes = make_test_image("PNG")
        response = client.post(
            "/api/v1/shifts/extract",
            files={"file": ("rota.png", png_bytes, "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["succeeded"] is False
        assert data["is_failed"] is True
        assert data["manual_entry_required"] is True
        assert data["total_shifts_extracted"] == 0
    finally:
        app.dependency_overrides.pop(get_extraction_service, None)


# --- CORS Security Tests (Requirement 10) ---


def test_cors_allowed_origin():
    """Verify preflight OPTIONS from explicit allowed origin succeeds."""
    response = client.options(
        "/api/v1/shifts/extract",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_disallows_unauthorized_origin():
    """Verify preflight OPTIONS from unauthorized origin does not return allow-origin."""
    response = client.options(
        "/api/v1/shifts/extract",
        headers={
            "Origin": "http://malicious-site.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_wildcard_is_stripped():
    """Verify get_cors_origins() explicitly strips wildcard '*'."""
    with patch.dict("os.environ", {"WORKCLARITY_CORS_ORIGINS": "https://app.workclarity.com,*,https://admin.workclarity.com"}):
        origins = get_cors_origins()
        assert "*" not in origins
        assert "https://app.workclarity.com" in origins
        assert "https://admin.workclarity.com" in origins


def test_extract_redacts_secrets_in_manual_entry_reason():
    """Verify potential API keys/tokens in provider error messages are redacted."""
    nv_secret = "nvapi-" + "secret1234567890"
    g_secret = "AIza" + "SyFakeKey1234567890"
    bearer_secret = "tok_" + "abc123"
    leaking_adapter = MockFailingAdapter(
        name="gemini",
        error_message=(
            f"Upstream failed using {nv_secret} and {g_secret} "
            f"with header Bearer {bearer_secret} and api_key=my_key_999"
        ),
    )
    orch = ExtractionOrchestrator(
        config=ExtractionServiceConfig(
            primary_provider="gemini",
            fallback_enabled=False,
            primary_max_retries=0,
        ),
        primary_adapter=leaking_adapter,
    )
    app.dependency_overrides[get_extraction_service] = lambda: orch

    try:
        png_bytes = make_test_image("PNG")
        response = client.post(
            "/api/v1/shifts/extract",
            files={"file": ("rota.png", png_bytes, "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["succeeded"] is False
        assert data["manual_entry_required"] is True
        reason = data["manual_entry_reason"] or ""
        assert "[REDACTED]" in reason
        assert nv_secret not in reason
        assert g_secret not in reason
        assert bearer_secret not in reason
        assert "my_key_999" not in reason
        assert "raw_response" not in data
        assert "reasoning_text" not in data
    finally:
        app.dependency_overrides.pop(get_extraction_service, None)
