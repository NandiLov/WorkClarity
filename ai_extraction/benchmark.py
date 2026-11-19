"""Repeatable AI schedule extraction V3 benchmark runner, reporting, and offline replay."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from ai_extraction.orchestrator import run_provider_attempts
from ai_extraction.pdf_utils import (
    DEFAULT_PDF_DPI,
    MissingRenderingDependencyError,
    get_available_image_preprocessing_backend,
    get_available_pdf_rendering_backend,
    load_document_pages,
)
from ai_extraction.prompt import SYSTEM_PROMPT, build_user_prompt
from ai_extraction.providers import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_NVIDIA_MAX_RETRIES,
    DEFAULT_NVIDIA_MAX_TOKENS,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REASONING_BUDGET,
    DEFAULT_NVIDIA_RETRY_BACKOFF,
    DEFAULT_NVIDIA_TEMPERATURE,
    ExtractionAdapter,
    ProviderExtractionRequest,
    RequestAttemptRecord,
    TokenUsage,
    create_adapter,
)
from ai_extraction.schema import (
    CONFIRMATION_CSV_COLUMNS,
    CSV_COLUMNS,
    DocumentExtractionResult,
    ExtractedShiftRecord,
    parse_and_validate_model_json,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
UNSTRUCTURED_DIR = REPO_ROOT / "data_validation" / "test_data" / "unstructured"
DEFAULT_FILES_CSV = UNSTRUCTURED_DIR / "files.csv"
DEFAULT_ANSWER_KEY_CSV = UNSTRUCTURED_DIR / "answer_key.csv"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "benchmark_output"
COMPARE_TOOL_PATH = (
    REPO_ROOT / "data_validation" / "tools" / "compare_extraction.py"
)
BACKEND_CALC_PATH = (
    REPO_ROOT / "backend" / "app" / "services" / "shift_calculations.py"
)
BACKEND_RULES_PATH = REPO_ROOT / "backend" / "app" / "config" / "pay_rules.csv"
BACKEND_LOCATIONS_PATH = REPO_ROOT / "backend" / "app" / "config" / "locations.csv"
FLAG_TYPES_PATH = REPO_ROOT / "data_validation" / "test_data" / "flag_types.csv"

_VERSION_DIR_RE = re.compile(r"^v(\d+)(?:$|_)")


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_compare_tool() -> ModuleType:
    """Dynamically load data_validation/tools/compare_extraction.py without modifying it."""
    return _load_module("compare_extraction", COMPARE_TOOL_PATH)


def resolve_versioned_output_dir(
    base_output_dir: Path,
    *,
    run_label: str | None = None,
) -> Path:
    """
    Create a fresh versioned subdirectory under base_output_dir so prior results cannot be overwritten.

    If base_output_dir contains top-level artifacts (like V1 outputs) or existing vN directories
    (such as v1_baseline), the next sequential directory v2, v3, ... is returned.
    """
    base_output_dir.mkdir(parents=True, exist_ok=True)
    if run_label:
        safe_label = re.sub(r"[^A-Za-z0-9._-]+", "_", run_label.strip()) or "run"
        candidate = base_output_dir / safe_label
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        suffix = 2
        while (base_output_dir / f"{safe_label}_{suffix}").exists():
            suffix += 1
        final_dir = base_output_dir / f"{safe_label}_{suffix}"
        final_dir.mkdir(parents=True, exist_ok=False)
        return final_dir

    highest_version = 0
    has_root_artifacts = any(
        (base_output_dir / name).exists()
        for name in ("benchmark_results.json", "extracted.csv", "comparison_report.txt")
    )
    if has_root_artifacts:
        highest_version = max(highest_version, 1)

    for child in base_output_dir.iterdir():
        if not child.is_dir():
            continue
        m = _VERSION_DIR_RE.match(child.name)
        if m:
            highest_version = max(highest_version, int(m.group(1)))

    next_version = highest_version + 1
    candidate = base_output_dir / f"v{next_version}"
    while candidate.exists():
        next_version += 1
        candidate = base_output_dir / f"v{next_version}"
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


@dataclass(frozen=True, slots=True)
class DocumentManifestEntry:
    """Single row loaded from data_validation/test_data/unstructured/files.csv."""

    file_name: str
    folder: str
    schedule_id: str
    kind: str
    layout_or_look: str
    difficulty: str
    target_worker: str | None
    document_path: Path


@dataclass(slots=True)
class BenchmarkDocumentResult:
    """Complete per-document extraction, retry telemetry, token usage, and failure record."""

    file_name: str
    schedule_id: str
    kind: str
    difficulty: str
    target_worker: str | None
    page_count: int
    provider_name: str
    model_id: str
    processing_time_seconds: float
    token_usage: dict[str, int]
    finish_reason: str | None
    request_attempts: int
    attempt_history: list[dict[str, Any]]
    extracted_shift_count: int
    filtered_other_worker_shifts: int
    deduplicated_shifts: int
    invalid_or_empty_records: int
    rejected_records: list[dict[str, Any]]
    partially_recovered_shift_count: int
    incomplete_extraction: bool
    partial_recovery_triggered: bool
    request_failure: bool
    request_error: str | None
    json_validation_failure: bool
    json_validation_errors: list[str]
    raw_response: str
    reasoning_text: str | None
    normalised_output: list[dict[str, Any]] = field(default_factory=list)
    deduplicated_records: list[dict[str, Any]] = field(default_factory=list)
    conflicting_duplicate_count: int = 0
    conflict_groups: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkRunResult:
    """Complete output of an extraction benchmark execution or offline replay."""

    run_timestamp_utc: str
    provider_name: str
    model_id: str
    adapter_config: dict[str, Any]
    output_dir: Path
    selected_files: list[str] | None
    documents_evaluated: int
    total_processing_time_seconds: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_reasoning_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_request_attempts: int
    total_retries: int
    failed_attempts: int
    failed_attempt_overhead_seconds: float
    successful_attempt_latency_seconds: float
    latency_and_retry_summary: dict[str, Any]
    request_failures: int
    json_validation_failures: int
    incomplete_extractions: int
    partially_recovered_documents: int
    total_invalid_or_empty_records: int
    total_conflicting_duplicate_records: int
    extracted_shift_count: int
    document_results: list[BenchmarkDocumentResult]
    comparison_summary: dict[str, Any]
    full_dataset_comparison_summary: dict[str, Any] | None
    deterministic_validation_summary: dict[str, Any]
    comparison_report_text: str
    full_dataset_report_text: str | None
    extracted_csv_path: Path
    review_queue_csv_path: Path
    differences_csv_path: Path
    comparison_report_path: Path
    full_dataset_report_path: Path | None
    full_dataset_differences_csv_path: Path | None
    per_document_csv_path: Path
    results_json_path: Path


def load_files_manifest(
    files_csv: Path = DEFAULT_FILES_CSV,
    unstructured_dir: Path = UNSTRUCTURED_DIR,
) -> list[DocumentManifestEntry]:
    """Load the synthetic unstructured document manifest without touching answer_key.csv."""
    with files_csv.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    entries: list[DocumentManifestEntry] = []
    for row in rows:
        target = (row.get("target_worker") or "").strip() or None
        file_name = row["file_name"].strip()
        folder = row["folder"].strip()
        entries.append(
            DocumentManifestEntry(
                file_name=file_name,
                folder=folder,
                schedule_id=row.get("schedule_id", "").strip(),
                kind=row.get("kind", "").strip(),
                layout_or_look=row.get("layout_or_look", "").strip(),
                difficulty=row.get("difficulty", "").strip(),
                target_worker=target,
                document_path=unstructured_dir / folder / file_name,
            )
        )
    return entries


def ensure_rendering_dependencies(
    manifest: Sequence[DocumentManifestEntry],
    *,
    preprocess_images: bool = False,
) -> None:
    """
    Fail fast before a benchmark run if any selected document requires an unavailable backend.

    Prevents PDF schedules from being silently skipped when running on Windows/Linux
    without pypdfium2 + Pillow.
    """
    has_pdf = any(
        entry.document_path.suffix.lower() == ".pdf" or entry.kind.lower() == "pdf"
        for entry in manifest
    )
    if has_pdf and get_available_pdf_rendering_backend() is None:
        raise MissingRenderingDependencyError(
            "Benchmark includes PDF documents, but no PDF rendering backend is available. "
            "Install cross-platform extraction dependencies with: "
            "pip install -r requirements.txt (or: pip install pypdfium2 Pillow)."
        )

    if preprocess_images:
        has_jpeg = any(
            entry.document_path.suffix.lower() in (".jpg", ".jpeg")
            for entry in manifest
        )
        if has_jpeg and get_available_image_preprocessing_backend("image/jpeg") is None:
            raise MissingRenderingDependencyError(
                "Benchmark includes JPEG preprocessing, but no JPEG decoding backend is available. "
                "Install Pillow with: pip install -r requirements.txt (or: pip install Pillow)."
            )


def _compute_percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = pct * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _compute_latency_and_retry_stats(
    doc_results: list[BenchmarkDocumentResult],
) -> dict[str, Any]:
    doc_times = sorted(float(d.processing_time_seconds) for d in doc_results)
    mean_latency = statistics.mean(doc_times) if doc_times else 0.0
    median_latency = statistics.median(doc_times) if doc_times else 0.0
    p90_latency = _compute_percentile(doc_times, 0.90)
    max_latency = max(doc_times) if doc_times else 0.0

    total_attempts = sum(d.request_attempts for d in doc_results)
    total_retries = sum(max(0, d.request_attempts - 1) for d in doc_results)

    failed_attempts = 0
    failed_overhead = 0.0
    success_latency = 0.0
    for d in doc_results:
        for att in d.attempt_history:
            elapsed = float(att.get("elapsed_seconds") or 0.0)
            if att.get("succeeded"):
                success_latency += elapsed
            else:
                failed_attempts += 1
                failed_overhead += elapsed

    return {
        "mean_latency_seconds": round(mean_latency, 4),
        "median_latency_seconds": round(median_latency, 4),
        "p90_latency_seconds": round(p90_latency, 4),
        "max_latency_seconds": round(max_latency, 4),
        "total_request_attempts": total_attempts,
        "total_retries": total_retries,
        "failed_attempts": failed_attempts,
        "failed_attempt_overhead_seconds": round(failed_overhead, 4),
        "successful_attempt_latency_seconds": round(success_latency, 4),
    }


def _evaluate_deterministic_validation(
    shift_rows: list[tuple[str, ExtractedShiftRecord]],
) -> dict[str, Any]:
    """
    Evaluate extracted shifts with the unmodified backend validation/earnings service.

    Kept strictly separate from extraction accuracy so unconfirmed AI protection and
    deterministic validation outcomes are reported independently.
    """
    if not BACKEND_CALC_PATH.is_file():
        return {"available": False, "reason": "shift_calculations.py not found"}

    calc_mod = _load_module("shift_calculations", BACKEND_CALC_PATH)
    rules = calc_mod.load_rules(str(BACKEND_RULES_PATH))
    messages = calc_mod.load_flag_messages(str(FLAG_TYPES_PATH))
    known_locs = calc_mod.load_known_locations(str(BACKEND_LOCATIONS_PATH))

    by_file: dict[str, list[tuple[int, ExtractedShiftRecord]]] = {}
    for idx, (fname, rec) in enumerate(shift_rows, start=1):
        by_file.setdefault(fname, []).append((idx, rec))

    as_extracted_status: Counter[str] = Counter()
    as_extracted_eligible = 0
    confirmed_validation: Counter[str] = Counter()
    confirmed_earnings_status: Counter[str] = Counter()
    confirmed_eligible = 0
    unresolved_conflict_records = sum(
        1
        for _, rec in shift_rows
        if rec.requires_conflict_resolution and not rec.conflict_resolved
    )

    for fname, items in by_file.items():
        as_extracted_payload = []
        confirmed_payload = []
        for idx, rec in items:
            eff = rec.effective_values()
            base_item = {
                "shift_id": f"{fname}#{idx}",
                "shift_date": eff.shift_date,
                "start_time": eff.start_time,
                "end_time": eff.end_time,
                "break_minutes": eff.break_minutes,
                "employer_name": eff.employer_name,
                "location": eff.location,
                "hourly_rate": eff.hourly_rate,
                "currency": eff.currency,
                "shift_status": eff.shift_status,
            }
            as_extracted_payload.append(
                {**base_item, "confirmation_status": rec.confirmation_status}
            )
            simulated_conf = rec.apply_worker_correction({}, confirm_individually=True)
            confirmed_payload.append(
                {**base_item, "confirmation_status": simulated_conf.confirmation_status}
            )

        res_ext = calc_mod.calculate_shifts(
            {"worker_id": f"BENCH::{fname}", "shifts": as_extracted_payload},
            flag_messages=messages,
            known_locations=known_locs,
            rules=rules,
        )
        for item in res_ext["shifts"]:
            as_extracted_status[item["earnings_status"]] += 1
            if item["eligible_for_earnings"]:
                as_extracted_eligible += 1

        res_conf = calc_mod.calculate_shifts(
            {"worker_id": f"BENCH::{fname}", "shifts": confirmed_payload},
            flag_messages=messages,
            known_locations=known_locs,
            rules=rules,
        )
        for item in res_conf["shifts"]:
            confirmed_validation[item["validation_status"]] += 1
            confirmed_earnings_status[item["earnings_status"]] += 1
            if item["eligible_for_earnings"]:
                confirmed_eligible += 1

    return {
        "available": True,
        "total_extracted_records": len(shift_rows),
        "unresolved_conflict_records": unresolved_conflict_records,
        "as_extracted_unconfirmed": {
            "eligible_for_earnings_count": as_extracted_eligible,
            "earnings_status_counts": dict(sorted(as_extracted_status.items())),
        },
        "if_individually_confirmed": {
            "eligible_for_earnings_count": confirmed_eligible,
            "validation_status_counts": dict(sorted(confirmed_validation.items())),
            "earnings_status_counts": dict(sorted(confirmed_earnings_status.items())),
        },
    }


def extract_single_document(
    *,
    file_path: Path,
    file_name: str,
    adapter: ExtractionAdapter,
    target_worker: str | None = None,
    dpi: int = DEFAULT_PDF_DPI,
    preprocess_images: bool = False,
    deskew: bool = True,
    perspective_correct: bool = False,
    max_retries: int | None = None,
    backoff_seconds: float | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[
    int,
    str,
    str | None,
    str | None,
    float,
    TokenUsage,
    list[RequestAttemptRecord],
    bool,
    str | None,
    DocumentExtractionResult | None,
]:
    """
    Extract and validate shifts for one document with bounded retries.

    Captures per-attempt tokens, latency, finish_reason, and failure reasons across ALL attempts.
    Never reads or receives any answer key, and never merges shifts across conflicting attempts.
    """
    try:
        pages = load_document_pages(
            file_path,
            dpi=dpi,
            preprocess_images=preprocess_images,
            deskew=deskew,
            perspective_correct=perspective_correct,
        )
    except MissingRenderingDependencyError:
        raise
    except Exception as exc:
        return (
            0,
            "",
            None,
            None,
            0.0,
            TokenUsage(),
            [],
            True,
            f"Document preparation error: {exc}",
            None,
        )

    user_prompt = build_user_prompt(
        target_worker=target_worker,
        page_count=len(pages),
    )
    request = ProviderExtractionRequest(
        file_name=file_name,
        pages=tuple(pages),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        target_worker=target_worker,
    )

    outcome = run_provider_attempts(
        adapter,
        request,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        sleep_fn=sleep_fn,
    )
    best_raw = outcome.raw_response

    return (
        len(pages),
        best_raw.raw_text if best_raw is not None else "",
        best_raw.reasoning_text if best_raw is not None else None,
        best_raw.finish_reason if best_raw is not None else None,
        outcome.elapsed_seconds,
        outcome.token_usage,
        outcome.attempt_records,
        outcome.final_request_failure,
        outcome.final_request_error,
        outcome.parsed_result,
    )


def _write_extracted_csv(
    path: Path,
    rows: list[tuple[str, ExtractedShiftRecord]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for file_name, record in rows:
            writer.writerow(record.to_compare_csv_row(file_name))


def _write_review_queue_csv(
    path: Path,
    rows: list[tuple[str, ExtractedShiftRecord]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CONFIRMATION_CSV_COLUMNS))
        writer.writeheader()
        for file_name, record in rows:
            base = record.to_compare_csv_row(file_name)
            base.update(
                {
                    "confidence": record.confidence,
                    "confirmation_status": record.confirmation_status,
                    "requires_worker_confirmation": str(
                        record.requires_worker_confirmation
                    ).lower(),
                    "requires_individual_review": str(
                        record.requires_individual_review
                    ).lower(),
                    "eligible_for_bulk_confirmation": str(
                        record.eligible_for_bulk_confirmation
                    ).lower(),
                    "source_page": (
                        "" if record.source_page is None else str(record.source_page)
                    ),
                    "source_row": (
                        "" if record.source_row is None else str(record.source_row)
                    ),
                    "worker_attribution_status": record.worker_attribution_status,
                    "partially_recovered": str(record.partially_recovered).lower(),
                    "conflict_group_id": record.conflict_group_id or "",
                    "conflicting_fields": "; ".join(record.conflicting_fields),
                    "requires_conflict_resolution": str(
                        record.requires_conflict_resolution
                    ).lower(),
                    "review_reasons": "; ".join(record.review_reasons),
                }
            )
            writer.writerow(base)


def _write_per_document_csv(
    path: Path,
    doc_results: list[BenchmarkDocumentResult],
) -> None:
    fieldnames = [
        "file_name",
        "schedule_id",
        "kind",
        "difficulty",
        "target_worker",
        "page_count",
        "provider_name",
        "model_id",
        "finish_reason",
        "request_attempts",
        "processing_time_seconds",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "output_tokens",
        "total_tokens",
        "extracted_shift_count",
        "filtered_other_worker_shifts",
        "deduplicated_shifts",
        "conflicting_duplicate_count",
        "invalid_or_empty_records",
        "partially_recovered_shift_count",
        "incomplete_extraction",
        "partial_recovery_triggered",
        "request_failure",
        "request_error",
        "json_validation_failure",
        "json_validation_errors",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in doc_results:
            writer.writerow(
                {
                    "file_name": item.file_name,
                    "schedule_id": item.schedule_id,
                    "kind": item.kind,
                    "difficulty": item.difficulty,
                    "target_worker": item.target_worker or "",
                    "page_count": item.page_count,
                    "provider_name": item.provider_name,
                    "model_id": item.model_id,
                    "finish_reason": item.finish_reason or "",
                    "request_attempts": item.request_attempts,
                    "processing_time_seconds": f"{item.processing_time_seconds:.3f}",
                    "prompt_tokens": item.token_usage["prompt_tokens"],
                    "completion_tokens": item.token_usage["completion_tokens"],
                    "reasoning_tokens": item.token_usage["reasoning_tokens"],
                    "output_tokens": item.token_usage["output_tokens"],
                    "total_tokens": item.token_usage["total_tokens"],
                    "extracted_shift_count": item.extracted_shift_count,
                    "filtered_other_worker_shifts": item.filtered_other_worker_shifts,
                    "deduplicated_shifts": item.deduplicated_shifts,
                    "conflicting_duplicate_count": item.conflicting_duplicate_count,
                    "invalid_or_empty_records": item.invalid_or_empty_records,
                    "partially_recovered_shift_count": item.partially_recovered_shift_count,
                    "incomplete_extraction": str(item.incomplete_extraction).lower(),
                    "partial_recovery_triggered": str(
                        item.partial_recovery_triggered
                    ).lower(),
                    "request_failure": str(item.request_failure).lower(),
                    "request_error": item.request_error or "",
                    "json_validation_failure": str(item.json_validation_failure).lower(),
                    "json_validation_errors": "; ".join(item.json_validation_errors),
                }
            )


def _finalise_benchmark_run(
    *,
    run_dir: Path,
    provider_name: str,
    model_id: str,
    adapter_config: dict[str, Any],
    selected_list: list[str] | None,
    doc_results: list[BenchmarkDocumentResult],
    all_shift_rows: list[tuple[str, ExtractedShiftRecord]],
    answer_key_csv: Path,
    replay_source: Path | None = None,
) -> BenchmarkRunResult:
    """Shared reporting, comparison, deterministic check, and artifact persistence."""
    extracted_csv_path = run_dir / "extracted.csv"
    review_queue_csv_path = run_dir / "extracted_review_queue.csv"
    differences_csv_path = run_dir / "differences.csv"
    comparison_report_path = run_dir / "comparison_report.txt"
    per_document_csv_path = run_dir / "per_document_metrics.csv"
    results_json_path = run_dir / "benchmark_results.json"

    _write_extracted_csv(extracted_csv_path, all_shift_rows)
    _write_review_queue_csv(review_queue_csv_path, all_shift_rows)
    _write_per_document_csv(per_document_csv_path, doc_results)

    # Answer key is loaded strictly AFTER extraction/replay for evaluation only.
    compare_tool = _load_compare_tool()
    got_rows = compare_tool.read_csv(str(extracted_csv_path))
    full_key_rows = compare_tool.read_csv(str(answer_key_csv))

    full_dataset_summary: dict[str, Any] | None = None
    full_dataset_report_text: str | None = None
    full_dataset_report_path: Path | None = None
    full_dataset_differences_csv_path: Path | None = None

    if selected_list is not None:
        # Subset mode: primary report scores ONLY selected documents cleanly.
        selected_set = set(selected_list)
        subset_key = [r for r in full_key_rows if r["file_name"] in selected_set]
        subset_per_file = compare_tool.compare(subset_key, got_rows)
        primary_summary = compare_tool.summarise(subset_per_file)
        primary_report_text = compare_tool.report(subset_per_file)
        compare_tool.write_report_csv(subset_per_file, str(differences_csv_path))
        comparison_report_path.write_text(primary_report_text + "\n", encoding="utf-8")

        # Save full-dataset comparison separately with an explicit limitation banner.
        full_per_file = compare_tool.compare(full_key_rows, got_rows)
        full_dataset_summary = compare_tool.summarise(full_per_file)
        raw_full_report = compare_tool.report(full_per_file)
        limitation_banner = (
            f"LIMITATION NOTE: This subset run evaluated {len(selected_list)}/14 documents "
            f"({', '.join(selected_list)}). Unselected documents were NOT run and appear as "
            f"missed in this full-dataset reference.\n\n"
        )
        full_dataset_report_text = limitation_banner + raw_full_report
        full_dataset_report_path = run_dir / "full_dataset_comparison_report.txt"
        full_dataset_differences_csv_path = run_dir / "full_dataset_differences.csv"
        full_dataset_report_path.write_text(
            full_dataset_report_text + "\n", encoding="utf-8"
        )
        compare_tool.write_report_csv(
            full_per_file, str(full_dataset_differences_csv_path)
        )
    else:
        full_per_file = compare_tool.compare(full_key_rows, got_rows)
        primary_summary = compare_tool.summarise(full_per_file)
        primary_report_text = compare_tool.report(full_per_file)
        compare_tool.write_report_csv(full_per_file, str(differences_csv_path))
        comparison_report_path.write_text(primary_report_text + "\n", encoding="utf-8")

    latency_retry_stats = _compute_latency_and_retry_stats(doc_results)
    deterministic_summary = _evaluate_deterministic_validation(all_shift_rows)

    total_time = round(sum(d.processing_time_seconds for d in doc_results), 4)
    total_prompt = sum(d.token_usage["prompt_tokens"] for d in doc_results)
    total_completion = sum(d.token_usage["completion_tokens"] for d in doc_results)
    total_reasoning = sum(d.token_usage["reasoning_tokens"] for d in doc_results)
    total_output = sum(d.token_usage["output_tokens"] for d in doc_results)
    total_tok = sum(d.token_usage["total_tokens"] for d in doc_results)
    req_failures = sum(1 for d in doc_results if d.request_failure)
    json_failures = sum(1 for d in doc_results if d.json_validation_failure)
    incomplete_count = sum(1 for d in doc_results if d.incomplete_extraction)
    partial_docs = sum(1 for d in doc_results if d.partial_recovery_triggered)
    total_invalid_empty = sum(d.invalid_or_empty_records for d in doc_results)
    total_conflicting_duplicates = sum(
        d.conflicting_duplicate_count for d in doc_results
    )
    timestamp = datetime.now(timezone.utc).isoformat()

    json_payload = {
        "run_timestamp_utc": timestamp,
        "replay_source_results_json": str(replay_source) if replay_source else None,
        "provider_name": provider_name,
        "model_id": model_id,
        "adapter_config": adapter_config,
        "output_dir": str(run_dir),
        "selected_files": selected_list,
        "documents_evaluated": len(doc_results),
        "total_request_attempts": latency_retry_stats["total_request_attempts"],
        "total_retries": latency_retry_stats["total_retries"],
        "failed_attempts": latency_retry_stats["failed_attempts"],
        "failed_attempt_overhead_seconds": latency_retry_stats[
            "failed_attempt_overhead_seconds"
        ],
        "successful_attempt_latency_seconds": latency_retry_stats[
            "successful_attempt_latency_seconds"
        ],
        "total_processing_time_seconds": total_time,
        "latency_and_retry_summary": latency_retry_stats,
        "token_usage": {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "reasoning_tokens": total_reasoning,
            "output_tokens": total_output,
            "total_tokens": total_tok,
        },
        "request_failures": req_failures,
        "json_validation_failures": json_failures,
        "incomplete_extractions": incomplete_count,
        "partially_recovered_documents": partial_docs,
        "total_invalid_or_empty_records": total_invalid_empty,
        "total_conflicting_duplicate_records": total_conflicting_duplicates,
        "extracted_shift_count": len(all_shift_rows),
        "comparison_summary": primary_summary,
        "full_dataset_comparison_summary": full_dataset_summary,
        "full_dataset_limitation_note": (
            f"Only {len(selected_list)}/14 documents evaluated; unselected documents count as missed."
            if selected_list is not None
            else None
        ),
        "deterministic_validation_summary": deterministic_summary,
        "documents": [asdict(d) for d in doc_results],
    }
    results_json_path.write_text(
        json.dumps(json_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return BenchmarkRunResult(
        run_timestamp_utc=timestamp,
        provider_name=provider_name,
        model_id=model_id,
        adapter_config=adapter_config,
        output_dir=run_dir,
        selected_files=selected_list,
        documents_evaluated=len(doc_results),
        total_processing_time_seconds=total_time,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_reasoning_tokens=total_reasoning,
        total_output_tokens=total_output,
        total_tokens=total_tok,
        total_request_attempts=latency_retry_stats["total_request_attempts"],
        total_retries=latency_retry_stats["total_retries"],
        failed_attempts=latency_retry_stats["failed_attempts"],
        failed_attempt_overhead_seconds=latency_retry_stats[
            "failed_attempt_overhead_seconds"
        ],
        successful_attempt_latency_seconds=latency_retry_stats[
            "successful_attempt_latency_seconds"
        ],
        latency_and_retry_summary=latency_retry_stats,
        request_failures=req_failures,
        json_validation_failures=json_failures,
        incomplete_extractions=incomplete_count,
        partially_recovered_documents=partial_docs,
        total_invalid_or_empty_records=total_invalid_empty,
        total_conflicting_duplicate_records=total_conflicting_duplicates,
        extracted_shift_count=len(all_shift_rows),
        document_results=doc_results,
        comparison_summary=primary_summary,
        full_dataset_comparison_summary=full_dataset_summary,
        deterministic_validation_summary=deterministic_summary,
        comparison_report_text=primary_report_text,
        full_dataset_report_text=full_dataset_report_text,
        extracted_csv_path=extracted_csv_path,
        review_queue_csv_path=review_queue_csv_path,
        differences_csv_path=differences_csv_path,
        comparison_report_path=comparison_report_path,
        full_dataset_report_path=full_dataset_report_path,
        full_dataset_differences_csv_path=full_dataset_differences_csv_path,
        per_document_csv_path=per_document_csv_path,
        results_json_path=results_json_path,
    )


def run_benchmark(
    adapter: ExtractionAdapter,
    *,
    files_csv: Path = DEFAULT_FILES_CSV,
    unstructured_dir: Path = UNSTRUCTURED_DIR,
    answer_key_csv: Path = DEFAULT_ANSWER_KEY_CSV,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_label: str | None = None,
    only_files: Sequence[str] | None = None,
    dpi: int = DEFAULT_PDF_DPI,
    preprocess_images: bool = False,
    deskew: bool = True,
    perspective_correct: bool = False,
    max_retries: int | None = None,
    backoff_seconds: float | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> BenchmarkRunResult:
    """
    Run extraction across synthetic documents and score using compare_extraction.py.

    Always writes into a separate versioned subdirectory under output_dir so previous
    benchmark runs (including V1/V2/Gemini artifacts) can never be overwritten.
    """
    manifest = load_files_manifest(files_csv=files_csv, unstructured_dir=unstructured_dir)
    selected_list: list[str] | None = None
    if only_files:
        requested = set(only_files)
        manifest = [entry for entry in manifest if entry.file_name in requested]
        if not manifest:
            raise ValueError(
                f"None of the requested files matched manifest: {sorted(requested)}"
            )
        selected_list = [entry.file_name for entry in manifest]

    ensure_rendering_dependencies(manifest, preprocess_images=preprocess_images)

    run_dir = resolve_versioned_output_dir(output_dir, run_label=run_label)
    doc_results: list[BenchmarkDocumentResult] = []
    all_shift_rows: list[tuple[str, ExtractedShiftRecord]] = []

    for entry in manifest:
        # Strict answer-key isolation: extract_single_document never reads any answer key.
        (
            page_count,
            raw_response,
            reasoning_text,
            finish_reason,
            elapsed_s,
            usage,
            attempt_records,
            req_fail,
            req_err,
            parsed_doc,
        ) = extract_single_document(
            file_path=entry.document_path,
            file_name=entry.file_name,
            adapter=adapter,
            target_worker=entry.target_worker,
            dpi=dpi,
            preprocess_images=preprocess_images,
            deskew=deskew,
            perspective_correct=perspective_correct,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            sleep_fn=sleep_fn,
        )

        shifts = parsed_doc.shifts if parsed_doc is not None else []
        for shift_rec in shifts:
            all_shift_rows.append((entry.file_name, shift_rec))

        doc_results.append(
            BenchmarkDocumentResult(
                file_name=entry.file_name,
                schedule_id=entry.schedule_id,
                kind=entry.kind,
                difficulty=entry.difficulty,
                target_worker=entry.target_worker,
                page_count=page_count,
                provider_name=adapter.provider_name,
                model_id=parsed_doc.model_id if parsed_doc else adapter.model_id,
                processing_time_seconds=round(elapsed_s, 4),
                token_usage=usage.to_dict(),
                finish_reason=finish_reason,
                request_attempts=len(attempt_records),
                attempt_history=[rec.to_dict() for rec in attempt_records],
                extracted_shift_count=len(shifts),
                filtered_other_worker_shifts=(
                    parsed_doc.filtered_other_worker_shifts if parsed_doc else 0
                ),
                deduplicated_shifts=(
                    parsed_doc.deduplicated_shifts if parsed_doc else 0
                ),
                invalid_or_empty_records=(
                    parsed_doc.invalid_or_empty_records if parsed_doc else 0
                ),
                rejected_records=(
                    list(parsed_doc.rejected_records) if parsed_doc else []
                ),
                partially_recovered_shift_count=(
                    parsed_doc.partially_recovered_shift_count if parsed_doc else 0
                ),
                incomplete_extraction=(
                    parsed_doc.incomplete_extraction if parsed_doc else False
                ),
                partial_recovery_triggered=(
                    parsed_doc.partial_recovery_triggered if parsed_doc else False
                ),
                request_failure=req_fail,
                request_error=req_err,
                json_validation_failure=(
                    parsed_doc.json_validation_failure if parsed_doc else False
                ),
                json_validation_errors=(
                    list(parsed_doc.json_validation_errors) if parsed_doc else []
                ),
                raw_response=raw_response,
                reasoning_text=reasoning_text,
                normalised_output=[rec.model_dump() for rec in shifts],
                deduplicated_records=(
                    list(parsed_doc.deduplicated_records) if parsed_doc else []
                ),
                conflicting_duplicate_count=(
                    parsed_doc.conflicting_duplicate_count if parsed_doc else 0
                ),
                conflict_groups=(
                    list(parsed_doc.conflict_groups) if parsed_doc else []
                ),
            )
        )

    adapter_config = {
        **adapter.config_snapshot(),
        "pdf_dpi": dpi,
        "preprocess_images": preprocess_images,
        "deskew": deskew if preprocess_images else False,
        "perspective_correct": perspective_correct if preprocess_images else False,
    }
    return _finalise_benchmark_run(
        run_dir=run_dir,
        provider_name=adapter.provider_name,
        model_id=adapter.model_id,
        adapter_config=adapter_config,
        selected_list=selected_list,
        doc_results=doc_results,
        all_shift_rows=all_shift_rows,
        answer_key_csv=answer_key_csv,
    )


def replay_saved_benchmark_run(
    source_results_json: Path,
    *,
    answer_key_csv: Path = DEFAULT_ANSWER_KEY_CSV,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_label: str | None = None,
) -> BenchmarkRunResult:
    """
    Replay saved raw model responses through the V3 parser and reporting pipeline offline.

    Never makes API requests, never modifies source_results_json, never mines reasoning_text,
    and never reads answer_key.csv during extraction/parsing.
    """
    source_payload = json.loads(source_results_json.read_text(encoding="utf-8"))
    provider_name = str(source_payload.get("provider_name") or "unknown")
    model_id = str(source_payload.get("model_id") or DEFAULT_NVIDIA_MODEL)
    adapter_config = dict(source_payload.get("adapter_config") or {})
    raw_selected = source_payload.get("selected_files")
    selected_list = list(raw_selected) if isinstance(raw_selected, list) else None

    default_label = f"v3_replay_{source_results_json.parent.name}"
    run_dir = resolve_versioned_output_dir(
        output_dir, run_label=run_label or default_label
    )

    doc_results: list[BenchmarkDocumentResult] = []
    all_shift_rows: list[tuple[str, ExtractedShiftRecord]] = []

    for doc in source_payload.get("documents", []):
        file_name = str(doc["file_name"])
        target_worker = doc.get("target_worker") or None
        raw_usage = dict(doc.get("token_usage") or {})
        prompt_tok = int(raw_usage.get("prompt_tokens") or 0)
        comp_tok = int(raw_usage.get("completion_tokens") or 0)
        reas_tok = int(raw_usage.get("reasoning_tokens") or 0)
        out_tok = int(raw_usage.get("output_tokens") or max(0, comp_tok - reas_tok))
        tot_tok = int(raw_usage.get("total_tokens") or (prompt_tok + comp_tok))
        norm_usage = {
            "prompt_tokens": prompt_tok,
            "completion_tokens": comp_tok,
            "reasoning_tokens": reas_tok,
            "output_tokens": out_tok,
            "total_tokens": tot_tok,
        }

        elapsed = float(doc.get("processing_time_seconds") or 0.0)
        raw_response = str(doc.get("raw_response") or "")
        reasoning_text = doc.get("reasoning_text")
        req_fail = bool(doc.get("request_failure"))
        req_err = doc.get("request_error")
        doc_model = str(doc.get("model_id") or model_id)
        finish_reason = doc.get("finish_reason")
        if finish_reason is None and provider_name == "nvidia" and comp_tok >= 4096:
            # Preserve V1 4096-token truncation inference when finish_reason was absent.
            finish_reason = "length"

        attempts = int(doc.get("request_attempts") or 1)
        attempt_hist = list(doc.get("attempt_history") or [])
        if not attempt_hist:
            attempt_hist = [
                {
                    "attempt_number": 1,
                    "elapsed_seconds": round(elapsed, 4),
                    "token_usage": norm_usage,
                    "finish_reason": finish_reason,
                    "succeeded": not req_fail,
                    "failure_reason": req_err,
                    "transient_error": False,
                }
            ]

        parsed_doc: DocumentExtractionResult | None = None
        if not (req_fail and not raw_response.strip()):
            parsed_doc = parse_and_validate_model_json(
                raw_response,
                file_name=file_name,
                model_id=doc_model,
                target_worker=target_worker,
                finish_reason=finish_reason,
                allow_partial_recovery=True,
            )

        shifts = parsed_doc.shifts if parsed_doc is not None else []
        for shift_rec in shifts:
            all_shift_rows.append((file_name, shift_rec))

        doc_results.append(
            BenchmarkDocumentResult(
                file_name=file_name,
                schedule_id=str(doc.get("schedule_id") or ""),
                kind=str(doc.get("kind") or ""),
                difficulty=str(doc.get("difficulty") or ""),
                target_worker=target_worker,
                page_count=int(doc.get("page_count") or 1),
                provider_name=str(doc.get("provider_name") or provider_name),
                model_id=doc_model,
                processing_time_seconds=round(elapsed, 4),
                token_usage=norm_usage,
                finish_reason=finish_reason,
                request_attempts=attempts,
                attempt_history=attempt_hist,
                extracted_shift_count=len(shifts),
                filtered_other_worker_shifts=(
                    parsed_doc.filtered_other_worker_shifts if parsed_doc else 0
                ),
                deduplicated_shifts=(
                    parsed_doc.deduplicated_shifts if parsed_doc else 0
                ),
                invalid_or_empty_records=(
                    parsed_doc.invalid_or_empty_records if parsed_doc else 0
                ),
                rejected_records=(
                    list(parsed_doc.rejected_records) if parsed_doc else []
                ),
                partially_recovered_shift_count=(
                    parsed_doc.partially_recovered_shift_count if parsed_doc else 0
                ),
                incomplete_extraction=(
                    parsed_doc.incomplete_extraction if parsed_doc else False
                ),
                partial_recovery_triggered=(
                    parsed_doc.partial_recovery_triggered if parsed_doc else False
                ),
                request_failure=req_fail,
                request_error=req_err,
                json_validation_failure=(
                    parsed_doc.json_validation_failure if parsed_doc else False
                ),
                json_validation_errors=(
                    list(parsed_doc.json_validation_errors) if parsed_doc else []
                ),
                raw_response=raw_response,
                reasoning_text=reasoning_text,
                normalised_output=[rec.model_dump() for rec in shifts],
                deduplicated_records=(
                    list(parsed_doc.deduplicated_records) if parsed_doc else []
                ),
                conflicting_duplicate_count=(
                    parsed_doc.conflicting_duplicate_count if parsed_doc else 0
                ),
                conflict_groups=(
                    list(parsed_doc.conflict_groups) if parsed_doc else []
                ),
            )
        )

    return _finalise_benchmark_run(
        run_dir=run_dir,
        provider_name=provider_name,
        model_id=model_id,
        adapter_config=adapter_config,
        selected_list=selected_list,
        doc_results=doc_results,
        all_shift_rows=all_shift_rows,
        answer_key_csv=answer_key_csv,
        replay_source=source_results_json,
    )


def evaluate_v1_offline_recovery(
    baseline_results_json: Path = DEFAULT_OUTPUT_DIR
    / "v1_baseline"
    / "benchmark_results.json",
) -> dict[str, Any]:
    """
    Re-parse preserved V1 failed documents offline using V3 partial-recovery rules.

    Never makes API requests, never extracts from reasoning_text, and never reads answer_key.csv.
    """
    payload = json.loads(baseline_results_json.read_text(encoding="utf-8"))
    model_id = str(payload.get("model_id") or DEFAULT_NVIDIA_MODEL)
    recovered_docs: list[dict[str, Any]] = []

    for doc in payload.get("documents", []):
        if not doc.get("json_validation_failure"):
            continue
        file_name = doc["file_name"]
        completion_tokens = int((doc.get("token_usage") or {}).get("completion_tokens") or 0)
        inferred_finish = "length" if completion_tokens >= 4096 else None
        parsed = parse_and_validate_model_json(
            doc.get("raw_response", ""),
            file_name=file_name,
            model_id=model_id,
            target_worker=doc.get("target_worker"),
            finish_reason=inferred_finish,
            allow_partial_recovery=True,
        )
        recovered_docs.append(
            {
                "file_name": file_name,
                "recovered_shift_count": len(parsed.shifts),
                "partially_recovered_shift_count": parsed.partially_recovered_shift_count,
                "invalid_or_empty_records": parsed.invalid_or_empty_records,
                "incomplete_extraction": parsed.incomplete_extraction,
                "partial_recovery_triggered": parsed.partial_recovery_triggered,
                "json_validation_failure": parsed.json_validation_failure,
                "json_validation_errors": parsed.json_validation_errors,
                "recovered_shifts": [
                    {
                        "normalised": s.normalised.model_dump(),
                        "confidence": s.confidence,
                        "confirmation_status": s.confirmation_status,
                        "requires_individual_review": s.requires_individual_review,
                        "eligible_for_bulk_confirmation": s.eligible_for_bulk_confirmation,
                        "review_reasons": s.review_reasons,
                    }
                    for s in parsed.shifts
                ],
            }
        )

    return {
        "baseline_results_json": str(baseline_results_json),
        "failed_documents_reprocessed": len(recovered_docs),
        "documents": recovered_docs,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run WorkClarity AI extraction benchmark or offline replay over synthetic schedules."
    )
    parser.add_argument(
        "--provider",
        choices=("nvidia", "gemini"),
        default="nvidia",
        help="Extraction provider adapter to run (default: nvidia).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            f"Override model identifier "
            f"(defaults: nvidia={DEFAULT_NVIDIA_MODEL}, gemini={DEFAULT_GEMINI_MODEL})."
        ),
    )
    parser.add_argument(
        "--replay-from",
        type=Path,
        default=None,
        help="Replay a saved benchmark_results.json offline through V3 parser/reporting without API calls.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Base directory for versioned benchmark outputs (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional versioned subdirectory label (e.g., v3, v3_replay). Auto-versioned if omitted.",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="Optional subset of file_name entries from files.csv to evaluate.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_PDF_DPI,
        help=f"PDF rasterization resolution in DPI (default: {DEFAULT_PDF_DPI}).",
    )
    parser.add_argument(
        "--preprocess-images",
        action="store_true",
        help="Enable optional non-destructive in-memory deskewing/autocontrast preprocessing.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_NVIDIA_MAX_TOKENS,
        help=f"Maximum completion tokens per request (default: {DEFAULT_NVIDIA_MAX_TOKENS}).",
    )
    parser.add_argument(
        "--reasoning-budget",
        type=int,
        default=DEFAULT_NVIDIA_REASONING_BUDGET,
        help=f"NVIDIA reasoning_budget token limit (default: {DEFAULT_NVIDIA_REASONING_BUDGET}).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_NVIDIA_TEMPERATURE,
        help=f"Sampling temperature (default: {DEFAULT_NVIDIA_TEMPERATURE}).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_NVIDIA_MAX_RETRIES,
        help=f"Maximum additional retries per document (default: {DEFAULT_NVIDIA_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-attempt HTTP request timeout in seconds (default: 120).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.replay_from is not None:
        result = replay_saved_benchmark_run(
            args.replay_from,
            output_dir=args.output_dir,
            run_label=args.run_name,
        )
    else:
        adapter = create_adapter(
            args.provider,
            model_id=args.model,
            timeout_seconds=args.timeout,
            max_tokens=args.max_tokens,
            reasoning_budget=args.reasoning_budget,
            temperature=args.temperature,
            max_retries=args.max_retries,
        )
        result = run_benchmark(
            adapter,
            output_dir=args.output_dir,
            run_label=args.run_name,
            only_files=args.files,
            dpi=args.dpi,
            preprocess_images=args.preprocess_images,
        )

    lr = result.latency_and_retry_summary
    print(
        f"Benchmark completed: provider={result.provider_name}, model={result.model_id}, "
        f"documents={result.documents_evaluated}, attempts={result.total_request_attempts} "
        f"(retries={result.total_retries}, failed_attempts={result.failed_attempts}), "
        f"extracted_shifts={result.extracted_shift_count}"
    )
    print(
        f"Latency: total={result.total_processing_time_seconds:.2f}s, "
        f"mean={lr['mean_latency_seconds']:.2f}s, median={lr['median_latency_seconds']:.2f}s, "
        f"p90={lr['p90_latency_seconds']:.2f}s, max={lr['max_latency_seconds']:.2f}s, "
        f"failed_overhead={lr['failed_attempt_overhead_seconds']:.2f}s"
    )
    print(
        f"Tokens={result.total_tokens} "
        f"(prompt={result.total_prompt_tokens}, completion={result.total_completion_tokens}, "
        f"reasoning={result.total_reasoning_tokens}, output={result.total_output_tokens}), "
        f"request_failures={result.request_failures}, "
        f"json_validation_failures={result.json_validation_failures}, "
        f"incomplete_extractions={result.incomplete_extractions}, "
        f"invalid_or_empty_records={result.total_invalid_or_empty_records}"
    )
    print()
    print(result.comparison_report_text)
    print()
    print(
        "Deterministic Backend Validation (separate from extraction accuracy):",
        json.dumps(result.deterministic_validation_summary),
    )
    print(f"Artifacts saved to: {result.output_dir}")
    return (
        0
        if (
            result.request_failures == 0
            and result.json_validation_failures == 0
            and result.incomplete_extractions == 0
            and result.total_invalid_or_empty_records == 0
        )
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
