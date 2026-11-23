"""Automated regression tests for AI extraction schema, providers, PDF utils, and benchmark runner."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import math
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ai_extraction.benchmark import (
    BACKEND_CALC_PATH,
    BACKEND_LOCATIONS_PATH,
    BACKEND_RULES_PATH,
    COMPARE_TOOL_PATH,
    DEFAULT_ANSWER_KEY_CSV,
    DEFAULT_FILES_CSV,
    DEFAULT_OUTPUT_DIR,
    FLAG_TYPES_PATH,
    UNSTRUCTURED_DIR,
    _evaluate_deterministic_validation,
    ensure_rendering_dependencies,
    evaluate_v1_offline_recovery,
    extract_single_document,
    load_files_manifest,
    replay_saved_benchmark_run,
    resolve_versioned_output_dir,
    run_benchmark,
)
from ai_extraction.orchestrator import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_FALLBACK_PROVIDER,
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_PRIMARY_PROVIDER,
    ExtractionOrchestrator,
    ExtractionServiceConfig,
    OrchestratedExtractionResult,
)
from ai_extraction.pdf_utils import (
    ImagePreprocessingDiagnostics,
    MissingRenderingDependencyError,
    _decode_png_rgba,
    _encode_rgba_png,
    _horizontal_projection_variance,
    _rotate_rgba_expanded_python,
    estimate_skew_angle_from_rgba,
    get_available_image_preprocessing_backend,
    get_available_pdf_rendering_backend,
    inspect_and_preprocess_image,
    load_document_pages,
    preprocess_image_bytes,
    render_pdf_to_png_pages,
    render_pdf_to_png_pages_with_backend,
)
from ai_extraction.prompt import SYSTEM_PROMPT, build_user_prompt
from ai_extraction.providers import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_NVIDIA_ENDPOINT,
    DEFAULT_NVIDIA_MAX_RETRIES,
    DEFAULT_NVIDIA_MAX_TOKENS,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REASONING_BUDGET,
    DEFAULT_NVIDIA_TEMPERATURE,
    GEMINI_RESPONSE_SCHEMA,
    ExtractionAdapter,
    GeminiExtractionAdapter,
    NvidiaExtractionAdapter,
    ProviderExtractionRequest,
    ProviderRawResponse,
    ProviderRequestError,
    TokenUsage,
    create_adapter,
    parse_token_usage,
)
from ai_extraction.schema import (
    CSV_COLUMNS,
    EXTRACTION_FIELDS,
    parse_and_validate_model_json,
    resolve_conflict_group,
)


def _build_minimal_two_page_pdf() -> bytes:
    """Create a valid minimal 2-page PDF byte stream using pure stdlib Python."""
    stream1 = b"BT /F1 12 Tf 20 150 Td (Page 1 Schedule) Tj ET"
    stream2 = b"BT /F1 12 Tf 20 150 Td (Page 2 Longer Text) Tj ET"
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>\nendobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(stream1)} >>\nstream\n".encode("ascii")
            + stream1
            + b"\nendstream\nendobj\n"
        ),
        (
            b"5 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>\nendobj\n"
        ),
        (
            f"6 0 obj\n<< /Length {len(stream2)} >>\nstream\n".encode("ascii")
            + stream2
            + b"\nendstream\nendobj\n"
        ),
        b"7 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


class SchemaAndNormalisationTests(unittest.TestCase):
    def test_shared_schema_columns_match_compare_extraction(self) -> None:
        self.assertEqual(
            CSV_COLUMNS,
            ("file_name",) + EXTRACTION_FIELDS,
        )
        self.assertEqual(len(EXTRACTION_FIELDS), 10)

    def test_malformed_json_and_reasoning_wrapper_handling(self) -> None:
        truncated = '{"week_of": "2026-11-02", "shifts": [{"shift_date": "2026-11-03"'
        res_bad = parse_and_validate_model_json(
            truncated, file_name="bad.png", model_id=DEFAULT_NVIDIA_MODEL
        )
        self.assertTrue(res_bad.json_validation_failure)
        self.assertTrue(res_bad.json_validation_errors)

        prose_only = "Unable to parse document because image is blurry."
        res_prose = parse_and_validate_model_json(
            prose_only, file_name="prose.png", model_id=DEFAULT_NVIDIA_MODEL
        )
        self.assertTrue(res_prose.json_validation_failure)

        bad_item = json.dumps({"week_of": None, "shifts": ["not-an-object"]})
        res_item = parse_and_validate_model_json(
            bad_item, file_name="item.png", model_id=DEFAULT_NVIDIA_MODEL
        )
        self.assertTrue(res_item.json_validation_failure)

        wrapped = (
            "<think>Let me inspect the schedule carefully.</think>\n"
            "```json\n"
            + json.dumps(
                {
                    "week_of": "Week of 2 November 2026",
                    "shifts": [
                        {
                            "shift_date": "2026-11-02",
                            "start_time": "09:00",
                            "end_time": "17:00",
                            "break_minutes": 30,
                            "employer_name": "BrightMart",
                            "location": "Store A",
                            "department": "checkout",
                            "hourly_rate": 16,
                            "currency": "usd",
                            "shift_status": "scheduled",
                            "confidence": "high",
                            "uncertain_fields": [],
                        }
                    ],
                }
            )
            + "\n```"
        )
        res_ok = parse_and_validate_model_json(
            wrapped, file_name="clean.png", model_id=DEFAULT_NVIDIA_MODEL
        )
        self.assertFalse(res_ok.json_validation_failure)
        self.assertEqual(len(res_ok.shifts), 1)
        shift = res_ok.shifts[0]
        self.assertEqual(shift.normalised.hourly_rate, "16.00")
        self.assertEqual(shift.normalised.currency, "USD")
        self.assertEqual(shift.normalised.break_minutes, "30")
        self.assertTrue(shift.requires_worker_confirmation)
        self.assertEqual(shift.confirmation_status, "needs_review")
        self.assertTrue(shift.requires_individual_review)
        self.assertFalse(shift.eligible_for_bulk_confirmation)
        # Raw values retained separately from normalised values
        self.assertEqual(shift.raw_values["currency"], "usd")
        self.assertEqual(shift.raw_values["hourly_rate"], 16)

    def test_missing_fields_are_never_invented_and_trigger_review(self) -> None:
        raw_json = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {
                        "shift_date": "2026-11-17",
                        "start_time": "08:00",
                        "end_time": "16:00",
                        "break_minutes": None,
                        "employer_name": "Metro Logistics",
                        "location": "-",
                        "department": "dispatch",
                        "hourly_rate": "18.00",
                        "currency": None,
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "shift_date": "2026-11-20",
                        "start_time": "08:00",
                        "end_time": "TBC",
                        "break_minutes": "N/A",
                        "employer_name": "Metro Logistics",
                        "location": "Unknown",
                        "department": "dispatch",
                        "hourly_rate": "-",
                        "currency": None,
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            raw_json,
            file_name="pdf_07_missing_details.pdf",
            model_id=DEFAULT_NVIDIA_MODEL,
        )
        self.assertFalse(parsed.json_validation_failure)
        s0, s1 = parsed.shifts

        # Missing break must stay None ("" in CSV), NEVER 0; missing currency stays None
        self.assertIsNone(s0.normalised.break_minutes)
        self.assertIsNone(s0.normalised.location)
        self.assertIsNone(s0.normalised.currency)
        self.assertEqual(s0.normalised.hourly_rate, "18.00")
        csv_row0 = s0.to_compare_csv_row("pdf_07_missing_details.pdf")
        self.assertEqual(csv_row0["break_minutes"], "")
        self.assertEqual(csv_row0["currency"], "")
        self.assertEqual(s0.confirmation_status, "needs_review")
        self.assertTrue(s0.requires_individual_review)
        self.assertFalse(s0.eligible_for_bulk_confirmation)

        self.assertIsNone(s1.normalised.end_time)
        self.assertIsNone(s1.normalised.break_minutes)
        self.assertIsNone(s1.normalised.hourly_rate)
        self.assertIsNone(s1.normalised.location)

    def test_explicit_zero_break_is_preserved_distinct_from_missing(self) -> None:
        raw_json = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {
                        "shift_date": "2026-11-17",
                        "start_time": "07:00",
                        "end_time": "15:00",
                        "break_minutes": None,
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": 14.25,
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "shift_date": "2026-11-20",
                        "start_time": "13:00",
                        "end_time": "21:00",
                        "break_minutes": 0,
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": "£14.25/h",
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "shift_date": "2026-11-21",
                        "start_time": "13:00",
                        "end_time": "21:00",
                        "break_minutes": "no break",
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": 14.25,
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            raw_json,
            file_name="img_07_photo_missing_details.jpg",
            model_id=DEFAULT_NVIDIA_MODEL,
        )
        missing_row, zero_num_row, no_break_row = parsed.shifts
        self.assertIsNone(missing_row.normalised.break_minutes)
        self.assertEqual(missing_row.to_compare_csv_row("x")["break_minutes"], "")

        self.assertEqual(zero_num_row.normalised.break_minutes, "0")
        self.assertEqual(zero_num_row.normalised.hourly_rate, "14.25")
        self.assertEqual(zero_num_row.to_compare_csv_row("x")["break_minutes"], "0")
        self.assertEqual(zero_num_row.confirmation_status, "needs_review")
        self.assertFalse(zero_num_row.eligible_for_bulk_confirmation)

        self.assertEqual(no_break_row.normalised.break_minutes, "0")

    def test_overnight_shifts_12h_times_year_heading_and_status_values(self) -> None:
        raw_json = json.dumps(
            {
                "week_of": "Week of 2 November 2026",
                "shifts": [
                    {
                        "shift_date": "Tue 3 Nov",
                        "start_time": "10:00 PM",
                        "end_time": "6:00 AM",
                        "break_minutes": "60 minutes",
                        "employer_name": "Swift Logistics",
                        "location": "Night Warehouse",
                        "department": "dispatch",
                        "hourly_rate": 17,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "shift_date": "2026-11-04",
                        "start_time": "7:00am",
                        "end_time": "12:10pm",
                        "break_minutes": "0 min",
                        "employer_name": "CityCare Hospital",
                        "location": "Hospital Annex",
                        "department": "patient support",
                        "hourly_rate": "15.00 USD",
                        "currency": "USD",
                        "shift_status": "CANCELLED",
                        "confidence": "high",
                    },
                    {
                        "shift_date": "2026-11-05",
                        "start_time": "10am",
                        "end_time": "6pm",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Main",
                        "department": "service",
                        "hourly_rate": 15.5,
                        "currency": "USD",
                        "shift_status": "changed",
                        "confidence": "medium",
                        "uncertain_fields": ["end_time"],
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            raw_json,
            file_name="pdf_03_sentences_12h.pdf",
            model_id=DEFAULT_NVIDIA_MODEL,
        )
        overnight, cancelled, changed = parsed.shifts
        self.assertEqual(overnight.normalised.shift_date, "2026-11-03")
        self.assertEqual(overnight.normalised.start_time, "22:00")
        self.assertEqual(overnight.normalised.end_time, "06:00")
        self.assertEqual(overnight.normalised.break_minutes, "60")

        self.assertEqual(cancelled.normalised.start_time, "07:00")
        self.assertEqual(cancelled.normalised.end_time, "12:10")
        self.assertEqual(cancelled.normalised.shift_status, "cancelled")
        self.assertEqual(cancelled.confirmation_status, "needs_review")
        self.assertFalse(cancelled.eligible_for_bulk_confirmation)

        self.assertEqual(changed.normalised.start_time, "10:00")
        self.assertEqual(changed.normalised.end_time, "18:00")
        self.assertEqual(changed.normalised.shift_status, "changed")
        self.assertEqual(changed.confirmation_status, "needs_review")
        self.assertTrue(changed.requires_individual_review)
        self.assertFalse(changed.eligible_for_bulk_confirmation)
        self.assertIn("end_time", changed.uncertain_fields)

    def test_multi_employee_roster_filters_non_target_workers(self) -> None:
        prompt = build_user_prompt(target_worker="Maria Santos", page_count=1)
        self.assertIn("Maria Santos", prompt)
        self.assertIn("Extract all visible shifts", prompt)
        self.assertIn("do not filter out unidentified shifts", prompt)
        self.assertNotIn("TARGET WORKER FILTER", prompt)

        noisy_model_json = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {
                        "worker_name": "Maria Santos",
                        "shift_date": "2026-11-16",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "kitchen",
                        "hourly_rate": 16.50,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "worker_name": "James Okoro",
                        "shift_date": "2026-11-17",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "bar",
                        "hourly_rate": 15.00,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "employee_name": "Tom Becker",
                        "shift_date": "2026-11-17",
                        "start_time": "16:00",
                        "end_time": "23:00",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "floor",
                        "hourly_rate": 14.00,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            noisy_model_json,
            file_name="pdf_06_team_roster_multi_employee.pdf",
            model_id=DEFAULT_NVIDIA_MODEL,
            target_worker="Maria Santos",
        )
        self.assertEqual(parsed.filtered_other_worker_shifts, 2)
        self.assertEqual(len(parsed.shifts), 1)
        self.assertEqual(parsed.shifts[0].normalised.shift_date, "2026-11-16")


class PdfAndImageUtilsTests(unittest.TestCase):
    def test_load_real_pdf_and_image_samples(self) -> None:
        pdf_pages = load_document_pages(
            UNSTRUCTURED_DIR / "pdf" / "pdf_01_table_clean.pdf"
        )
        self.assertEqual(len(pdf_pages), 1)
        self.assertEqual(pdf_pages[0].mime_type, "image/png")
        self.assertTrue(pdf_pages[0].image_bytes.startswith(b"\x89PNG"))
        self.assertTrue(pdf_pages[0].data_url.startswith("data:image/png;base64,"))

        img_pages = load_document_pages(
            UNSTRUCTURED_DIR / "images" / "img_02_photo_tilted.jpg"
        )
        self.assertEqual(len(img_pages), 1)
        self.assertEqual(img_pages[0].mime_type, "image/jpeg")
        self.assertTrue(img_pages[0].data_url.startswith("data:image/jpeg;base64,"))

    def test_multipage_pdf_renders_every_page_as_separate_image_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "multipage.pdf"
            pdf_path.write_bytes(_build_minimal_two_page_pdf())

            rendered = render_pdf_to_png_pages(pdf_path, dpi=150)
            self.assertEqual(len(rendered), 2)
            self.assertTrue(all(p.startswith(b"\x89PNG") for p in rendered))
            self.assertNotEqual(rendered[0], rendered[1])

            pages = load_document_pages(pdf_path, dpi=150)
            self.assertEqual(len(pages), 2)
            self.assertEqual([p.page_number for p in pages], [1, 2])
            self.assertEqual([p.total_pages for p in pages], [2, 2])

            adapter = NvidiaExtractionAdapter(api_key="dummy-key")
            payload = adapter.build_payload(
                ProviderExtractionRequest(
                    file_name="multipage.pdf",
                    pages=tuple(pages),
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=build_user_prompt(page_count=2),
                )
            )
            content_blocks = payload["messages"][1]["content"]
            image_blocks = [b for b in content_blocks if b["type"] == "image_url"]
            self.assertEqual(len(image_blocks), 2)
            self.assertEqual(content_blocks[-1]["type"], "text")
            self.assertIn("2 document page(s)", content_blocks[-1]["text"])

    def test_all_14_documents_render_and_preprocess_with_pypdfium2_and_pillow_without_macos_backends(
        self,
    ) -> None:
        manifest = load_files_manifest(DEFAULT_FILES_CSV)
        self.assertEqual(len(manifest), 14)

        with (
            patch("ai_extraction.pdf_utils._render_pdf_with_coregraphics", return_value=None),
            patch("ai_extraction.pdf_utils._render_pdf_with_pdftoppm", return_value=None),
            patch("ai_extraction.pdf_utils._render_pdf_with_pymupdf", return_value=None),
            patch("ai_extraction.pdf_utils._decode_image_with_coregraphics", return_value=None),
            patch("ai_extraction.pdf_utils._rotate_rgba_expanded_coregraphics", return_value=None),
        ):
            for entry in manifest:
                raw_pages = load_document_pages(
                    entry.document_path, preprocess_images=False
                )
                self.assertEqual(len(raw_pages), 1, entry.file_name)
                if entry.kind == "pdf":
                    self.assertEqual(raw_pages[0].rendering_backend, "pypdfium2")
                    self.assertEqual(raw_pages[0].mime_type, "image/png")
                    self.assertTrue(raw_pages[0].image_bytes.startswith(b"\x89PNG"))
                else:
                    self.assertEqual(raw_pages[0].rendering_backend, "direct_image")

                pre_pages = load_document_pages(
                    entry.document_path, preprocess_images=True
                )
                self.assertEqual(len(pre_pages), 1, entry.file_name)
                diag = pre_pages[0].preprocessing_diagnostics
                self.assertIsNotNone(diag)
                self.assertEqual(diag.backend_used, "pillow")
                self.assertGreater(diag.output_width, 0)
                self.assertGreater(diag.output_height, 0)

    def test_missing_rendering_dependencies_raise_actionable_error_instead_of_silent_skip(
        self,
    ) -> None:
        sample_pdf = UNSTRUCTURED_DIR / "pdf" / "pdf_01_table_clean.pdf"
        sample_jpg = UNSTRUCTURED_DIR / "images" / "img_07_photo_missing_details.jpg"

        with (
            patch.dict(
                sys.modules,
                {"pypdfium2": None, "fitz": None, "PIL": None, "PIL.Image": None},
            ),
            patch("ai_extraction.pdf_utils.shutil.which", return_value=None),
            patch("ai_extraction.pdf_utils.ctypes.util.find_library", return_value=None),
        ):
            self.assertIsNone(get_available_pdf_rendering_backend())
            self.assertIsNone(get_available_image_preprocessing_backend("image/jpeg"))
            self.assertEqual(
                get_available_image_preprocessing_backend("image/png"),
                "pure_python_png",
            )

            with self.assertRaises(MissingRenderingDependencyError) as ctx_pdf:
                render_pdf_to_png_pages_with_backend(sample_pdf)
            self.assertIn("pip install -r requirements.txt", str(ctx_pdf.exception))

            with self.assertRaises(MissingRenderingDependencyError):
                load_document_pages(sample_pdf)

            with self.assertRaises(MissingRenderingDependencyError) as ctx_jpg:
                inspect_and_preprocess_image(
                    sample_jpg.read_bytes(), mime_type="image/jpeg"
                )
            self.assertIn("pip install Pillow", str(ctx_jpg.exception))

            with self.assertRaises(MissingRenderingDependencyError):
                ensure_rendering_dependencies(load_files_manifest(DEFAULT_FILES_CSV))

            mock_adapter = NvidiaExtractionAdapter(api_key="test")
            with self.assertRaises(MissingRenderingDependencyError):
                extract_single_document(
                    file_path=sample_pdf,
                    file_name=sample_pdf.name,
                    adapter=mock_adapter,
                )

            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(MissingRenderingDependencyError) as ctx_bench:
                    run_benchmark(mock_adapter, output_dir=Path(tmp))
                self.assertIn("pypdfium2 Pillow", str(ctx_bench.exception))


class ProviderAdaptersAndFailureTests(unittest.TestCase):
    def test_nvidia_adapter_payload_and_response_parsing(self) -> None:
        captured: dict[str, Any] = {}

        def fake_sender(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> dict[str, Any]:
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            captured["timeout"] = timeout
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"week_of": "2026-11-02", "shifts": []}),
                            "reasoning_content": "No shifts detected in mock.",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 704,
                    "total_tokens": 1904,
                },
            }

        adapter = NvidiaExtractionAdapter(
            api_key="nvapi-mock-key-123",
            http_sender=fake_sender,
        )
        pages = load_document_pages(
            UNSTRUCTURED_DIR / "images" / "img_01_screenshot_clean.png"
        )
        raw = adapter.extract(
            ProviderExtractionRequest(
                file_name="img_01_screenshot_clean.png",
                pages=tuple(pages),
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(),
            )
        )
        self.assertEqual(captured["url"], DEFAULT_NVIDIA_ENDPOINT)
        self.assertEqual(captured["payload"]["model"], DEFAULT_NVIDIA_MODEL)
        self.assertEqual(raw.token_usage.total_tokens, 1904)
        self.assertEqual(raw.reasoning_text, "No shifts detected in mock.")
        self.assertNotIn("nvapi-mock-key-123", repr(adapter))

    def test_gemini_adapter_implements_provider_interface(self) -> None:
        captured: dict[str, Any] = {}

        def fake_gemini_sender(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> dict[str, Any]:
            captured["url"] = url
            captured["payload"] = payload
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {"week_of": "2026-11-02", "shifts": []}
                                    )
                                }
                            ]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 500,
                    "candidatesTokenCount": 120,
                    "totalTokenCount": 620,
                },
            }

        adapter = create_adapter("gemini", http_sender=fake_gemini_sender)
        self.assertIsInstance(adapter, GeminiExtractionAdapter)
        pages = load_document_pages(
            UNSTRUCTURED_DIR / "images" / "img_01_screenshot_clean.png"
        )
        raw = adapter.extract(
            ProviderExtractionRequest(
                file_name="img_01_screenshot_clean.png",
                pages=tuple(pages),
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(),
            )
        )
        self.assertEqual(raw.provider_name, "gemini")
        self.assertEqual(raw.token_usage.total_tokens, 620)
        self.assertIn("inlineData", captured["payload"]["contents"][0]["parts"][0])

    def test_api_failures_do_not_crash_and_never_leak_api_keys(self) -> None:
        fake_secret = "nvapi-SUPER-SECRET-TOKEN-DO-NOT-LEAK"

        def failing_urlopen(req, timeout=120):
            raise urllib.error.HTTPError(
                req.full_url,
                401,
                f"Unauthorized token {fake_secret}",
                hdrs=None,
                fp=io.BytesIO(f"Invalid Bearer {fake_secret}".encode("utf-8")),
            )

        with patch.dict(os.environ, {"NVIDIA_API_KEY": fake_secret}, clear=False), patch(
            "urllib.request.urlopen", side_effect=failing_urlopen
        ):
            adapter = NvidiaExtractionAdapter()
            with tempfile.TemporaryDirectory() as tmp:
                result = run_benchmark(
                    adapter,
                    output_dir=Path(tmp),
                    only_files=["img_01_screenshot_clean.png"],
                )
                self.assertEqual(result.request_failures, 1)
                self.assertTrue(result.document_results[0].request_failure)
                err = result.document_results[0].request_error or ""
                self.assertIn("HTTP 401", err)
                self.assertIn("[REDACTED]", err)
                self.assertNotIn(fake_secret, err)
                results_json = result.results_json_path.read_text(encoding="utf-8")
                self.assertNotIn(fake_secret, results_json)


class BenchmarkPipelineIntegrationTests(unittest.TestCase):
    def test_full_14_document_benchmark_isolates_answer_key_and_scores_with_compare_tool(
        self,
    ) -> None:
        # Prepare mock model responses independently in test setup so answer_key.csv
        # is never touched by the extraction code path.
        expected_by_file: dict[str, list[dict[str, str]]] = {}
        with DEFAULT_ANSWER_KEY_CSV.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                expected_by_file.setdefault(row["file_name"], []).append(row)

        self.assertEqual(len(load_files_manifest(DEFAULT_FILES_CSV)), 14)

        mock_responses_by_file: dict[str, str] = {}
        for file_name, rows in expected_by_file.items():
            shifts_payload = []
            for r in rows:
                shifts_payload.append(
                    {
                        "shift_date": r["shift_date"],
                        "start_time": r["start_time"],
                        "end_time": r["end_time"] or None,
                        "break_minutes": (
                            int(r["break_minutes"])
                            if r["break_minutes"] != ""
                            else None
                        ),
                        "employer_name": r["employer_name"] or None,
                        "location": r["location"] or None,
                        "department": r["department"] or None,
                        "hourly_rate": (
                            float(r["hourly_rate"]) if r["hourly_rate"] != "" else None
                        ),
                        "currency": r["currency"] or None,
                        "shift_status": r["shift_status"],
                        "confidence": "high",
                        "uncertain_fields": [],
                    }
                )
            # For multi-employee roster, also inject a non-target colleague shift
            # to verify the schema filter excludes colleagues cleanly.
            if file_name == "pdf_06_team_roster_multi_employee.pdf":
                for s in shifts_payload:
                    s["worker_name"] = "Maria Santos"
                shifts_payload.append(
                    {
                        "worker_name": "James Okoro",
                        "shift_date": "2026-11-17",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "bar",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    }
                )
            mock_responses_by_file[file_name] = json.dumps(
                {"week_of": "2026-11", "shifts": shifts_payload}
            )

        observed_requests: list[ProviderExtractionRequest] = []

        class MockNvidiaAdapter(ExtractionAdapter):
            @property
            def provider_name(self) -> str:
                return "nvidia"

            @property
            def model_id(self) -> str:
                return DEFAULT_NVIDIA_MODEL

            def extract(
                self, request: ProviderExtractionRequest
            ) -> ProviderRawResponse:
                # Verify extractor never passes answer_key paths or answer counts in prompts
                observed_requests.append(request)
                assert "answer_key" not in request.user_prompt
                assert "answer_key" not in request.system_prompt
                return ProviderRawResponse(
                    provider_name=self.provider_name,
                    model_id=self.model_id,
                    raw_text=mock_responses_by_file[request.file_name],
                    elapsed_seconds=0.25,
                    token_usage=TokenUsage(
                        prompt_tokens=1000, completion_tokens=300, total_tokens=1300
                    ),
                )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            result = run_benchmark(MockNvidiaAdapter(), output_dir=out_dir)

            self.assertEqual(len(observed_requests), 14)
            self.assertEqual(result.documents_evaluated, 14)
            self.assertEqual(result.request_failures, 0)
            self.assertEqual(result.json_validation_failures, 0)
            self.assertEqual(result.extracted_shift_count, 62)
            self.assertEqual(result.total_tokens, 14 * 1300)

            summary = result.comparison_summary
            self.assertEqual(summary["expected"], 62)
            self.assertEqual(summary["matched"], 62)
            self.assertEqual(summary["missed"], 0)
            self.assertEqual(summary["invented"], 0)
            self.assertEqual(summary["made_up_details"], 0)
            self.assertEqual(summary["dropped_details"], 0)
            self.assertEqual(summary["all_ok"], 62)
            self.assertEqual(summary["money_ok"], 62)

            self.assertTrue(result.extracted_csv_path.is_file())
            self.assertTrue(result.review_queue_csv_path.is_file())
            self.assertTrue(result.differences_csv_path.is_file())
            self.assertTrue(result.comparison_report_path.is_file())
            self.assertTrue(result.per_document_csv_path.is_file())
            self.assertTrue(result.results_json_path.is_file())

            with result.extracted_csv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.assertEqual(tuple(reader.fieldnames or ()), CSV_COLUMNS)
                rows = list(reader)
                self.assertEqual(len(rows), 62)

            # Verify every single extracted shift requires worker confirmation,
            # and incomplete/cancelled/changed shifts are flagged for individual review.
            with result.review_queue_csv_path.open(newline="", encoding="utf-8") as f:
                queue_rows = list(csv.DictReader(f))
                self.assertEqual(len(queue_rows), 62)
                self.assertTrue(
                    all(r["requires_worker_confirmation"] == "true" for r in queue_rows)
                )
                self.assertTrue(
                    all(r["confirmation_status"] == "needs_review" for r in queue_rows)
                )
                self.assertTrue(
                    all(r["requires_individual_review"] == "true" for r in queue_rows)
                )
                self.assertTrue(
                    all(r["eligible_for_bulk_confirmation"] == "false" for r in queue_rows)
                )
                miss01 = [r for r in queue_rows if r["file_name"] == "pdf_07_missing_details.pdf"]
                # Shifts 2..6 in MISS01 have missing break/rate/currency/end_time/location (shifts 2..5 have missing money fields -> needs_review)
                self.assertTrue(
                    all(r["confirmation_status"] == "needs_review" for r in miss01[1:5])
                )
                self.assertTrue(
                    all(r["eligible_for_bulk_confirmation"] == "false" for r in miss01[1:5])
                )

    def test_extract_single_document_never_opens_answer_key(self) -> None:
        mock_adapter = NvidiaExtractionAdapter(
            api_key="test",
            http_sender=lambda *_args: {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"week_of": None, "shifts": []})
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
        orig_open = Path.open

        def guarded_open(self_path: Path, *args: Any, **kwargs: Any):
            if self_path.name == "answer_key.csv":
                raise AssertionError("Extractor attempted to read answer_key.csv!")
            return orig_open(self_path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            extract_single_document(
                file_path=UNSTRUCTURED_DIR / "pdf" / "pdf_01_table_clean.pdf",
                file_name="pdf_01_table_clean.pdf",
                adapter=mock_adapter,
            )

    def test_benchmark_records_json_validation_failure_cleanly(self) -> None:
        bad_json_adapter = NvidiaExtractionAdapter(
            api_key="test",
            http_sender=lambda *_args: {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [{"message": {"content": "{not valid json"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62},
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_benchmark(
                bad_json_adapter,
                output_dir=Path(tmp),
                only_files=["pdf_01_table_clean.pdf"],
            )
            self.assertEqual(result.request_failures, 0)
            self.assertEqual(result.json_validation_failures, 1)
            self.assertEqual(result.extracted_shift_count, 0)
            # Primary subset report scores ONLY selected document(s); full dataset saved separately.
            self.assertEqual(result.comparison_summary["expected"], 3)
            self.assertEqual(result.comparison_summary["missed"], 3)
            self.assertIsNotNone(result.full_dataset_comparison_summary)
            self.assertEqual(result.full_dataset_comparison_summary["expected"], 62)
            self.assertIsNotNone(result.full_dataset_report_path)
            self.assertIn(
                "LIMITATION NOTE",
                result.full_dataset_report_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(result.document_results[0].raw_response, "{not valid json")
            self.assertTrue(result.document_results[0].json_validation_failure)

    def test_all_14_documents_reach_mock_provider_when_native_macos_backends_unavailable(
        self,
    ) -> None:
        observed_requests: list[ProviderExtractionRequest] = []

        class MockProviderAdapter(ExtractionAdapter):
            @property
            def provider_name(self) -> str:
                return "nvidia"

            @property
            def model_id(self) -> str:
                return DEFAULT_NVIDIA_MODEL

            def extract(
                self, request: ProviderExtractionRequest
            ) -> ProviderRawResponse:
                observed_requests.append(request)
                return ProviderRawResponse(
                    provider_name=self.provider_name,
                    model_id=self.model_id,
                    raw_text=json.dumps({"week_of": "Week of 2 November 2026", "shifts": []}),
                    finish_reason="stop",
                    elapsed_seconds=0.05,
                    token_usage=TokenUsage(
                        prompt_tokens=100, completion_tokens=20, total_tokens=120
                    ),
                )

        with (
            patch("ai_extraction.pdf_utils._render_pdf_with_coregraphics", return_value=None),
            patch("ai_extraction.pdf_utils._render_pdf_with_pdftoppm", return_value=None),
            patch("ai_extraction.pdf_utils._render_pdf_with_pymupdf", return_value=None),
            patch("ai_extraction.pdf_utils._decode_image_with_coregraphics", return_value=None),
            patch("ai_extraction.pdf_utils._rotate_rgba_expanded_coregraphics", return_value=None),
            tempfile.TemporaryDirectory() as tmp,
        ):
            res = run_benchmark(
                MockProviderAdapter(),
                output_dir=Path(tmp),
                preprocess_images=True,
            )

            self.assertEqual(res.documents_evaluated, 14)
            self.assertEqual(res.request_failures, 0)
            self.assertEqual(res.json_validation_failures, 0)
            self.assertEqual(len(observed_requests), 14)
            pdf_reqs = [r for r in observed_requests if r.file_name.endswith(".pdf")]
            img_reqs = [r for r in observed_requests if not r.file_name.endswith(".pdf")]
            self.assertEqual(len(pdf_reqs), 7)
            self.assertEqual(len(img_reqs), 7)
            self.assertTrue(
                all(r.pages[0].rendering_backend == "pypdfium2" for r in pdf_reqs)
            )
            self.assertTrue(
                all(
                    r.pages[0].preprocessing_diagnostics is not None
                    and r.pages[0].preprocessing_diagnostics.backend_used == "pillow"
                    for r in observed_requests
                )
            )


class V2CorrectiveRegressionTests(unittest.TestCase):
    def test_v2_nvidia_defaults_and_payload_parameters(self) -> None:
        self.assertEqual(DEFAULT_NVIDIA_MAX_TOKENS, 8192)
        self.assertEqual(DEFAULT_NVIDIA_REASONING_BUDGET, 2048)
        self.assertAlmostEqual(DEFAULT_NVIDIA_TEMPERATURE, 0.2)
        self.assertEqual(DEFAULT_NVIDIA_MAX_RETRIES, 2)

        adapter = NvidiaExtractionAdapter(api_key="dummy")
        pages = load_document_pages(
            UNSTRUCTURED_DIR / "images" / "img_01_screenshot_clean.png"
        )
        payload = adapter.build_payload(
            ProviderExtractionRequest(
                file_name="img_01_screenshot_clean.png",
                pages=tuple(pages),
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(),
            )
        )
        self.assertEqual(payload["max_tokens"], 8192)
        self.assertEqual(payload["reasoning_budget"], 2048)
        self.assertAlmostEqual(payload["temperature"], 0.2)
        # Only verified OpenAI/NVIDIA parameters included
        self.assertEqual(
            set(payload.keys()),
            {"model", "messages", "temperature", "max_tokens", "reasoning_budget"},
        )

    def test_v2_finish_reason_and_reasoning_token_breakdown_captured(self) -> None:
        adapter = NvidiaExtractionAdapter(
            api_key="dummy",
            http_sender=lambda *_args: {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": ""},
                    }
                ],
                "usage": {
                    "prompt_tokens": 1600,
                    "completion_tokens": 4096,
                    "completion_tokens_details": {"reasoning_tokens": 2048},
                    "total_tokens": 5696,
                },
            },
        )
        pages = load_document_pages(
            UNSTRUCTURED_DIR / "images" / "img_01_screenshot_clean.png"
        )
        raw = adapter.extract(
            ProviderExtractionRequest(
                file_name="img_01_screenshot_clean.png",
                pages=tuple(pages),
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(),
            )
        )
        self.assertEqual(raw.finish_reason, "length")
        self.assertEqual(raw.token_usage.reasoning_tokens, 2048)
        self.assertEqual(raw.token_usage.output_tokens, 2048)
        self.assertEqual(raw.token_usage.total_tokens, 5696)

    def test_partial_json_recovery_recovers_only_closed_objects_and_rejects_incomplete(
        self,
    ) -> None:
        truncated_json = (
            '{\n  "week_of": "Week of 9 November 2026",\n  "shifts": [\n'
            '    {"shift_date": "2026-11-09", "start_time": "08:00", "end_time": "16:00", '
            '"break_minutes": 30, "employer_name": "Grand Hotel", "location": "Hotel Front", '
            '"department": "front desk", "hourly_rate": 18.0, "currency": "USD", '
            '"shift_status": "scheduled", "confidence": "high", "source_page": 1, "source_row": 1},\n'
            '    {"shift_date": "2026-11-10", "start_time": "08:00", "end_time": "16:00", '
            '"break_minutes": 30, "employer_name": "Grand Hotel", "location": "Hotel Front", '
            '"department": "front desk", "hourly_rate": 18.0, "currency": "USD", '
            '"shift_status": "scheduled", "confidence": "high", "source_page": 1, "source_row": 2},\n'
            '    {"shift_date": "2026-11-15", "start_time": "22:00", "end_time": "06'
        )
        parsed = parse_and_validate_model_json(
            truncated_json,
            file_name="img_05_cropped_perspective.jpg",
            model_id=DEFAULT_NVIDIA_MODEL,
            finish_reason="length",
        )
        self.assertTrue(parsed.json_validation_failure)
        self.assertTrue(parsed.incomplete_extraction)
        self.assertTrue(parsed.partial_recovery_triggered)
        self.assertEqual(parsed.partially_recovered_shift_count, 2)
        self.assertEqual(len(parsed.shifts), 2)
        for s in parsed.shifts:
            self.assertTrue(s.partially_recovered)
            self.assertEqual(s.confidence, "low")
            self.assertEqual(s.confirmation_status, "needs_review")
            self.assertTrue(s.requires_individual_review)
            self.assertFalse(s.eligible_for_bulk_confirmation)
            self.assertIn("partial_json_recovery", s.review_reasons)
        self.assertEqual(parsed.shifts[0].source_page, 1)
        self.assertEqual(parsed.shifts[0].source_row, 1)

        # Without truncation evidence (stop + malformed non-truncated syntax), do NOT partially recover
        non_truncated_corrupt = (
            '{"shifts": [{"shift_date": "2026-11-09", "start_time": "08:00", '
            '"end_time": "16:00", "shift_status": "scheduled"}, BROKEN_TAIL]}'
        )
        parsed_corrupt = parse_and_validate_model_json(
            non_truncated_corrupt,
            file_name="corrupt.png",
            model_id=DEFAULT_NVIDIA_MODEL,
            finish_reason="stop",
        )
        self.assertTrue(parsed_corrupt.json_validation_failure)
        self.assertFalse(parsed_corrupt.partial_recovery_triggered)
        self.assertEqual(len(parsed_corrupt.shifts), 0)

    def test_empty_response_due_to_reasoning_exhaustion_never_mines_reasoning_text(
        self,
    ) -> None:
        class ReasoningExhaustionAdapter(ExtractionAdapter):
            @property
            def provider_name(self) -> str:
                return "nvidia"

            @property
            def model_id(self) -> str:
                return DEFAULT_NVIDIA_MODEL

            def extract(
                self, request: ProviderExtractionRequest
            ) -> ProviderRawResponse:
                return ProviderRawResponse(
                    provider_name="nvidia",
                    model_id=DEFAULT_NVIDIA_MODEL,
                    raw_text="",
                    finish_reason="length",
                    reasoning_text=(
                        '{"week_of": "Week of 16 November 2026", "shifts": ['
                        '{"shift_date": "2026-11-16", "start_time": "09:00", "end_time": "17:00", '
                        '"break_minutes": 30, "employer_name": "Harbor Bistro", "hourly_rate": 16.5, '
                        '"currency": "USD", "shift_status": "scheduled"}]}'
                    ),
                    elapsed_seconds=1.1,
                    token_usage=TokenUsage(
                        prompt_tokens=4000,
                        completion_tokens=4096,
                        reasoning_tokens=4096,
                        output_tokens=0,
                        total_tokens=8096,
                    ),
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = run_benchmark(
                ReasoningExhaustionAdapter(),
                output_dir=Path(tmp),
                only_files=["pdf_06_team_roster_multi_employee.pdf"],
                backoff_seconds=0.0,
            )
            doc = result.document_results[0]
            self.assertEqual(doc.extracted_shift_count, 0)
            self.assertTrue(doc.json_validation_failure)
            self.assertTrue(doc.incomplete_extraction)
            self.assertFalse(doc.partial_recovery_triggered)
            # 1 initial + 2 retries = 3 attempts; all tokens & latency summed
            self.assertEqual(doc.request_attempts, 3)
            self.assertEqual(doc.token_usage["total_tokens"], 3 * 8096)
            self.assertEqual(doc.token_usage["reasoning_tokens"], 3 * 4096)

    def test_retry_limits_backoff_token_accounting_and_no_duplicates_across_retries(
        self,
    ) -> None:
        calls = {"count": 0}
        sleeps: list[float] = []

        truncated_payload = (
            '{\n  "week_of": "Week of 2 November 2026",\n  "shifts": [\n'
            '    {"shift_date": "2026-11-03", "start_time": "08:00", "end_time": "16:00", '
            '"break_minutes": 0, "employer_name": "BrightMart", "location": "Store A", '
            '"department": "sales floor", "hourly_rate": 15.0, "currency": "USD", "shift_status": "scheduled"},\n'
            '    {"shift_date": "2026-11-04", "start_time": "09:00'
        )
        complete_payload = json.dumps(
            {
                "week_of": "Week of 2 November 2026",
                "shifts": [
                    {
                        "shift_date": "2026-11-03",
                        "start_time": "08:00",
                        "end_time": "16:00",
                        "break_minutes": 0,
                        "employer_name": "BrightMart",
                        "location": "Store A",
                        "department": "sales floor",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "shift_date": "2026-11-04",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 0,
                        "employer_name": "BrightMart",
                        "location": "Store A",
                        "department": "sales floor",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "shift_date": "2026-11-05",
                        "start_time": "22:00",
                        "end_time": "06:00",
                        "break_minutes": 0,
                        "employer_name": "SwiftLogistics",
                        "location": "Warehouse B",
                        "department": "dispatch",
                        "hourly_rate": 18.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                ],
            }
        )

        class RetryScenarioAdapter(ExtractionAdapter):
            @property
            def provider_name(self) -> str:
                return "nvidia"

            @property
            def model_id(self) -> str:
                return DEFAULT_NVIDIA_MODEL

            def extract(
                self, request: ProviderExtractionRequest
            ) -> ProviderRawResponse:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise ProviderRequestError(
                        "HTTP 503 Service Unavailable", status_code=503, is_transient=True
                    )
                if calls["count"] == 2:
                    return ProviderRawResponse(
                        provider_name="nvidia",
                        model_id=DEFAULT_NVIDIA_MODEL,
                        raw_text=truncated_payload,
                        finish_reason="length",
                        elapsed_seconds=0.5,
                        token_usage=TokenUsage(
                            prompt_tokens=1000,
                            completion_tokens=800,
                            reasoning_tokens=500,
                            output_tokens=300,
                            total_tokens=1800,
                        ),
                    )
                return ProviderRawResponse(
                    provider_name="nvidia",
                    model_id=DEFAULT_NVIDIA_MODEL,
                    raw_text=complete_payload,
                    finish_reason="stop",
                    elapsed_seconds=0.7,
                    token_usage=TokenUsage(
                        prompt_tokens=1000,
                        completion_tokens=400,
                        reasoning_tokens=150,
                        output_tokens=250,
                        total_tokens=1400,
                    ),
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = run_benchmark(
                RetryScenarioAdapter(),
                output_dir=Path(tmp),
                only_files=["pdf_01_table_clean.pdf"],
                max_retries=2,
                backoff_seconds=1.5,
                sleep_fn=sleeps.append,
            )
            doc = result.document_results[0]
            # Attempt 1 transient 503 -> sleep(1.5), Attempt 2 truncated -> sleep(3.0), Attempt 3 complete
            self.assertEqual(doc.request_attempts, 3)
            self.assertEqual(sleeps, [1.5, 3.0])
            self.assertFalse(doc.request_failure)
            self.assertFalse(doc.json_validation_failure)
            self.assertFalse(doc.partial_recovery_triggered)
            # Never duplicates shift from Attempt 2 + Attempt 3: exactly 3 shifts extracted!
            self.assertEqual(doc.extracted_shift_count, 3)
            # Tokens summed across ALL attempts (0 + 1800 + 1400 = 3200)
            self.assertEqual(doc.token_usage["total_tokens"], 3200)
            self.assertEqual(doc.token_usage["prompt_tokens"], 2000)
            self.assertEqual(doc.token_usage["reasoning_tokens"], 650)
            self.assertEqual(len(doc.attempt_history), 3)
            self.assertEqual(doc.attempt_history[0]["transient_error"], True)
            self.assertEqual(doc.attempt_history[1]["finish_reason"], "length")
            self.assertEqual(doc.attempt_history[2]["succeeded"], True)

    def test_missing_employer_location_ambiguous_worker_and_individual_review_safeguards(
        self,
    ) -> None:
        raw_json = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {
                        "worker_name": "Maria Santos",
                        "shift_date": "2026-11-16",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": None,
                        "location": None,
                        "department": "kitchen",
                        "hourly_rate": 16.50,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "worker_name": "Maria",
                        "shift_date": "2026-11-18",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "kitchen",
                        "hourly_rate": 16.50,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "worker_name": None,
                        "shift_date": "2026-11-19",
                        "start_time": "12:00",
                        "end_time": "20:00",
                        "break_minutes": 45,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "kitchen",
                        "hourly_rate": 16.50,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                    {
                        "worker_name": "Tom Becker",
                        "shift_date": "2026-11-20",
                        "start_time": "10:00",
                        "end_time": "18:00",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "floor",
                        "hourly_rate": 14.00,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            raw_json,
            file_name="pdf_06_team_roster_multi_employee.pdf",
            model_id=DEFAULT_NVIDIA_MODEL,
            target_worker="Maria Santos",
        )
        self.assertEqual(parsed.filtered_other_worker_shifts, 1)
        self.assertEqual(len(parsed.shifts), 3)

        exact_worker, partial_worker, missing_worker = parsed.shifts
        self.assertEqual(exact_worker.worker_attribution_status, "verified_target_worker")
        self.assertIn("missing_employer", exact_worker.review_reasons)
        self.assertIn("missing_location", exact_worker.review_reasons)
        self.assertEqual(exact_worker.confirmation_status, "needs_review")
        self.assertFalse(exact_worker.eligible_for_bulk_confirmation)

        for ambiguous in (partial_worker, missing_worker):
            self.assertEqual(
                ambiguous.worker_attribution_status, "ambiguous_or_unverified"
            )
            self.assertEqual(ambiguous.confidence, "low")
            self.assertIn("ambiguous_worker_attribution", ambiguous.review_reasons)
            self.assertEqual(ambiguous.confirmation_status, "needs_review")
            self.assertTrue(ambiguous.requires_individual_review)
            self.assertFalse(ambiguous.eligible_for_bulk_confirmation)

        # Verify worker correction preserves raw_values and normalised separately
        corrected = exact_worker.apply_worker_correction(
            {"employer_name": "Harbor Bistro", "location": "Harbor Bistro Main"},
            confirm_individually=True,
        )
        self.assertIsNone(corrected.normalised.employer_name)
        self.assertIsNone(corrected.normalised.location)
        self.assertIsNone(corrected.raw_values["employer_name"])
        self.assertEqual(corrected.worker_corrected_values.employer_name, "Harbor Bistro")
        self.assertEqual(corrected.confirmation_status, "confirmed")

    def test_versioned_benchmark_directories_prevent_overwrites(self) -> None:
        mock_adapter = NvidiaExtractionAdapter(
            api_key="test",
            http_sender=lambda *_args: {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"week_of": None, "shifts": []})},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # Simulate an existing v1_baseline directory inside base
            (base / "v1_baseline").mkdir()
            (base / "v1_baseline" / "benchmark_results.json").write_text("v1", encoding="utf-8")

            r1 = run_benchmark(
                mock_adapter,
                output_dir=base,
                only_files=["pdf_01_table_clean.pdf"],
            )
            r2 = run_benchmark(
                mock_adapter,
                output_dir=base,
                only_files=["pdf_01_table_clean.pdf"],
            )
            self.assertEqual(r1.output_dir.name, "v2")
            self.assertEqual(r2.output_dir.name, "v3")
            self.assertNotEqual(r1.results_json_path, r2.results_json_path)
            self.assertEqual(
                (base / "v1_baseline" / "benchmark_results.json").read_text(encoding="utf-8"),
                "v1",
            )

            next_dir = resolve_versioned_output_dir(base, run_label="v2")
            self.assertEqual(next_dir.name, "v2_2")

    def test_offline_recovery_on_preserved_v1_baseline_without_api_calls(self) -> None:
        # Deterministic, sanitized V1 partial-truncation and reasoning-exhaustion regression fixture
        # (independent of gitignored local benchmark_output/v1_baseline artifacts).
        truncated_img05_raw = (
            '{\n  "week_of": "Week of 9 November 2026",\n  "shifts": [\n'
            + ",\n".join(
                json.dumps(
                    {
                        "shift_date": f"2026-11-{day:02d}",
                        "start_time": "08:00",
                        "end_time": "16:00",
                        "break_minutes": 30,
                        "employer_name": "Grand Hotel",
                        "location": "Hotel Front",
                        "department": "front desk",
                        "hourly_rate": 18.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "uncertain_fields": [],
                    }
                )
                for day in (9, 10, 11, 12)
            )
            + ',\n    {\n      "shift_date": "2026-11-15",\n      "start_time": "22:00",\n      "end_time": "06'
        )
        v1_fixture = {
            "provider_name": "nvidia",
            "model_id": DEFAULT_NVIDIA_MODEL,
            "documents": [
                {
                    "file_name": "pdf_01_table_clean.pdf",
                    "target_worker": None,
                    "json_validation_failure": False,
                    "token_usage": {
                        "prompt_tokens": 1200,
                        "completion_tokens": 450,
                        "total_tokens": 1650,
                    },
                    "raw_response": json.dumps(
                        {"week_of": "Week of 2 November 2026", "shifts": []}
                    ),
                    "reasoning_text": None,
                },
                {
                    "file_name": "img_05_cropped_perspective.jpg",
                    "target_worker": None,
                    "json_validation_failure": True,
                    "token_usage": {
                        "prompt_tokens": 1634,
                        "completion_tokens": 4096,
                        "total_tokens": 5730,
                    },
                    "raw_response": truncated_img05_raw,
                    "reasoning_text": None,
                },
                {
                    "file_name": "pdf_06_team_roster_multi_employee.pdf",
                    "target_worker": "Maria Santos",
                    "json_validation_failure": True,
                    "token_usage": {
                        "prompt_tokens": 4154,
                        "completion_tokens": 4096,
                        "total_tokens": 8250,
                    },
                    "raw_response": "",
                    # Synthetic draft in reasoning_text verifies evaluate_v1_offline_recovery never mines CoT.
                    "reasoning_text": (
                        'Thought draft: {"shifts": [{"worker_name": "Maria Santos", '
                        '"shift_date": "2026-11-16", "start_time": "09:00", "end_time": "17:00"}]}'
                    ),
                },
            ],
        }

        orig_open = Path.open

        def guarded_open(self_path: Path, *args: Any, **kwargs: Any):
            if self_path.name == "answer_key.csv":
                raise AssertionError("Offline recovery must never read answer_key.csv!")
            return orig_open(self_path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "v1_baseline_fixture.json"
            fixture_path.write_text(json.dumps(v1_fixture), encoding="utf-8")
            with patch.object(Path, "open", guarded_open):
                recovery = evaluate_v1_offline_recovery(fixture_path)

        self.assertEqual(recovery["failed_documents_reprocessed"], 2)
        by_name = {doc["file_name"]: doc for doc in recovery["documents"]}

        img05 = by_name["img_05_cropped_perspective.jpg"]
        self.assertEqual(img05["recovered_shift_count"], 4)
        self.assertEqual(
            [s["normalised"]["shift_date"] for s in img05["recovered_shifts"]],
            ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"],
        )
        self.assertTrue(img05["partial_recovery_triggered"])
        self.assertTrue(img05["incomplete_extraction"])
        self.assertTrue(img05["json_validation_failure"])
        self.assertTrue(
            all(
                s["confidence"] == "low"
                and s["confirmation_status"] == "needs_review"
                and s["eligible_for_bulk_confirmation"] is False
                for s in img05["recovered_shifts"]
            )
        )

        pdf06 = by_name["pdf_06_team_roster_multi_employee.pdf"]
        self.assertEqual(pdf06["recovered_shift_count"], 0)
        self.assertFalse(pdf06["partial_recovery_triggered"])
        self.assertTrue(pdf06["incomplete_extraction"])
        self.assertTrue(pdf06["json_validation_failure"])

    def test_optional_image_preprocessing_is_non_destructive_and_prompt_has_alignment_rules(
        self,
    ) -> None:
        self.assertIn("source_row", SYSTEM_PROMPT)
        self.assertIn("NEVER copy or transfer rates", SYSTEM_PROMPT)
        self.assertIn("source_page", build_user_prompt())
        # Verify projection variance peaks on aligned rows vs scattered rows
        aligned = [[0] * 10, [255] * 10, [0] * 10, [255] * 10]
        uniform = [[128] * 10, [128] * 10, [128] * 10, [128] * 10]
        self.assertGreater(
            _horizontal_projection_variance(aligned),
            _horizontal_projection_variance(uniform),
        )
        # Preprocessing wrapper preserves input bytes when Pillow is unavailable or disabled
        orig = (UNSTRUCTURED_DIR / "images" / "img_07_photo_missing_details.jpg").read_bytes()
        processed, mime, _notes = preprocess_image_bytes(orig, mime_type="image/jpeg")
        self.assertTrue(len(processed) > 0)
        self.assertIn(mime, ("image/jpeg", "image/png"))


class V3ParserAndReportingRegressionTests(unittest.TestCase):
    def test_single_list_wrapped_envelope_unwraps_shifts_without_phantom_records(self) -> None:
        wrapped_envelope = json.dumps(
            [
                {
                    "week_of": "Week of 9 November 2026",
                    "shifts": [
                        {
                            "shift_date": "2026-11-09",
                            "start_time": "07:00",
                            "end_time": "15:00",
                            "break_minutes": 30,
                            "employer_name": "Central Cafe Group",
                            "location": "Cafe Central",
                            "department": "counter",
                            "hourly_rate": 16.50,
                            "currency": "USD",
                            "shift_status": "scheduled",
                            "confidence": "high",
                            "source_page": 1,
                            "source_row": 1,
                        },
                        {
                            "shift_date": "2026-11-11",
                            "start_time": "07:00",
                            "end_time": "15:00",
                            "break_minutes": 30,
                            "employer_name": "Central Cafe Group",
                            "location": "Cafe Central",
                            "department": "counter",
                            "hourly_rate": 16.50,
                            "currency": "USD",
                            "shift_status": "cancelled",
                            "confidence": "high",
                            "source_page": 1,
                            "source_row": 3,
                        },
                    ],
                }
            ]
        )
        parsed = parse_and_validate_model_json(
            wrapped_envelope,
            file_name="img_02_photo_tilted.jpg",
            model_id="gemini-3.5-flash-lite",
        )
        self.assertFalse(parsed.json_validation_failure)
        self.assertEqual(parsed.invalid_or_empty_records, 0)
        self.assertEqual(parsed.week_of, "Week of 9 November 2026")
        self.assertEqual(len(parsed.shifts), 2)
        self.assertEqual(parsed.shifts[1].normalised.shift_status, "cancelled")

    def test_multiple_envelopes_preserve_distinct_week_contexts_and_source_page(self) -> None:
        multi_env = json.dumps(
            [
                {
                    "week_of": "Week of 2 November 2025",
                    "source_page": 1,
                    "shifts": [
                        {
                            "shift_date": "Mon 3 Nov",
                            "start_time": "09:00",
                            "end_time": "17:00",
                            "break_minutes": 0,
                            "employer_name": "BrightMart",
                            "location": "Store A",
                            "department": "sales",
                            "hourly_rate": 15.0,
                            "currency": "USD",
                            "shift_status": "scheduled",
                        }
                    ],
                },
                {
                    "week_of": "Week of 9 November 2026",
                    "source_page": 2,
                    "shifts": [
                        {
                            "shift_date": "Mon 9 Nov",
                            "start_time": "09:00",
                            "end_time": "17:00",
                            "break_minutes": 30,
                            "employer_name": "BrightMart",
                            "location": "Store A",
                            "department": "sales",
                            "hourly_rate": 16.0,
                            "currency": "USD",
                            "shift_status": "scheduled",
                        }
                    ],
                },
            ]
        )
        parsed = parse_and_validate_model_json(
            multi_env,
            file_name="multi_page.pdf",
            model_id="gemini-3.5-flash-lite",
        )
        self.assertFalse(parsed.json_validation_failure)
        self.assertEqual(len(parsed.shifts), 2)
        self.assertEqual(parsed.shifts[0].normalised.shift_date, "2025-11-03")
        self.assertEqual(parsed.shifts[0].source_page, 1)
        self.assertEqual(parsed.shifts[1].normalised.shift_date, "2026-11-09")
        self.assertEqual(parsed.shifts[1].source_page, 2)
        self.assertEqual(
            parsed.week_of, "Week of 2 November 2025 | Week of 9 November 2026"
        )

    def test_empty_records_and_mixed_invalid_structures_are_rejected_and_incomplete_shifts_preserved(
        self,
    ) -> None:
        # Mixed ambiguous top-level array combining envelope dict and bare shift dict
        mixed = json.dumps(
            [
                {"week_of": "2026-11-02", "shifts": []},
                {"shift_date": "2026-11-03", "start_time": "08:00"},
            ]
        )
        res_mixed = parse_and_validate_model_json(
            mixed, file_name="mixed.png", model_id=DEFAULT_NVIDIA_MODEL
        )
        self.assertTrue(res_mixed.json_validation_failure)
        self.assertIn("Ambiguous mixed", res_mixed.json_validation_errors[0])

        # Envelope containing an empty {}, all-dash row, misplaced inner envelope,
        # AND a genuinely incomplete valid shift (shift_date + start_time only)
        payload = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {},
                    {
                        "shift_date": "-",
                        "start_time": "N/A",
                        "end_time": "TBC",
                        "break_minutes": None,
                        "employer_name": None,
                        "shift_status": "scheduled",
                    },
                    {"week_of": "nested", "shifts": []},
                    {
                        "shift_date": "2026-11-20",
                        "start_time": "08:00",
                        "end_time": None,
                        "break_minutes": None,
                        "employer_name": "Metro Logistics",
                        "location": None,
                        "hourly_rate": None,
                        "currency": None,
                        "shift_status": "scheduled",
                        "confidence": "high",
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            payload,
            file_name="pdf_07_missing_details.pdf",
            model_id="gemini-3.5-flash-lite",
        )
        self.assertTrue(parsed.json_validation_failure)
        self.assertTrue(parsed.incomplete_extraction)
        self.assertEqual(parsed.invalid_or_empty_records, 3)
        self.assertEqual(len(parsed.rejected_records), 3)
        self.assertEqual(len(parsed.shifts), 1)
        valid_incomplete = parsed.shifts[0]
        self.assertEqual(valid_incomplete.normalised.shift_date, "2026-11-20")
        self.assertEqual(valid_incomplete.normalised.start_time, "08:00")
        self.assertIsNone(valid_incomplete.normalised.end_time)
        self.assertIsNone(valid_incomplete.normalised.break_minutes)
        self.assertEqual(valid_incomplete.confirmation_status, "needs_review")
        self.assertFalse(valid_incomplete.eligible_for_bulk_confirmation)

    def test_empty_record_triggers_retry_and_preserves_zero_phantom_rows_in_csv(self) -> None:
        calls = {"n": 0}
        phantom_envelope = json.dumps({"week_of": None, "shifts": [{}]})
        valid_envelope = json.dumps(
            {
                "week_of": "Week of 2 November 2026",
                "shifts": [
                    {
                        "shift_date": "2026-11-03",
                        "start_time": "08:00",
                        "end_time": "16:00",
                        "break_minutes": 0,
                        "employer_name": "BrightMart",
                        "location": "Store A",
                        "department": "sales floor",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    }
                ],
            }
        )

        class RetryEmptyRecordAdapter(ExtractionAdapter):
            @property
            def provider_name(self) -> str:
                return "gemini"

            @property
            def model_id(self) -> str:
                return "gemini-3.5-flash-lite"

            def extract(self, request: ProviderExtractionRequest) -> ProviderRawResponse:
                calls["n"] += 1
                raw_text = phantom_envelope if calls["n"] == 1 else valid_envelope
                return ProviderRawResponse(
                    provider_name="gemini",
                    model_id="gemini-3.5-flash-lite",
                    raw_text=raw_text,
                    finish_reason="stop",
                    elapsed_seconds=0.3,
                    token_usage=TokenUsage(
                        prompt_tokens=100,
                        completion_tokens=40,
                        reasoning_tokens=0,
                        output_tokens=40,
                        total_tokens=140,
                    ),
                )

        with tempfile.TemporaryDirectory() as tmp:
            res = run_benchmark(
                RetryEmptyRecordAdapter(),
                output_dir=Path(tmp),
                only_files=["pdf_01_table_clean.pdf"],
                backoff_seconds=0.0,
            )
            doc = res.document_results[0]
            self.assertEqual(doc.request_attempts, 2)
            self.assertEqual(res.total_retries, 1)
            self.assertEqual(res.failed_attempts, 1)
            self.assertAlmostEqual(res.failed_attempt_overhead_seconds, 0.3, places=3)
            self.assertEqual(doc.extracted_shift_count, 1)
            self.assertEqual(doc.invalid_or_empty_records, 0)
            self.assertEqual(res.total_tokens, 280)
            # Only 1 shift row written to extracted.csv (zero phantom empty rows)
            with res.extracted_csv_path.open(newline="", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))
            self.assertEqual(len(csv_rows), 1)
            self.assertEqual(csv_rows[0]["shift_date"], "2026-11-03")
            self.assertEqual(csv_rows[0]["break_minutes"], "0")

    def test_gemini_structured_output_schema_and_token_reconciliation(self) -> None:
        adapter = GeminiExtractionAdapter(model_id="gemini-3.5-flash-lite", api_key="test")
        pages = load_document_pages(
            UNSTRUCTURED_DIR / "images" / "img_01_screenshot_clean.png"
        )
        payload = adapter.build_payload(
            ProviderExtractionRequest(
                file_name="img_01_screenshot_clean.png",
                pages=tuple(pages),
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(target_worker="Maria Santos"),
            )
        )
        gen_cfg = payload["generationConfig"]
        self.assertEqual(gen_cfg["responseMimeType"], "application/json")
        self.assertEqual(gen_cfg["responseSchema"], GEMINI_RESPONSE_SCHEMA)
        self.assertEqual(gen_cfg["responseSchema"]["type"], "OBJECT")
        self.assertIn("shifts", gen_cfg["responseSchema"]["properties"])
        item_props = gen_cfg["responseSchema"]["properties"]["shifts"]["items"]["properties"]
        self.assertTrue(item_props["break_minutes"]["nullable"])
        self.assertEqual(item_props["break_minutes"]["type"], "INTEGER")
        self.assertIn("worker_name", item_props)
        self.assertNotIn("additionalProperties", json.dumps(gen_cfg["responseSchema"]))

        # Reconcile Gemini usageMetadata with thoughtsTokenCount present
        usage = parse_token_usage(
            {
                "promptTokenCount": 2304,
                "candidatesTokenCount": 505,
                "thoughtsTokenCount": 200,
                "totalTokenCount": 3009,
            }
        )
        self.assertEqual(usage.prompt_tokens, 2304)
        self.assertEqual(usage.output_tokens, 505)
        self.assertEqual(usage.reasoning_tokens, 200)
        self.assertEqual(usage.completion_tokens, 705)
        self.assertEqual(usage.total_tokens, 3009)

    def test_truncated_list_wrapped_envelope_partial_recovery(self) -> None:
        truncated_wrapped = (
            '[\n  {\n    "week_of": "Week of 9 November 2026",\n    "shifts": [\n'
            '      {"shift_date": "2026-11-09", "start_time": "07:00", "end_time": "15:00", '
            '"break_minutes": 30, "employer_name": "Central Cafe Group", "location": "Cafe Central", '
            '"department": "counter", "hourly_rate": 16.5, "currency": "USD", "shift_status": "scheduled"},\n'
            '      {"shift_date": "2026-11-10", "start_time": "07:00"'
        )
        parsed = parse_and_validate_model_json(
            truncated_wrapped,
            file_name="img_02_photo_tilted.jpg",
            model_id="gemini-3.5-flash-lite",
            finish_reason="length",
        )
        self.assertTrue(parsed.partial_recovery_triggered)
        self.assertTrue(parsed.incomplete_extraction)
        self.assertEqual(parsed.partially_recovered_shift_count, 1)
        self.assertEqual(parsed.shifts[0].normalised.shift_date, "2026-11-09")
        self.assertEqual(parsed.shifts[0].confirmation_status, "needs_review")
        self.assertFalse(parsed.shifts[0].eligible_for_bulk_confirmation)

    def test_cancellation_sensitive_metrics_and_subset_reporting(self) -> None:
        # img_02_photo_tilted has 5 expected shifts (2 cancelled on Nov 11 & Nov 13).
        # Flipping cancelled/scheduled statuses must lower earnings_critical_ok below money_ok.
        swapped_status_response = json.dumps(
            {
                "week_of": "Week of 9 November 2026",
                "shifts": [
                    {
                        "shift_date": d,
                        "start_time": "07:00",
                        "end_time": "15:00",
                        "break_minutes": 30,
                        "employer_name": "Central Cafe Group",
                        "location": "Cafe Central",
                        "department": "counter",
                        "hourly_rate": 16.5,
                        "currency": "USD",
                        "shift_status": st,
                        "confidence": "high",
                    }
                    for d, st in [
                        ("2026-11-09", "scheduled"),
                        ("2026-11-10", "cancelled"),  # wrong (should be scheduled)
                        ("2026-11-11", "scheduled"),  # wrong (should be cancelled)
                        ("2026-11-12", "scheduled"),
                        ("2026-11-13", "cancelled"),
                    ]
                ],
            }
        )
        adapter = NvidiaExtractionAdapter(
            api_key="test",
            http_sender=lambda *_args: {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": swapped_status_response},
                    }
                ],
                "usage": {
                    "prompt_tokens": 2000,
                    "completion_tokens": 500,
                    "reasoning_tokens": 100,
                    "total_tokens": 2500,
                },
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            res = run_benchmark(
                adapter,
                output_dir=Path(tmp),
                only_files=["img_02_photo_tilted.jpg"],
            )
            summary = res.comparison_summary
            self.assertEqual(summary["expected"], 5)
            self.assertEqual(summary["true_positives"], 5)
            self.assertEqual(summary["false_positives"], 0)
            self.assertEqual(summary["false_negatives"], 0)
            self.assertAlmostEqual(summary["precision"], 1.0)
            self.assertAlmostEqual(summary["recall"], 1.0)
            self.assertAlmostEqual(summary["f1"], 1.0)
            self.assertEqual(summary["money_ok"], 5)
            self.assertEqual(summary["earnings_critical_ok"], 3)
            self.assertEqual(summary["all_ok"], 3)
            # Full dataset saved separately with explicit limitation note
            self.assertIsNotNone(res.full_dataset_comparison_summary)
            self.assertEqual(res.full_dataset_comparison_summary["expected"], 62)
            self.assertEqual(res.full_dataset_comparison_summary["false_negatives"], 57)
            self.assertEqual(
                res.deterministic_validation_summary["as_extracted_unconfirmed"][
                    "eligible_for_earnings_count"
                ],
                0,
            )

    @staticmethod
    def _build_sanitized_replay_fixture_payload(provider_name: str) -> dict[str, Any]:
        """Build a minimal, sanitized 14-document replay fixture payload (no live/raw artifacts)."""
        manifest = load_files_manifest(DEFAULT_FILES_CSV)
        expected_by_file: dict[str, list[dict[str, str]]] = {}
        with DEFAULT_ANSWER_KEY_CSV.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                expected_by_file.setdefault(row["file_name"], []).append(row)

        total_token_target = 42666 if provider_name == "gemini" else 68389
        model_id = (
            DEFAULT_GEMINI_MODEL if provider_name == "gemini" else DEFAULT_NVIDIA_MODEL
        )
        per_doc_tokens, remainder = divmod(total_token_target, len(manifest))

        documents: list[dict[str, Any]] = []
        for idx, entry in enumerate(manifest):
            rows = expected_by_file[entry.file_name]
            shifts_payload: list[dict[str, Any]] = []
            for r in rows:
                shift_item: dict[str, Any] = {
                    "shift_date": r["shift_date"],
                    "start_time": r["start_time"],
                    "end_time": r["end_time"] or None,
                    "break_minutes": (
                        int(r["break_minutes"]) if r["break_minutes"] != "" else None
                    ),
                    "employer_name": r["employer_name"] or None,
                    "location": r["location"] or None,
                    "department": r["department"] or None,
                    "hourly_rate": (
                        float(r["hourly_rate"]) if r["hourly_rate"] != "" else None
                    ),
                    "currency": r["currency"] or None,
                    "shift_status": r["shift_status"],
                    "confidence": "high",
                    "uncertain_fields": [],
                }
                if entry.file_name == "pdf_06_team_roster_multi_employee.pdf":
                    shift_item["worker_name"] = "Maria Santos"
                shifts_payload.append(shift_item)

            if entry.file_name == "pdf_06_team_roster_multi_employee.pdf":
                shifts_payload.append(
                    {
                        "worker_name": "James Okoro",
                        "shift_date": "2026-11-17",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Bistro Main",
                        "department": "bar",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "confidence": "high",
                    }
                )

            if provider_name == "gemini":
                if entry.file_name == "img_06_chat_message.png":
                    # 2 status mismatches -> money_ok=True, earnings_critical_ok=False
                    for item in shifts_payload:
                        if item["shift_status"] == "changed":
                            item["shift_status"] = "scheduled"
                elif entry.file_name == "img_07_photo_missing_details.jpg":
                    # 3 money-field mismatches -> money_ok drops by 3 (62 -> 59)
                    shifts_payload[1]["break_minutes"] = 45
                    shifts_payload[2]["hourly_rate"] = 14.25
                    shifts_payload[2]["currency"] = "GBP"
                    shifts_payload[3]["hourly_rate"] = None
                    shifts_payload[3]["currency"] = None

                envelope: Any = {"week_of": "2026-11", "shifts": shifts_payload}
                if entry.file_name == "img_02_photo_tilted.jpg":
                    envelope = [envelope]
            else:
                if entry.file_name == "img_07_photo_missing_details.jpg":
                    # 2 money-field mismatches -> money_ok drops by 2 (62 -> 60)
                    shifts_payload[2]["hourly_rate"] = 14.25
                    shifts_payload[2]["currency"] = "GBP"
                    shifts_payload[3]["hourly_rate"] = None
                    shifts_payload[3]["currency"] = None
                elif entry.file_name in (
                    "img_02_photo_tilted.jpg",
                    "img_06_chat_message.png",
                ):
                    # 4 status mismatches -> earnings_critical_ok drops by 4 (60 -> 56)
                    for item in shifts_payload:
                        if item["shift_status"] in ("cancelled", "changed"):
                            item["shift_status"] = "scheduled"
                elif entry.file_name == "pdf_04_weekly_grid.pdf":
                    # 3 non-money location mismatches -> all_ok drops by 3 (56 -> 53)
                    for item in shifts_payload:
                        item["location"] = None

                envelope = {"week_of": "2026-11", "shifts": shifts_payload}

            doc_tok = per_doc_tokens + (remainder if idx == 0 else 0)
            prompt_tok = int(doc_tok * 0.7)
            comp_tok = doc_tok - prompt_tok
            reas_tok = int(comp_tok * 0.3) if provider_name == "nvidia" else 0
            documents.append(
                {
                    "file_name": entry.file_name,
                    "schedule_id": entry.schedule_id,
                    "kind": entry.kind,
                    "difficulty": entry.difficulty,
                    "target_worker": entry.target_worker,
                    "page_count": 1,
                    "provider_name": provider_name,
                    "model_id": model_id,
                    "processing_time_seconds": 0.5,
                    "finish_reason": "stop",
                    "token_usage": {
                        "prompt_tokens": prompt_tok,
                        "completion_tokens": comp_tok,
                        "reasoning_tokens": reas_tok,
                        "output_tokens": comp_tok - reas_tok,
                        "total_tokens": doc_tok,
                    },
                    "raw_response": json.dumps(envelope),
                    "reasoning_text": None,
                    "request_failure": False,
                    "request_error": None,
                }
            )

        return {
            "provider_name": provider_name,
            "model_id": model_id,
            "selected_files": None,
            "documents": documents,
        }

    def test_offline_replay_reproduces_saved_gemini_and_nvidia_targets(self) -> None:
        # Uses deterministic, sanitized 14-document replay fixtures rather than
        # gitignored local benchmark_output artifacts so the check passes on fresh checkouts.
        gemini_payload = self._build_sanitized_replay_fixture_payload("gemini")
        nvidia_payload = self._build_sanitized_replay_fixture_payload("nvidia")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            gem_src = tmp_dir / "sanitized_gemini_fixture.json"
            nvd_src = tmp_dir / "sanitized_nvidia_fixture.json"
            gem_src.write_text(json.dumps(gemini_payload), encoding="utf-8")
            nvd_src.write_text(json.dumps(nvidia_payload), encoding="utf-8")

            gem_replay = replay_saved_benchmark_run(
                gem_src,
                output_dir=tmp_dir,
                run_label="v3_replay_gemini",
            )
            sg = gem_replay.comparison_summary
            self.assertEqual(sg["expected"], 62)
            self.assertEqual(sg["true_positives"], 62)
            self.assertEqual(sg["false_positives"], 0)
            self.assertEqual(sg["false_negatives"], 0)
            self.assertAlmostEqual(sg["precision"], 1.0)
            self.assertAlmostEqual(sg["recall"], 1.0)
            self.assertAlmostEqual(sg["f1"], 1.0)
            self.assertEqual(gem_replay.total_invalid_or_empty_records, 0)
            self.assertEqual(sg["all_ok"], 57)
            self.assertEqual(sg["money_ok"], 59)
            self.assertEqual(sg["earnings_critical_ok"], 57)
            self.assertEqual(gem_replay.total_tokens, 42666)
            self.assertEqual(
                gem_replay.deterministic_validation_summary["as_extracted_unconfirmed"][
                    "eligible_for_earnings_count"
                ],
                0,
            )

            nvd_replay = replay_saved_benchmark_run(
                nvd_src,
                output_dir=tmp_dir,
                run_label="v3_replay_nvidia",
            )
            sn = nvd_replay.comparison_summary
            self.assertEqual(sn["expected"], 62)
            self.assertEqual(sn["true_positives"], 62)
            self.assertEqual(sn["false_positives"], 0)
            self.assertEqual(sn["false_negatives"], 0)
            self.assertAlmostEqual(sn["precision"], 1.0)
            self.assertAlmostEqual(sn["recall"], 1.0)
            self.assertAlmostEqual(sn["f1"], 1.0)
            self.assertEqual(nvd_replay.total_invalid_or_empty_records, 0)
            self.assertEqual(sn["all_ok"], 53)
            self.assertEqual(sn["money_ok"], 60)
            self.assertEqual(sn["earnings_critical_ok"], 56)
            self.assertEqual(nvd_replay.total_tokens, 68389)
            self.assertEqual(
                nvd_replay.deterministic_validation_summary["as_extracted_unconfirmed"][
                    "eligible_for_earnings_count"
                ],
                0,
            )


def _make_synthetic_table_png(angle_deg: float, width: int = 420, height: int = 240) -> bytes:
    """Create a synthetic RGBA PNG containing a table tilted by angle_deg."""
    rad = math.radians(angle_deg)
    cos_t = math.cos(rad)
    sin_t = math.sin(rad)
    cx = width / 2.0
    cy = height / 2.0
    rgba = bytearray([245, 245, 245, 255] * (width * height))
    for y in range(height):
        for x in range(width):
            dx = x - cx
            dy = y - cy
            tx = dx * cos_t + dy * sin_t
            ty = -dx * sin_t + dy * cos_t
            if -160 <= tx <= 160 and -75 <= ty <= 75:
                if abs(ty - round(ty / 25.0) * 25.0) < 1.2:
                    idx = (y * width + x) * 4
                    rgba[idx : idx + 3] = b"\x15\x15\x15"
                elif abs((ty % 25.0) - 12.0) < 1.5 and (int(tx + 160) % 18) < 12:
                    idx = (y * width + x) * 4
                    rgba[idx : idx + 3] = b"\x25\x25\x25"
    return _encode_rgba_png(width, height, bytes(rgba))


class V31ConflictAndPreprocessingRegressionTests(unittest.TestCase):
    @staticmethod
    def _load_mod(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _build_missing_details_conflicting_duplicate_fixture_json() -> str:
        """
        Return a deterministic, sanitized 5-record extraction fixture for
        img_07_photo_missing_details.jpg reproducing conflicting duplicates on 2026-11-20.
        """
        return json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {
                        "shift_date": "2026-11-16",
                        "start_time": "07:00",
                        "end_time": "15:00",
                        "break_minutes": 45,
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": 14.25,
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "uncertain_fields": [],
                        "source_page": 1,
                        "source_row": 1,
                        "worker_name": None,
                    },
                    {
                        "shift_date": "2026-11-17",
                        "start_time": "07:00",
                        "end_time": "15:00",
                        "break_minutes": None,
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": 14.25,
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "uncertain_fields": [],
                        "source_page": 1,
                        "source_row": 2,
                        "worker_name": None,
                    },
                    {
                        "shift_date": "2026-11-19",
                        "start_time": "07:00",
                        "end_time": "15:00",
                        "break_minutes": None,
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": None,
                        "currency": None,
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "uncertain_fields": [],
                        "source_page": 1,
                        "source_row": 3,
                        "worker_name": None,
                    },
                    {
                        "shift_date": "2026-11-20",
                        "start_time": "13:00",
                        "end_time": "21:00",
                        "break_minutes": 45,
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": 14.25,
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "uncertain_fields": [],
                        "source_page": 1,
                        "source_row": 4,
                        "worker_name": None,
                    },
                    {
                        "shift_date": "2026-11-20",
                        "start_time": "13:00",
                        "end_time": "21:00",
                        "break_minutes": 0,
                        "employer_name": "Greenfield Care",
                        "location": "Greenfield Home",
                        "department": "carer",
                        "hourly_rate": None,
                        "currency": None,
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "uncertain_fields": [],
                        "source_page": 1,
                        "source_row": 5,
                        "worker_name": None,
                    },
                ],
            }
        )

    def test_v3_gemini_missing_details_artifact_conflict_group_and_comparator_order_sensitivity(
        self,
    ) -> None:
        raw_fixture = self._build_missing_details_conflicting_duplicate_fixture_json()
        parsed = parse_and_validate_model_json(
            raw_fixture,
            file_name="img_07_photo_missing_details.jpg",
            model_id="gemini-3.5-flash-lite",
            finish_reason="stop",
        )
        self.assertEqual(len(parsed.shifts), 5)
        self.assertEqual(parsed.deduplicated_shifts, 0)
        self.assertEqual(parsed.conflicting_duplicate_count, 2)
        self.assertEqual(len(parsed.conflict_groups), 1)

        rec4, rec5 = parsed.shifts[3], parsed.shifts[4]
        self.assertEqual(rec4.source_row, 4)
        self.assertEqual(rec5.source_row, 5)
        self.assertEqual(rec4.conflict_group_id, "conflict_group_1")
        self.assertEqual(rec5.conflict_group_id, "conflict_group_1")
        self.assertTrue(rec4.requires_conflict_resolution)
        self.assertTrue(rec5.requires_conflict_resolution)
        self.assertEqual(
            rec4.conflicting_fields, ["break_minutes", "hourly_rate", "currency"]
        )
        self.assertEqual(
            rec5.conflicting_fields, ["break_minutes", "hourly_rate", "currency"]
        )

        # Demonstrate compare_extraction.py greedy first-match order sensitivity
        compare_tool = self._load_mod("compare_extraction", COMPARE_TOOL_PATH)
        key_rows = [
            r
            for r in compare_tool.read_csv(str(DEFAULT_ANSWER_KEY_CSV))
            if r["file_name"] == "img_07_photo_missing_details.jpg"
        ]
        got_in_order = [
            r.to_compare_csv_row("img_07_photo_missing_details.jpg")
            for r in parsed.shifts
        ]
        got_reversed_conflict = [
            *got_in_order[:3],
            got_in_order[4],
            got_in_order[3],
        ]
        res_forward = compare_tool.summarise(compare_tool.compare(key_rows, got_in_order))
        res_reverse = compare_tool.summarise(
            compare_tool.compare(key_rows, got_reversed_conflict)
        )
        self.assertEqual(res_forward["field_ok"]["break_minutes"], 2)
        self.assertEqual(res_forward["field_ok"]["hourly_rate"], 4)
        self.assertEqual(res_forward["field_ok"]["currency"], 4)
        self.assertEqual(res_reverse["field_ok"]["break_minutes"], 3)
        self.assertEqual(res_reverse["field_ok"]["hourly_rate"], 3)
        self.assertEqual(res_reverse["field_ok"]["currency"], 3)

    def test_conflicting_duplicates_cannot_contribute_to_earnings_through_confirmation_alone(
        self,
    ) -> None:
        # Case 1: Deterministic conflicting-duplicate missing-details fixture
        raw_fixture = self._build_missing_details_conflicting_duplicate_fixture_json()
        parsed_gem = parse_and_validate_model_json(
            raw_fixture,
            file_name="img_07_photo_missing_details.jpg",
            model_id="gemini-3.5-flash-lite",
        )
        val_gem = _evaluate_deterministic_validation(
            [("img_07_photo_missing_details.jpg", rec) for rec in parsed_gem.shifts]
        )
        self.assertEqual(val_gem["unresolved_conflict_records"], 2)
        self.assertEqual(
            val_gem["as_extracted_unconfirmed"]["eligible_for_earnings_count"], 0
        )
        self.assertEqual(
            val_gem["if_individually_confirmed"]["eligible_for_earnings_count"], 1
        )

        # Case 2: Both conflicting duplicates have complete money fields AND differing locations
        complete_conflict_json = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {
                        "shift_date": "2026-11-20",
                        "start_time": "13:00",
                        "end_time": "21:00",
                        "break_minutes": 45,
                        "employer_name": "Greenfield Care",
                        "location": "Home A",
                        "department": "carer",
                        "hourly_rate": 14.25,
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "source_page": 1,
                        "source_row": 4,
                    },
                    {
                        "shift_date": "2026-11-20",
                        "start_time": "13:00",
                        "end_time": "21:00",
                        "break_minutes": 0,
                        "employer_name": "Greenfield Care",
                        "location": "Home B",
                        "department": "carer",
                        "hourly_rate": 16.00,
                        "currency": "GBP",
                        "shift_status": "scheduled",
                        "confidence": "high",
                        "source_page": 1,
                        "source_row": 5,
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            complete_conflict_json,
            file_name="img_07_photo_missing_details.jpg",
            model_id="gemini-3.5-flash-lite",
        )
        self.assertEqual(parsed.conflicting_duplicate_count, 2)

        # Attempting confirm_individually=True alone must NOT confirm unresolved conflict members
        for rec in parsed.shifts:
            attempted = rec.apply_worker_correction({}, confirm_individually=True)
            self.assertEqual(attempted.confirmation_status, "needs_review")
            self.assertIn(
                "conflict_resolution_required_before_confirmation",
                attempted.review_reasons,
            )

        det = _evaluate_deterministic_validation(
            [("img_07_photo_missing_details.jpg", rec) for rec in parsed.shifts]
        )
        self.assertEqual(det["unresolved_conflict_records"], 2)
        self.assertEqual(
            det["if_individually_confirmed"]["eligible_for_earnings_count"], 0
        )

        # Explicit conflict resolution selects source_row=5 and rejects source_row=4 (preserved)
        resolved = resolve_conflict_group(
            parsed,
            "conflict_group_1",
            selected_source_row=5,
            worker_corrections={"hourly_rate": "14.25", "currency": "GBP"},
            confirm_selected=True,
        )
        self.assertEqual(len(resolved.shifts), 2)
        kept = resolved.shifts[1]
        rejected = resolved.shifts[0]
        self.assertEqual(kept.confirmation_status, "confirmed")
        self.assertTrue(kept.conflict_resolved)
        self.assertEqual(rejected.confirmation_status, "rejected")
        self.assertTrue(rejected.conflict_resolved)

        calc_mod = self._load_mod("shift_calculations", BACKEND_CALC_PATH)
        calc_out = calc_mod.calculate_shifts(
            {
                "worker_id": "W_CONFLICT_TEST",
                "shifts": [
                    {
                        "shift_id": f"R{rec.source_row}",
                        "shift_date": rec.effective_values().shift_date,
                        "start_time": rec.effective_values().start_time,
                        "end_time": rec.effective_values().end_time,
                        "break_minutes": rec.effective_values().break_minutes,
                        "employer_name": rec.effective_values().employer_name,
                        "location": rec.effective_values().location,
                        "hourly_rate": rec.effective_values().hourly_rate,
                        "currency": rec.effective_values().currency,
                        "shift_status": rec.effective_values().shift_status,
                        "confirmation_status": rec.confirmation_status,
                    }
                    for rec in resolved.shifts
                ],
            },
            flag_messages=calc_mod.load_flag_messages(str(FLAG_TYPES_PATH)),
            known_locations=calc_mod.load_known_locations(str(BACKEND_LOCATIONS_PATH)),
            rules=calc_mod.load_rules(str(BACKEND_RULES_PATH)),
        )
        eligible = [s for s in calc_out["shifts"] if s["eligible_for_earnings"]]
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["shift_id"], "R5")
        rejected_calc = [s for s in calc_out["shifts"] if s["shift_id"] == "R4"][0]
        self.assertEqual(rejected_calc["earnings_status"], "rejected")
        self.assertEqual(calc_out["weekly_summary"][0]["gross_earnings"], 114.0)

    def test_exact_duplicates_deduplicate_with_provenance_and_different_employers_not_grouped(
        self,
    ) -> None:
        payload = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    {
                        "shift_date": "2026-11-16",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": "BrightMart",
                        "location": "Store A",
                        "department": "sales",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "source_page": 1,
                        "source_row": 1,
                    },
                    {
                        "shift_date": "2026-11-16",
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "break_minutes": 30,
                        "employer_name": "BrightMart",
                        "location": "Store A",
                        "department": "sales",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "source_page": 2,
                        "source_row": 2,
                    },
                    {
                        "shift_date": "2026-11-21",
                        "start_time": "09:00",
                        "end_time": "13:00",
                        "break_minutes": 0,
                        "employer_name": "BrightMart",
                        "location": "Store A",
                        "department": "sales",
                        "hourly_rate": 15.0,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "source_page": 2,
                        "source_row": 3,
                    },
                    {
                        "shift_date": "2026-11-21",
                        "start_time": "09:00",
                        "end_time": "13:00",
                        "break_minutes": 15,
                        "employer_name": "Harbor Bistro",
                        "location": "Harbor Main",
                        "department": "counter",
                        "hourly_rate": 16.5,
                        "currency": "USD",
                        "shift_status": "scheduled",
                        "source_page": 2,
                        "source_row": 4,
                    },
                ],
            }
        )
        parsed = parse_and_validate_model_json(
            payload,
            file_name="multi_employer.pdf",
            model_id="gemini-3.5-flash-lite",
        )
        self.assertEqual(parsed.deduplicated_shifts, 1)
        self.assertEqual(len(parsed.shifts), 3)
        self.assertEqual(len(parsed.shifts[0].deduplicated_provenance), 1)
        self.assertEqual(parsed.shifts[0].deduplicated_provenance[0]["source_row"], 2)
        self.assertEqual(len(parsed.deduplicated_records), 1)
        # Simultaneous shifts at BrightMart vs Harbor Bistro are NOT conflicting duplicates
        self.assertEqual(parsed.conflicting_duplicate_count, 0)
        self.assertEqual(parsed.conflict_groups, [])
        self.assertIsNone(parsed.shifts[1].conflict_group_id)
        self.assertIsNone(parsed.shifts[2].conflict_group_id)
        self.assertFalse(parsed.shifts[1].requires_conflict_resolution)
        self.assertFalse(parsed.shifts[2].requires_conflict_resolution)

    def test_synthetic_image_deskew_estimation_canvas_expansion_and_unreliable_preservation(
        self,
    ) -> None:
        # 1. Synthetic rotated tables (+4.0 deg and -3.5 deg): auto-detected & expanded without cropping
        for true_angle in (4.0, -3.5):
            tilted_png = _make_synthetic_table_png(true_angle)
            out_bytes, out_mime, diag = inspect_and_preprocess_image(
                tilted_png, mime_type="image/png", deskew=True
            )
            self.assertEqual(out_mime, "image/png")
            self.assertIsInstance(diag, ImagePreprocessingDiagnostics)
            self.assertTrue(diag.orientation_reliable)
            self.assertIsNotNone(diag.estimated_angle_degrees)
            self.assertLessEqual(abs(diag.estimated_angle_degrees - true_angle), 0.5)
            self.assertFalse(diag.preserved_original_bytes)
            self.assertGreater(diag.output_width, diag.original_width)
            self.assertGreater(diag.output_height, diag.original_height)
            self.assertTrue(
                any(s.startswith("deskew_applied:") for s in diag.applied_transformations)
            )
            self.assertTrue(
                any(s.startswith("canvas_expanded:") for s in diag.applied_transformations)
            )

            dec = _decode_png_rgba(out_bytes)
            self.assertIsNotNone(dec)
            dw, dh, drgba = dec
            residual, _, res_rel = estimate_skew_angle_from_rgba(dw, dh, drgba)
            self.assertTrue(res_rel)
            self.assertIsNotNone(residual)
            self.assertLessEqual(abs(residual), 0.5)

            # Verify pure-Python fallback rotator aligns identically too
            ow, oh, orgba = _decode_png_rgba(tilted_png)
            pw, ph, prgba = _rotate_rgba_expanded_python(
                ow, oh, orgba, diag.rotation_applied_degrees
            )
            self.assertGreater(pw, ow)
            self.assertGreater(ph, oh)
            py_res, _, py_rel = estimate_skew_angle_from_rgba(pw, ph, prgba)
            self.assertTrue(py_rel)
            self.assertLessEqual(abs(py_res), 0.5)

        # 2. Level synthetic table (0.0 deg): skips rotation & preserves exact original bytes
        level_png = _make_synthetic_table_png(0.0)
        out_level, out_level_mime, diag_level = inspect_and_preprocess_image(
            level_png, mime_type="image/png", deskew=True
        )
        self.assertEqual(out_level_mime, "image/png")
        self.assertTrue(diag_level.orientation_reliable)
        self.assertLess(abs(diag_level.estimated_angle_degrees), 0.5)
        self.assertTrue(diag_level.preserved_original_bytes)
        self.assertEqual(out_level, level_png)
        self.assertIn("deskew_skipped:within_threshold", diag_level.applied_transformations)
        self.assertIn("preserved_original_image", diag_level.applied_transformations)

        # 3. Featureless blank synthetic PNG: unreliable orientation preserves exact original bytes
        blank_png = _encode_rgba_png(
            180, 120, bytes([240, 240, 240, 255] * (180 * 120))
        )
        out_blank, _, diag_blank = inspect_and_preprocess_image(
            blank_png, mime_type="image/png", deskew=True
        )
        self.assertFalse(diag_blank.orientation_reliable)
        self.assertTrue(diag_blank.preserved_original_bytes)
        self.assertEqual(out_blank, blank_png)
        self.assertIn(
            "deskew_skipped:unreliable_orientation", diag_blank.applied_transformations
        )
        self.assertIn("preserved_original_image", diag_blank.applied_transformations)

        # 4. Real tilted sample images: disabled by default, non-destructive & expands when enabled
        img07_path = UNSTRUCTURED_DIR / "images" / "img_07_photo_missing_details.jpg"
        orig_disk_bytes = img07_path.read_bytes()
        default_pages = load_document_pages(img07_path)
        self.assertEqual(default_pages[0].image_bytes, orig_disk_bytes)
        self.assertEqual(default_pages[0].preprocessing_applied, ())
        self.assertIsNone(default_pages[0].preprocessing_diagnostics)

        pre_pages = load_document_pages(img07_path, preprocess_images=True)
        pre_diag = pre_pages[0].preprocessing_diagnostics
        self.assertIsNotNone(pre_diag)
        self.assertTrue(pre_diag.orientation_reliable)
        self.assertLessEqual(abs(pre_diag.estimated_angle_degrees - (-3.5)), 0.3)
        self.assertGreater(pre_diag.output_width, pre_diag.original_width)
        self.assertGreater(pre_diag.output_height, pre_diag.original_height)
        self.assertEqual(img07_path.read_bytes(), orig_disk_bytes)


class Phase4AutomaticFailoverOrchestrationTests(unittest.TestCase):
    SAMPLE_IMAGE = UNSTRUCTURED_DIR / "images" / "img_01_screenshot_clean.png"

    @staticmethod
    def _shift_dict(
        *,
        shift_date: str = "2026-11-16",
        start_time: str = "09:00",
        end_time: str = "17:00",
        break_minutes: int | None = 30,
        employer_name: str | None = "BrightMart",
        location: str | None = "Store A",
        department: str | None = "sales floor",
        hourly_rate: float | None = 15.0,
        currency: str | None = "USD",
        shift_status: str = "scheduled",
        confidence: str = "high",
        source_page: int = 1,
        source_row: int = 1,
    ) -> dict[str, Any]:
        return {
            "shift_date": shift_date,
            "start_time": start_time,
            "end_time": end_time,
            "break_minutes": break_minutes,
            "employer_name": employer_name,
            "location": location,
            "department": department,
            "hourly_rate": hourly_rate,
            "currency": currency,
            "shift_status": shift_status,
            "confidence": confidence,
            "uncertain_fields": [],
            "source_page": source_page,
            "source_row": source_row,
            "worker_name": None,
        }

    @staticmethod
    def _load_backend_calc():
        spec = importlib.util.spec_from_file_location(
            "shift_calculations", BACKEND_CALC_PATH
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_01_primary_success_without_fallback(self) -> None:
        cfg = ExtractionServiceConfig()
        self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(cfg.resolved_primary_provider, DEFAULT_PRIMARY_PROVIDER)
        self.assertEqual(cfg.resolved_primary_provider, "gemini")
        self.assertEqual(cfg.resolved_primary_model_id, DEFAULT_PRIMARY_MODEL)
        self.assertEqual(cfg.resolved_primary_model_id, "gemini-3.5-flash-lite")
        self.assertEqual(cfg.resolved_fallback_provider, DEFAULT_FALLBACK_PROVIDER)
        self.assertEqual(cfg.resolved_fallback_provider, "nvidia")
        self.assertEqual(cfg.resolved_fallback_model_id, DEFAULT_FALLBACK_MODEL)
        self.assertEqual(
            cfg.resolved_fallback_model_id,
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        )

        primary_calls = 0
        fallback_calls = 0

        def primary_sender(url, headers, payload, timeout):
            nonlocal primary_calls
            primary_calls += 1
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "week_of": "Week of 16 November 2026",
                                            "shifts": [self._shift_dict()],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 900,
                    "candidatesTokenCount": 140,
                    "totalTokenCount": 1040,
                },
            }

        def fallback_sender(url, headers, payload, timeout):
            nonlocal fallback_calls
            fallback_calls += 1
            raise AssertionError("Fallback must not be called when primary succeeds!")

        orchestrator = ExtractionOrchestrator(
            cfg,
            primary_adapter=GeminiExtractionAdapter(
                model_id=DEFAULT_PRIMARY_MODEL,
                api_key="test-gem",
                http_sender=primary_sender,
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                model_id=DEFAULT_FALLBACK_MODEL,
                api_key="test-nvd",
                http_sender=fallback_sender,
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertIsInstance(res, OrchestratedExtractionResult)
        self.assertEqual(primary_calls, 1)
        self.assertEqual(fallback_calls, 0)
        self.assertEqual(res.extraction_status, "complete")
        self.assertTrue(res.succeeded)
        self.assertTrue(res.is_complete)
        self.assertFalse(res.fallback_triggered)
        self.assertEqual(res.active_provider, "gemini")
        self.assertEqual(res.active_model_id, "gemini-3.5-flash-lite")
        self.assertEqual(res.token_usage.total_tokens, 1040)
        self.assertEqual(len(res.shifts), 1)
        self.assertEqual(res.shifts[0].confirmation_status, "needs_review")
        self.assertTrue(res.shifts[0].requires_worker_confirmation)
        self.assertFalse(res.shifts[0].eligible_for_bulk_confirmation)

    def test_02_transient_primary_failure_followed_by_successful_retry(self) -> None:
        calls = {"primary": 0, "fallback": 0}
        sleeps: list[float] = []

        def primary_sender(url, headers, payload, timeout):
            calls["primary"] += 1
            if calls["primary"] == 1:
                raise ProviderRequestError(
                    "HTTP 429 Too Many Requests", status_code=429, is_transient=True
                )
            if calls["primary"] == 2:
                raise ProviderRequestError(
                    "HTTP 503 Service Unavailable", status_code=503, is_transient=True
                )
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "week_of": "Week of 16 November 2026",
                                            "shifts": [self._shift_dict()],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 800,
                    "candidatesTokenCount": 120,
                    "totalTokenCount": 920,
                },
            }

        def fallback_sender(*_args):
            calls["fallback"] += 1
            raise AssertionError("Fallback must not be called when primary retry succeeds")

        cfg = ExtractionServiceConfig(
            primary_max_retries=2, retry_backoff_seconds=1.0
        )
        orchestrator = ExtractionOrchestrator(
            cfg,
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
            sleep_fn=sleeps.append,
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(calls["primary"], 3)
        self.assertEqual(calls["fallback"], 0)
        self.assertEqual(sleeps, [1.0, 2.0])
        self.assertTrue(res.is_complete)
        self.assertFalse(res.fallback_triggered)
        self.assertEqual(res.request_attempts, 3)
        self.assertEqual(res.attempt_history[0]["failure_category"], "rate_limit_429")
        self.assertEqual(res.attempt_history[1]["failure_category"], "transient_http_5xx")
        self.assertTrue(res.attempt_history[2]["succeeded"])

    def test_03_primary_retries_exhausted_followed_by_fallback_success(self) -> None:
        calls = {"primary": 0, "fallback": 0}
        sleeps: list[float] = []

        def primary_sender(*_args):
            calls["primary"] += 1
            raise ProviderRequestError(
                "HTTP 503 Upstream overloaded", status_code=503, is_transient=True
            )

        def fallback_sender(*_args):
            calls["fallback"] += 1
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "week_of": "Week of 16 November 2026",
                                    "shifts": [
                                        self._shift_dict(
                                            employer_name="Harbor Bistro",
                                            location="Harbor Main",
                                            hourly_rate=16.5,
                                        )
                                    ],
                                }
                            ),
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 1100,
                    "completion_tokens": 350,
                    "completion_tokens_details": {"reasoning_tokens": 150},
                    "total_tokens": 1450,
                },
            }

        cfg = ExtractionServiceConfig(
            primary_max_retries=2, fallback_max_retries=1, retry_backoff_seconds=0.5
        )
        orchestrator = ExtractionOrchestrator(
            cfg,
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
            sleep_fn=sleeps.append,
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(calls["primary"], 3)
        self.assertEqual(calls["fallback"], 1)
        self.assertEqual(sleeps, [0.5, 1.0])
        self.assertTrue(res.is_complete)
        self.assertTrue(res.fallback_triggered)
        self.assertEqual(res.fallback_trigger_category, "transient_http_5xx")
        self.assertIn("HTTP 503", res.fallback_trigger_reason or "")
        self.assertEqual(res.active_provider, "nvidia")
        self.assertEqual(res.active_model_id, DEFAULT_NVIDIA_MODEL)
        self.assertEqual(res.request_attempts, 4)
        self.assertEqual(res.token_usage.total_tokens, 1450)
        self.assertEqual(res.shifts[0].normalised.employer_name, "Harbor Bistro")

    def test_04_invalid_json_followed_by_fallback_success(self) -> None:
        calls = {"primary": 0, "fallback": 0}

        def primary_sender(*_args):
            calls["primary"] += 1
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "{broken json payload"}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 500,
                    "candidatesTokenCount": 30,
                    "totalTokenCount": 530,
                },
            }

        def fallback_sender(*_args):
            calls["fallback"] += 1
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "week_of": "Week of 16 November 2026",
                                    "shifts": [self._shift_dict()],
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 900, "completion_tokens": 200, "total_tokens": 1100},
            }

        orchestrator = ExtractionOrchestrator(
            ExtractionServiceConfig(primary_max_retries=1, retry_backoff_seconds=0.0),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(calls["primary"], 2)
        self.assertEqual(calls["fallback"], 1)
        self.assertTrue(res.is_complete)
        self.assertTrue(res.fallback_triggered)
        self.assertEqual(
            res.fallback_trigger_category, "malformed_or_empty_response"
        )
        self.assertEqual(res.active_provider, "nvidia")
        self.assertEqual(res.token_usage.total_tokens, 2 * 530 + 1100)

    def test_05_both_providers_failing_requires_manual_entry_and_not_empty_schedule(
        self,
    ) -> None:
        calls = {"primary": 0, "fallback": 0}

        def primary_sender(*_args):
            calls["primary"] += 1
            raise ProviderRequestError(
                "Network error calling Gemini: connection reset", is_transient=True
            )

        def fallback_sender(*_args):
            calls["fallback"] += 1
            raise ProviderRequestError(
                "HTTP 502 Bad Gateway", status_code=502, is_transient=True
            )

        orchestrator = ExtractionOrchestrator(
            ExtractionServiceConfig(
                primary_max_retries=1, fallback_max_retries=1, retry_backoff_seconds=0.0
            ),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(calls["primary"], 2)
        self.assertEqual(calls["fallback"], 2)
        self.assertEqual(res.extraction_status, "failed")
        self.assertFalse(res.succeeded)
        self.assertTrue(res.is_failed)
        self.assertFalse(res.is_complete)
        self.assertFalse(res.is_partial)
        self.assertFalse(res.is_empty_schedule)
        self.assertTrue(res.manual_entry_required)
        self.assertIn("connection reset", res.manual_entry_reason or "")
        self.assertIn("HTTP 502", res.manual_entry_reason or "")
        self.assertEqual(res.shifts, [])
        self.assertEqual(res.primary_failure_category, "timeout_or_connection_error")
        self.assertEqual(res.fallback_failure_category, "transient_http_5xx")

    def test_06_invalid_or_missing_primary_credentials_failover_without_primary_retry(
        self,
    ) -> None:
        sleeps: list[float] = []
        captured_fallback_headers: dict[str, str] = {}

        def fallback_sender(url, headers, payload, timeout):
            captured_fallback_headers.update(headers)
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "week_of": "Week of 16 November 2026",
                                    "shifts": [self._shift_dict()],
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 800, "completion_tokens": 180, "total_tokens": 980},
            }

        # Case A: Missing GEMINI_API_KEY -> primary makes 1 attempt, no retries, fails over to NVIDIA
        orig_is_file = Path.is_file
        with patch.dict(os.environ, {}, clear=True), patch.object(
            Path,
            "is_file",
            autospec=True,
            side_effect=lambda p: False if p.name == ".env" else orig_is_file(p),
        ):
            orchestrator_missing = ExtractionOrchestrator(
                ExtractionServiceConfig(primary_max_retries=2, retry_backoff_seconds=2.0),
                primary_adapter=GeminiExtractionAdapter(api_key=None),
                fallback_adapter=NvidiaExtractionAdapter(
                    api_key="fallback-fixture-key", http_sender=fallback_sender
                ),
                sleep_fn=sleeps.append,
            )
            res_missing = orchestrator_missing.extract_file(self.SAMPLE_IMAGE)

        self.assertEqual(sleeps, [])
        self.assertTrue(res_missing.is_complete)
        self.assertTrue(res_missing.fallback_triggered)
        self.assertEqual(res_missing.primary_failure_category, "missing_credentials")
        self.assertEqual(res_missing.request_attempts, 2)
        self.assertNotIn("x-goog-api-key", captured_fallback_headers)
        self.assertEqual(
            captured_fallback_headers.get("Authorization"),
            "Bearer fallback-fixture-key",
        )

        # Case B: HTTP 401 on primary -> short-circuits retries (1 attempt), fails over immediately
        primary_401_calls = 0

        def primary_401(*_args):
            nonlocal primary_401_calls
            primary_401_calls += 1
            raise ProviderRequestError(
                "HTTP 401 Unauthorized: invalid key", status_code=401, is_transient=False
            )

        sleeps.clear()
        orchestrator_401 = ExtractionOrchestrator(
            ExtractionServiceConfig(primary_max_retries=2, retry_backoff_seconds=2.0),
            primary_adapter=GeminiExtractionAdapter(
                api_key="bad-gem-fixture", http_sender=primary_401
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="fallback-fixture-key", http_sender=fallback_sender
            ),
            sleep_fn=sleeps.append,
        )
        res_401 = orchestrator_401.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(primary_401_calls, 1)
        self.assertEqual(sleeps, [])
        self.assertTrue(res_401.is_complete)
        self.assertTrue(res_401.fallback_triggered)
        self.assertEqual(res_401.primary_failure_category, "authentication_error")

    def test_07_fallback_disabled_stops_after_primary_failure(self) -> None:
        calls = {"primary": 0, "fallback": 0}

        def primary_sender(*_args):
            calls["primary"] += 1
            raise ProviderRequestError(
                "HTTP 500 Internal Server Error", status_code=500, is_transient=True
            )

        def fallback_sender(*_args):
            calls["fallback"] += 1
            raise AssertionError("Fallback must NEVER run when fallback_enabled=False")

        cfg = ExtractionServiceConfig(
            fallback_enabled=False,
            primary_max_retries=1,
            retry_backoff_seconds=0.0,
        )
        orchestrator = ExtractionOrchestrator(
            cfg,
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertIsNone(orchestrator.fallback_adapter)
        self.assertEqual(calls["primary"], 2)
        self.assertEqual(calls["fallback"], 0)
        self.assertFalse(res.fallback_triggered)
        self.assertTrue(res.is_failed)
        self.assertFalse(res.is_empty_schedule)
        self.assertTrue(res.manual_entry_required)

    def test_08_missing_fallback_credentials_fails_cleanly_without_fallback_retry(
        self,
    ) -> None:
        primary_calls = 0

        def primary_sender(*_args):
            nonlocal primary_calls
            primary_calls += 1
            raise ProviderRequestError(
                "HTTP 503 Unavailable", status_code=503, is_transient=True
            )

        orig_is_file = Path.is_file
        with patch.dict(os.environ, {}, clear=True), patch.object(
            Path,
            "is_file",
            autospec=True,
            side_effect=lambda p: False if p.name == ".env" else orig_is_file(p),
        ):
            orchestrator = ExtractionOrchestrator(
                ExtractionServiceConfig(
                    primary_max_retries=1,
                    fallback_max_retries=2,
                    retry_backoff_seconds=0.0,
                ),
                primary_adapter=GeminiExtractionAdapter(
                    api_key="test-gem", http_sender=primary_sender
                ),
                fallback_adapter=NvidiaExtractionAdapter(api_key=None),
            )
            res = orchestrator.extract_file(self.SAMPLE_IMAGE)

        self.assertEqual(primary_calls, 2)
        self.assertTrue(res.fallback_triggered)
        self.assertEqual(res.request_attempts, 3)
        self.assertEqual(res.fallback_failure_category, "missing_credentials")
        self.assertTrue(res.is_failed)
        self.assertFalse(res.is_empty_schedule)
        self.assertTrue(res.manual_entry_required)
        self.assertIn("NVIDIA_API_KEY", res.fallback_failure_reason or "")
        self.assertIn("HTTP 503", res.primary_failure_reason or "")

    def test_09_valid_extraction_with_missing_financial_fields_does_not_failover(
        self,
    ) -> None:
        fallback_calls = 0

        def primary_sender(*_args):
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "week_of": "Week of 16 November 2026",
                                            "shifts": [
                                                self._shift_dict(
                                                    break_minutes=None,
                                                    hourly_rate=None,
                                                    currency=None,
                                                )
                                            ],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 700,
                    "candidatesTokenCount": 110,
                    "totalTokenCount": 810,
                },
            }

        def fallback_sender(*_args):
            nonlocal fallback_calls
            fallback_calls += 1
            raise AssertionError("Legitimately missing fields must NOT trigger failover!")

        orchestrator = ExtractionOrchestrator(
            ExtractionServiceConfig(),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(fallback_calls, 0)
        self.assertFalse(res.fallback_triggered)
        self.assertTrue(res.is_complete)
        self.assertEqual(len(res.shifts), 1)
        s = res.shifts[0]
        self.assertIsNone(s.normalised.break_minutes)
        self.assertIsNone(s.normalised.hourly_rate)
        self.assertIsNone(s.normalised.currency)
        self.assertEqual(s.confirmation_status, "needs_review")
        self.assertIn("missing_money_field:break_minutes", s.review_reasons)
        self.assertIn("missing_money_field:hourly_rate", s.review_reasons)
        self.assertIn("missing_money_field:currency", s.review_reasons)

    def test_10_conflicting_duplicates_preserved_and_require_worker_resolution(
        self,
    ) -> None:
        def primary_sender(*_args):
            raise ProviderRequestError(
                "HTTP 429 rate limited", status_code=429, is_transient=True
            )

        def fallback_sender(*_args):
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "week_of": "Week of 16 November 2026",
                                    "shifts": [
                                        self._shift_dict(
                                            shift_date="2026-11-20",
                                            start_time="13:00",
                                            end_time="21:00",
                                            break_minutes=45,
                                            hourly_rate=14.25,
                                            currency="GBP",
                                            source_row=4,
                                        ),
                                        self._shift_dict(
                                            shift_date="2026-11-20",
                                            start_time="13:00",
                                            end_time="21:00",
                                            break_minutes=0,
                                            hourly_rate=16.00,
                                            currency="GBP",
                                            source_row=5,
                                        ),
                                    ],
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 900, "completion_tokens": 250, "total_tokens": 1150},
            }

        orchestrator = ExtractionOrchestrator(
            ExtractionServiceConfig(primary_max_retries=0, retry_backoff_seconds=0.0),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertTrue(res.fallback_triggered)
        self.assertIsNotNone(res.document_result)
        self.assertEqual(res.document_result.conflicting_duplicate_count, 2)
        self.assertEqual(len(res.shifts), 2)
        self.assertTrue(all(s.requires_conflict_resolution for s in res.shifts))

        det = _evaluate_deterministic_validation(
            [(res.file_name, rec) for rec in res.shifts]
        )
        self.assertEqual(det["unresolved_conflict_records"], 2)
        self.assertEqual(
            det["if_individually_confirmed"]["eligible_for_earnings_count"], 0
        )

    def test_11_unconfirmed_high_confidence_shifts_excluded_from_earnings(self) -> None:
        def primary_sender(*_args):
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "week_of": "Week of 16 November 2026",
                                            "shifts": [
                                                self._shift_dict(confidence="high")
                                            ],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 700,
                    "candidatesTokenCount": 130,
                    "totalTokenCount": 830,
                },
            }

        orchestrator = ExtractionOrchestrator(
            ExtractionServiceConfig(fallback_enabled=False),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        shift = res.shifts[0]
        self.assertEqual(shift.confidence, "high")
        self.assertEqual(shift.confirmation_status, "needs_review")
        self.assertTrue(shift.requires_worker_confirmation)
        self.assertTrue(shift.requires_individual_review)
        self.assertFalse(shift.eligible_for_bulk_confirmation)

        calc_mod = self._load_backend_calc()
        out = calc_mod.calculate_shifts(
            {
                "worker_id": "W_HIGH_CONF",
                "shifts": [
                    {
                        "shift_id": "S1",
                        "shift_date": shift.effective_values().shift_date,
                        "start_time": shift.effective_values().start_time,
                        "end_time": shift.effective_values().end_time,
                        "break_minutes": shift.effective_values().break_minutes,
                        "employer_name": shift.effective_values().employer_name,
                        "location": shift.effective_values().location,
                        "hourly_rate": shift.effective_values().hourly_rate,
                        "currency": shift.effective_values().currency,
                        "shift_status": shift.effective_values().shift_status,
                        "confirmation_status": shift.confirmation_status,
                    }
                ],
            },
            flag_messages=calc_mod.load_flag_messages(str(FLAG_TYPES_PATH)),
            known_locations=calc_mod.load_known_locations(str(BACKEND_LOCATIONS_PATH)),
            rules=calc_mod.load_rules(str(BACKEND_RULES_PATH)),
        )
        self.assertEqual(out["shifts"][0]["earnings_status"], "needs_review")
        self.assertFalse(out["shifts"][0]["eligible_for_earnings"])
        self.assertIsNone(out["weekly_summary"][0]["gross_earnings"])

    def test_12_credential_and_reasoning_redaction_across_both_providers(self) -> None:
        primary_secret = "synthetic-gem-" + "fixture-987654"
        fallback_secret = "synthetic-nvd-" + "fixture-123456"
        sensitive_reasoning = "SENSITIVE_CHAIN_OF_THOUGHT_DO_NOT_LOG_SALARY_999"

        def primary_urlopen(req, timeout=120):
            raise urllib.error.HTTPError(
                req.full_url,
                503,
                f"Service unavailable key={primary_secret}",
                hdrs=None,
                fp=io.BytesIO(f"Bad header {primary_secret}".encode("utf-8")),
            )

        def fallback_sender(url, headers, payload, timeout):
            # Fallback must never receive primary's credential
            self.assertNotIn(primary_secret, json.dumps(headers))
            self.assertNotIn(primary_secret, json.dumps(payload))
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": sensitive_reasoning,
                            "content": json.dumps(
                                {
                                    "week_of": "Week of 16 November 2026",
                                    "shifts": [self._shift_dict()],
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 900, "completion_tokens": 200, "total_tokens": 1100},
            }

        with patch("urllib.request.urlopen", side_effect=primary_urlopen):
            orchestrator = ExtractionOrchestrator(
                ExtractionServiceConfig(
                    primary_max_retries=0, retry_backoff_seconds=0.0
                ),
                primary_adapter=GeminiExtractionAdapter(api_key=primary_secret),
                fallback_adapter=NvidiaExtractionAdapter(
                    api_key=fallback_secret, http_sender=fallback_sender
                ),
            )
            with self.assertLogs("ai_extraction.orchestrator", level="INFO") as log_ctx:
                res = orchestrator.extract_file(self.SAMPLE_IMAGE)

        joined_logs = "\n".join(log_ctx.output)
        summary_json = json.dumps(res.to_public_summary())
        payload_json = json.dumps(res.to_payload_dict())

        for haystack in (joined_logs, summary_json, payload_json):
            self.assertNotIn(primary_secret, haystack)
            self.assertNotIn(fallback_secret, haystack)
            self.assertNotIn(sensitive_reasoning, haystack)
        self.assertIn("[REDACTED]", res.primary_failure_reason or "")

    def test_13_bounded_retry_backoff_and_per_attempt_timeout_enforcement(self) -> None:
        observed_timeouts: list[float | None] = []
        sleeps: list[float] = []

        def primary_sender(url, headers, payload, timeout):
            observed_timeouts.append(timeout)
            raise ProviderRequestError(
                "Timeout calling primary", is_transient=True
            )

        def fallback_sender(url, headers, payload, timeout):
            observed_timeouts.append(timeout)
            raise ProviderRequestError(
                "HTTP 503 fallback error", status_code=503, is_transient=True
            )

        cfg = ExtractionServiceConfig(
            primary_max_retries=2,
            fallback_max_retries=1,
            retry_backoff_seconds=1.5,
            per_attempt_timeout_seconds=12.0,
            total_deadline_seconds=100.0,
        )
        orchestrator = ExtractionOrchestrator(
            cfg,
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
            sleep_fn=sleeps.append,
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        # Primary: 1 + 2 = 3 attempts (sleeps 1.5, 3.0); Fallback: 1 + 1 = 2 attempts (sleep 1.5)
        self.assertEqual(len(observed_timeouts), 5)
        self.assertTrue(all(t is not None and t <= 12.0 for t in observed_timeouts))
        self.assertEqual(sleeps, [1.5, 3.0, 1.5])
        self.assertEqual(res.request_attempts, 5)
        self.assertTrue(res.is_failed)

    def test_14_no_duplicate_shifts_introduced_across_retries_or_failover(self) -> None:
        primary_calls = 0

        partial_one = (
            '{\n  "week_of": "Week of 16 November 2026",\n  "shifts": [\n'
            + json.dumps(self._shift_dict(shift_date="2026-11-16", source_row=1))
            + ',\n    {"shift_date": "2026-11-17"'
        )
        partial_two = (
            '{\n  "week_of": "Week of 16 November 2026",\n  "shifts": [\n'
            + json.dumps(self._shift_dict(shift_date="2026-11-16", source_row=1))
            + ",\n"
            + json.dumps(self._shift_dict(shift_date="2026-11-17", source_row=2))
            + ',\n    {"shift_date": "2026-11-18"'
        )

        def primary_sender(*_args):
            nonlocal primary_calls
            primary_calls += 1
            return {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {
                            "parts": [
                                {"text": partial_one if primary_calls == 1 else partial_two}
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 700,
                    "candidatesTokenCount": 200,
                    "totalTokenCount": 900,
                },
            }

        def fallback_sender(*_args):
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "week_of": "Week of 16 November 2026",
                                    "shifts": [
                                        self._shift_dict(
                                            shift_date="2026-11-16", source_row=1
                                        ),
                                        self._shift_dict(
                                            shift_date="2026-11-17", source_row=2
                                        ),
                                        self._shift_dict(
                                            shift_date="2026-11-18", source_row=3
                                        ),
                                    ],
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200},
            }

        orchestrator = ExtractionOrchestrator(
            ExtractionServiceConfig(primary_max_retries=1, retry_backoff_seconds=0.0),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        self.assertTrue(res.is_complete)
        self.assertTrue(res.fallback_triggered)
        self.assertEqual(res.active_provider, "nvidia")
        # Exactly the 3 fallback shifts (never merged with primary's 1 + 2 partial shifts)
        self.assertEqual(
            [s.normalised.shift_date for s in res.shifts],
            ["2026-11-16", "2026-11-17", "2026-11-18"],
        )

    def test_15_partial_extraction_and_recovery_explicitly_represented(self) -> None:
        partial_payload = (
            '{\n  "week_of": "Week of 16 November 2026",\n  "shifts": [\n'
            + json.dumps(self._shift_dict(shift_date="2026-11-16", source_row=1))
            + ",\n"
            + json.dumps(self._shift_dict(shift_date="2026-11-17", source_row=2))
            + ',\n    {"shift_date": "2026-11-18", "start_time": "09:'
        )

        def primary_sender(*_args):
            return {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": partial_payload}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 800,
                    "candidatesTokenCount": 300,
                    "totalTokenCount": 1100,
                },
            }

        def fallback_sender(*_args):
            raise ProviderRequestError(
                "HTTP 503 Unavailable", status_code=503, is_transient=True
            )

        orchestrator = ExtractionOrchestrator(
            ExtractionServiceConfig(
                primary_max_retries=0, fallback_max_retries=0, retry_backoff_seconds=0.0
            ),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
        )
        image_bytes = self.SAMPLE_IMAGE.read_bytes()
        res = orchestrator.extract_bytes(
            image_bytes, file_name="img_01_screenshot_clean.png"
        )
        self.assertEqual(res.extraction_status, "partial")
        self.assertTrue(res.is_partial)
        self.assertFalse(res.is_complete)
        self.assertFalse(res.succeeded)
        self.assertFalse(res.is_failed)
        self.assertFalse(res.is_empty_schedule)
        self.assertTrue(res.manual_entry_required)
        self.assertTrue(res.fallback_triggered)
        self.assertEqual(len(res.shifts), 2)
        self.assertTrue(all(s.partially_recovered for s in res.shifts))
        self.assertTrue(all(s.confidence == "low" for s in res.shifts))
        self.assertTrue(
            all(s.confirmation_status == "needs_review" for s in res.shifts)
        )
        summary = res.to_public_summary()
        self.assertFalse(summary["is_complete"])
        self.assertTrue(summary["is_partial"])

    def test_16_exhausted_overall_processing_deadline_aborts_retries_and_failover(
        self,
    ) -> None:
        now = {"t": 100.0}
        observed_timeouts: list[float | None] = []
        primary_calls = 0
        fallback_calls = 0

        def fake_clock() -> float:
            return now["t"]

        def fake_sleep(secs: float) -> None:
            now["t"] += secs

        def primary_sender(url, headers, payload, timeout):
            nonlocal primary_calls
            primary_calls += 1
            observed_timeouts.append(timeout)
            if primary_calls == 1:
                now["t"] += 6.0  # Clock now at 106.0 (4.0s left before 110.0 deadline)
                raise ProviderRequestError(
                    "HTTP 503 Primary temporary outage", status_code=503, is_transient=True
                )
            now["t"] += 2.5  # After 2.0s sleep -> 108.0 + 2.5 = 110.5 (exceeds 110.0 deadline)
            raise ProviderRequestError(
                "Timeout calling primary", is_transient=True
            )

        def fallback_sender(*_args):
            nonlocal fallback_calls
            fallback_calls += 1
            raise AssertionError("Fallback must not start after total deadline is exhausted")

        cfg = ExtractionServiceConfig(
            primary_max_retries=2,
            fallback_max_retries=2,
            retry_backoff_seconds=2.0,
            per_attempt_timeout_seconds=8.0,
            total_deadline_seconds=10.0,
        )
        orchestrator = ExtractionOrchestrator(
            cfg,
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_sender
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_sender
            ),
            clock_fn=fake_clock,
            sleep_fn=fake_sleep,
        )
        res = orchestrator.extract_file(self.SAMPLE_IMAGE)
        # Attempt 1 timeout = min(8.0, 10.0) = 8.0; Attempt 2 timeout = min(8.0, 2.0) = 2.0
        self.assertEqual(observed_timeouts, [8.0, 2.0])
        self.assertEqual(primary_calls, 2)
        self.assertEqual(fallback_calls, 0)
        self.assertTrue(res.deadline_exhausted)
        self.assertFalse(res.fallback_triggered)
        self.assertTrue(res.is_failed)
        self.assertFalse(res.is_empty_schedule)
        self.assertTrue(res.manual_entry_required)
        self.assertIn("deadline exhausted", (res.manual_entry_reason or "").lower())

    def test_17_suspicious_empty_shifts_triggers_failover_and_distinguishes_corroborated_empty_schedule(
        self,
    ) -> None:
        # Subcase A: Primary returns uncontextualised {"week_of": null, "shifts": []} ->
        # retries & fails over to Fallback, which recovers the real shifts.
        prim_calls_a = 0
        fb_calls_a = 0

        def prim_empty_a(*_args):
            nonlocal prim_calls_a
            prim_calls_a += 1
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": json.dumps({"week_of": None, "shifts": []})}]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 600,
                    "candidatesTokenCount": 15,
                    "totalTokenCount": 615,
                },
            }

        def fb_valid_a(*_args):
            nonlocal fb_calls_a
            fb_calls_a += 1
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "week_of": "Week of 16 November 2026",
                                    "shifts": [self._shift_dict()],
                                }
                            ),
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 800,
                    "completion_tokens": 180,
                    "total_tokens": 980,
                },
            }

        orch_a = ExtractionOrchestrator(
            ExtractionServiceConfig(primary_max_retries=1, retry_backoff_seconds=0.0),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=prim_empty_a
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fb_valid_a
            ),
        )
        res_a = orch_a.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(prim_calls_a, 2)
        self.assertEqual(fb_calls_a, 1)
        self.assertEqual(res_a.extraction_status, "complete")
        self.assertFalse(res_a.is_empty_schedule)
        self.assertTrue(res_a.fallback_triggered)
        self.assertEqual(res_a.fallback_trigger_category, "suspicious_empty_shifts")
        self.assertEqual(res_a.active_provider, "nvidia")
        self.assertEqual(len(res_a.shifts), 1)

        # Subcase B: Both Primary & Fallback return uncontextualised {"week_of": null, "shifts": []} ->
        # MUST fail rather than misreporting a genuinely empty schedule.
        def fb_empty_uncontextualised(*_args):
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"week_of": None, "shifts": []}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 800, "completion_tokens": 15, "total_tokens": 815},
            }

        orch_b = ExtractionOrchestrator(
            ExtractionServiceConfig(
                primary_max_retries=0, fallback_max_retries=0, retry_backoff_seconds=0.0
            ),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=prim_empty_a
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fb_empty_uncontextualised
            ),
        )
        res_b = orch_b.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(res_b.extraction_status, "failed")
        self.assertFalse(res_b.succeeded)
        self.assertTrue(res_b.is_failed)
        self.assertFalse(res_b.is_empty_schedule)
        self.assertTrue(res_b.manual_entry_required)

        # Subcase C: Both Primary & Fallback independently return contextualised 0-shift roster
        # responses (colleague filtered out) -> corroborated empty schedule requiring worker confirmation.
        colleague_payload = {
            "week_of": "Week of 16 November 2026",
            "shifts": [
                {
                    **self._shift_dict(),
                    "worker_name": "James Okoro",
                }
            ],
        }

        def prim_corroborated_c(*_args):
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(colleague_payload)}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 700,
                    "candidatesTokenCount": 90,
                    "totalTokenCount": 790,
                },
            }

        def fb_corroborated_c(*_args):
            return {
                "model": DEFAULT_NVIDIA_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(colleague_payload),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 800, "completion_tokens": 90, "total_tokens": 890},
            }

        orch_c = ExtractionOrchestrator(
            ExtractionServiceConfig(
                primary_max_retries=0, fallback_max_retries=0, retry_backoff_seconds=0.0
            ),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=prim_corroborated_c
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fb_corroborated_c
            ),
        )
        res_c = orch_c.extract_file(self.SAMPLE_IMAGE, target_worker="Maria Santos")
        self.assertEqual(res_c.extraction_status, "complete")
        self.assertTrue(res_c.succeeded)
        self.assertTrue(res_c.is_complete)
        self.assertTrue(res_c.is_empty_schedule)
        self.assertTrue(res_c.manual_entry_required)
        self.assertEqual(res_c.shifts, [])

    def test_18_mixed_valid_and_rejected_records_never_reported_as_complete_and_preserve_safeguards(
        self,
    ) -> None:
        # Response contains 1 valid shift + 1 empty {} record AND also 2 conflicting duplicates
        # in the second scenario to ensure partial results enforce both individual review & conflict blocking.
        mixed_payload = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    self._shift_dict(source_row=1, confidence="high"),
                    {},
                ],
            }
        )

        def primary_mixed(*_args):
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": mixed_payload}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 700,
                    "candidatesTokenCount": 140,
                    "totalTokenCount": 840,
                },
            }

        def fallback_fail(*_args):
            raise ProviderRequestError(
                "HTTP 503 Unavailable", status_code=503, is_transient=True
            )

        orch = ExtractionOrchestrator(
            ExtractionServiceConfig(
                primary_max_retries=0, fallback_max_retries=0, retry_backoff_seconds=0.0
            ),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=primary_mixed
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fallback_fail
            ),
        )
        res = orch.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(res.extraction_status, "partial")
        self.assertFalse(res.is_complete)
        self.assertTrue(res.is_partial)
        self.assertFalse(res.succeeded)
        self.assertTrue(res.manual_entry_required)
        self.assertTrue(res.fallback_triggered)
        self.assertEqual(res.fallback_trigger_category, "partially_invalid_response")
        self.assertIn("invalid/empty", res.manual_entry_reason or "")
        self.assertEqual(len(res.shifts), 1)
        surviving = res.shifts[0]
        self.assertEqual(surviving.confidence, "low")
        self.assertIn("partial_extraction_with_rejected_records", surviving.review_reasons)
        self.assertEqual(surviving.confirmation_status, "needs_review")
        self.assertFalse(surviving.eligible_for_bulk_confirmation)

        # Partial shifts remain excluded from backend earnings unless explicitly confirmed
        calc_mod = self._load_backend_calc()
        out_unconf = calc_mod.calculate_shifts(
            res.to_backend_calculation_payload(worker_id="W_MIXED"),
            flag_messages=calc_mod.load_flag_messages(str(FLAG_TYPES_PATH)),
            known_locations=calc_mod.load_known_locations(str(BACKEND_LOCATIONS_PATH)),
            rules=calc_mod.load_rules(str(BACKEND_RULES_PATH)),
        )
        self.assertFalse(out_unconf["shifts"][0]["eligible_for_earnings"])
        self.assertIsNone(out_unconf["weekly_summary"][0]["gross_earnings"])

        # Mixed response containing conflicting duplicates in surviving partial shifts must stay blocked
        mixed_conflict_payload = json.dumps(
            {
                "week_of": "Week of 16 November 2026",
                "shifts": [
                    self._shift_dict(
                        shift_date="2026-11-20",
                        start_time="13:00",
                        end_time="21:00",
                        break_minutes=45,
                        hourly_rate=14.25,
                        currency="GBP",
                        source_row=1,
                    ),
                    self._shift_dict(
                        shift_date="2026-11-20",
                        start_time="13:00",
                        end_time="21:00",
                        break_minutes=0,
                        hourly_rate=16.0,
                        currency="GBP",
                        source_row=2,
                    ),
                    {},
                ],
            }
        )
        orch_conf = ExtractionOrchestrator(
            ExtractionServiceConfig(
                primary_max_retries=0, fallback_enabled=False, retry_backoff_seconds=0.0
            ),
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem",
                http_sender=lambda *_args: {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": mixed_conflict_payload}]},
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 700,
                        "candidatesTokenCount": 200,
                        "totalTokenCount": 900,
                    },
                },
            ),
        )
        res_conf = orch_conf.extract_file(self.SAMPLE_IMAGE)
        self.assertEqual(res_conf.extraction_status, "partial")
        out_sim = calc_mod.calculate_shifts(
            res_conf.to_backend_calculation_payload(
                worker_id="W_MIXED_CONFLICT", simulate_individual_confirmation=True
            ),
            flag_messages=calc_mod.load_flag_messages(str(FLAG_TYPES_PATH)),
            known_locations=calc_mod.load_known_locations(str(BACKEND_LOCATIONS_PATH)),
            rules=calc_mod.load_rules(str(BACKEND_RULES_PATH)),
        )
        self.assertEqual(
            sum(1 for s in out_sim["shifts"] if s["eligible_for_earnings"]), 0
        )

    def test_19_deadline_enforcement_includes_preprocessing_time(self) -> None:
        now = {"t": 100.0}
        primary_calls = 0
        fallback_calls = 0

        def fake_clock() -> float:
            return now["t"]

        def slow_load_pages(*_args, **_kwargs):
            now["t"] += 11.0  # Simulate slow PDF rasterization / image deskewing (> 10s deadline)
            return load_document_pages(self.SAMPLE_IMAGE)

        def fail_if_called(*_args):
            nonlocal primary_calls
            primary_calls += 1
            raise AssertionError("Primary must not be called once preprocessing exhausts deadline")

        def fb_fail_if_called(*_args):
            nonlocal fallback_calls
            fallback_calls += 1
            raise AssertionError("Fallback must not be called once deadline is exhausted")

        cfg = ExtractionServiceConfig(
            total_deadline_seconds=10.0,
            per_attempt_timeout_seconds=8.0,
        )
        orch = ExtractionOrchestrator(
            cfg,
            primary_adapter=GeminiExtractionAdapter(
                api_key="test-gem", http_sender=fail_if_called
            ),
            fallback_adapter=NvidiaExtractionAdapter(
                api_key="test-nvd", http_sender=fb_fail_if_called
            ),
            clock_fn=fake_clock,
        )
        with patch(
            "ai_extraction.orchestrator.load_document_pages",
            side_effect=slow_load_pages,
        ):
            res = orch.extract_file(self.SAMPLE_IMAGE)

        self.assertEqual(primary_calls, 0)
        self.assertEqual(fallback_calls, 0)
        self.assertTrue(res.deadline_exhausted)
        self.assertTrue(res.is_failed)
        self.assertFalse(res.is_empty_schedule)
        self.assertTrue(res.manual_entry_required)
        self.assertEqual(res.primary_failure_category, "deadline_exhausted")
        self.assertGreaterEqual(res.preprocessing_time_seconds, 11.0)
        self.assertGreaterEqual(res.processing_time_seconds, 11.0)

    def test_20_invalid_configuration_values_unsupported_providers_and_log_sanitization(
        self,
    ) -> None:
        # Unsupported providers
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(primary_provider="anthropic")
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(fallback_provider="openai")

        # Invalid numeric configuration bounds
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(primary_max_retries=-1)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(fallback_max_retries=-1)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(per_attempt_timeout_seconds=0.0)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(total_deadline_seconds=-1.0)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(max_tokens=0)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(reasoning_budget=-5)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(temperature=-0.1)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(temperature=2.5)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(temperature=math.nan)
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(pdf_dpi=50)

        # Identical primary + fallback provider/model must be rejected when fallback is enabled
        with self.assertRaises(ValueError):
            ExtractionServiceConfig(
                primary_provider="gemini",
                fallback_enabled=True,
                fallback_provider="gemini",
            )
        # Same provider as fallback IS allowed cleanly when explicitly disabled
        cfg_disabled = ExtractionServiceConfig(
            primary_provider="nvidia",
            fallback_enabled=False,
            fallback_provider=None,
        )
        self.assertIsNone(cfg_disabled.resolved_fallback_provider)

        # Env loader selects distinct opposite default fallback when primary is nvidia
        with patch.dict(
            os.environ,
            {"AI_EXTRACTION_PRIMARY_PROVIDER": "nvidia"},
            clear=True,
        ):
            env_cfg = ExtractionServiceConfig.from_env()
            self.assertEqual(env_cfg.resolved_primary_provider, "nvidia")
            self.assertEqual(env_cfg.resolved_fallback_provider, "gemini")
            self.assertEqual(env_cfg.resolved_fallback_model_id, "gemini-3.5-flash-lite")

        # Operational logs must exclude local filesystem paths, raw responses, reasoning text, and shifts
        sensitive_shift_employer = "SUPER_PRIVATE_CLINIC_EMPLOYER_777"
        sensitive_reasoning = "INTERNAL_REASONING_CHAIN_XYZ_888"
        with tempfile.TemporaryDirectory(prefix="secret_dir_marker_") as tmp:
            img_copy = Path(tmp) / "worker_schedule.png"
            img_copy.write_bytes(self.SAMPLE_IMAGE.read_bytes())

            orch = ExtractionOrchestrator(
                ExtractionServiceConfig(fallback_enabled=False),
                primary_adapter=GeminiExtractionAdapter(
                    api_key="test-gem",
                    http_sender=lambda *_args: {
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {
                                    "parts": [
                                        {
                                            "text": json.dumps(
                                                {
                                                    "week_of": "Week of 16 November 2026",
                                                    "shifts": [
                                                        self._shift_dict(
                                                            employer_name=sensitive_shift_employer
                                                        )
                                                    ],
                                                }
                                            )
                                        }
                                    ]
                                },
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 500,
                            "candidatesTokenCount": 120,
                            "totalTokenCount": 620,
                        },
                    },
                ),
            )
            with self.assertLogs("ai_extraction.orchestrator", level="INFO") as logs:
                res = orch.extract_file(img_copy)

            joined_logs = "\n".join(logs.output)
            log_summary_str = json.dumps(res.to_log_summary())
            self.assertNotIn("secret_dir_marker_", joined_logs)
            self.assertNotIn(sensitive_shift_employer, joined_logs)
            self.assertNotIn(sensitive_reasoning, joined_logs)
            self.assertNotIn(sensitive_shift_employer, log_summary_str)
            self.assertNotIn("shifts", res.to_log_summary())
            self.assertNotIn("raw_response", res.to_log_summary())
            self.assertNotIn("reasoning_text", res.to_log_summary())

            # Missing file warning also excludes local directory path
            missing_file = Path(tmp) / "does_not_exist.png"
            with self.assertLogs("ai_extraction.orchestrator", level="WARNING") as err_logs:
                err_res = orch.extract_file(missing_file)
            self.assertTrue(err_res.is_failed)
            self.assertNotIn("secret_dir_marker_", "\n".join(err_logs.output))


if __name__ == "__main__":
    unittest.main()
