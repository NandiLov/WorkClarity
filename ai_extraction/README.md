# WorkClarity — AI Schedule Extraction & Automatic Failover Pipeline

Repeatable, provider-independent AI schedule extraction service and benchmarking pipeline for PDF and image rosters, built around the shared 10-field extraction schema, mandatory individual worker confirmation safeguards, and deterministic scoring against [`data_validation/tools/compare_extraction.py`](../data_validation/tools/compare_extraction.py).

## Architecture Overview

| Module | Responsibility |
|---|---|
| [`orchestrator.py`](orchestrator.py) | Reusable extraction orchestration service (`ExtractionOrchestrator`, `ExtractionServiceConfig`, `OrchestratedExtractionResult`, `run_provider_attempts`) supporting configurable primary + fallback providers, failure classification, exponential backoff retries, total processing deadlines, secret-free telemetry (`to_public_summary`), and FastAPI-ready byte/file entry points (`extract_bytes`, `extract_file`). |
| [`schema.py`](schema.py) | Shared 10-field extraction contract (`SharedShiftSchema`, `CSV_COLUMNS`, `CONFIRMATION_CSV_COLUMNS`), deterministic non-guessing normalisation, multi-envelope parsing, semantic invalid/empty rejection, safe truncated-JSON partial recovery (`parse_and_validate_model_json`), conflicting-duplicate grouping (`resolve_conflict_group`), raw/normalised/corrected separation (`apply_worker_correction`), and mandatory individual worker review safeguards (`ExtractedShiftRecord`). |
| [`prompt.py`](prompt.py) | V2 extraction prompts (`SYSTEM_PROMPT`, `build_user_prompt`) enforcing concise reasoning, unambiguous `week_of` header extraction, row-by-row alignment, missing (`null`) vs explicit `0` break preservation, `source_page`/`source_row`, and target-worker attribution. |
| [`pdf_utils.py`](pdf_utils.py) | Renders single/multi-page `.pdf` and `.png`/`.jpg` schedules from disk (`load_document_pages`) or uploaded bytes (`load_document_pages_from_bytes`) at configurable DPI (`200` default). Supports Linux/Cloud Run PDF backends (`pypdfium2`, `pymupdf`, `poppler-utils` `pdftoppm`) and macOS `CoreGraphics`, plus optional non-destructive automatic deskewing/contrast preprocessing (`preprocess_images=False` default). |
| [`providers/base.py`](providers/base.py) | Provider adapter interface (`ExtractionAdapter`), token/attempt telemetry (`TokenUsage`, `RequestAttemptRecord`), Gemini/OpenAI token reconciliation (`parse_token_usage`), transient vs permanent HTTP classification, `.env` credential lookup (`get_api_key`), and secret redaction (`redact_secret`). |
| [`providers/gemini.py`](providers/gemini.py) | Gemini multimodal adapter (`GeminiExtractionAdapter`) targeting `generativelanguage.googleapis.com`, defaulting to `gemini-3.5-flash-lite` with OpenAPI-subset `GEMINI_RESPONSE_SCHEMA`, using `GEMINI_API_KEY` independently. |
| [`providers/nvidia.py`](providers/nvidia.py) | NVIDIA multimodal `image_url` adapter (`NvidiaExtractionAdapter`) targeting `https://integrate.api.nvidia.com/v1/chat/completions`, defaulting to `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (`max_tokens=8192`, `reasoning_budget=2048`, `temperature=0.2`), using `NVIDIA_API_KEY` independently. |
| [`benchmark.py`](benchmark.py) | Runs single-provider benchmarks across the 14 synthetic schedules (or `--files` subsets) reusing `run_provider_attempts`, executes offline replays (`--replay-from`), isolates `answer_key.csv` strictly to scoring, evaluates unconfirmed vs confirmed eligibility separately against [`shift_calculations.py`](../backend/app/services/shift_calculations.py), and writes versioned output directories. |
| [`tests/test_ai_extraction.py`](tests/test_ai_extraction.py) | Mocked unit and regression test suite (`55` tests across Phase 1, V2, V3, V3.1, and Phase 4 automatic failover + review hardening). |

## Provider Selection & Defaults

`ExtractionServiceConfig` configures primary and fallback providers independently with zero cross-provider credential sharing:

- **Default primary provider:** `gemini` (`gemini-3.5-flash-lite`, updated from deprecated `gemini-2.5-flash` which returned HTTP 404 in smoke testing).
- **Default fallback provider:** `nvidia` (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`).
- **Independent single-provider operation:** Either provider can run alone by setting `fallback_enabled=False` (or `AI_EXTRACTION_FALLBACK_ENABLED=false`) or swapping `primary_provider` (`"nvidia"` or `"gemini"`).

## Configuration Variables

| Environment Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required for live Gemini)* | Gemini API credential loaded independently by `GeminiExtractionAdapter`. |
| `NVIDIA_API_KEY` | *(required for live NVIDIA)* | NVIDIA API credential loaded independently by `NvidiaExtractionAdapter`. |
| `AI_EXTRACTION_PRIMARY_PROVIDER` | `gemini` | Primary extraction provider (`gemini` or `nvidia`). |
| `AI_EXTRACTION_PRIMARY_MODEL` | provider default (`gemini-3.5-flash-lite`) | Override primary model identifier. |
| `AI_EXTRACTION_FALLBACK_ENABLED` | `true` | Enable or disable automatic fallback (`true`/`false`). |
| `AI_EXTRACTION_FALLBACK_PROVIDER` | `nvidia` | Fallback provider (`nvidia`, `gemini`, or `none`). |
| `AI_EXTRACTION_FALLBACK_MODEL` | provider default (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`) | Override fallback model identifier. |
| `AI_EXTRACTION_PRIMARY_MAX_RETRIES` | `2` | Maximum additional retry attempts on primary (`3` total attempts). |
| `AI_EXTRACTION_FALLBACK_MAX_RETRIES` | `2` | Maximum additional retry attempts on fallback (`3` total attempts). |
| `AI_EXTRACTION_RETRY_BACKOFF_SECONDS` | `1.0` | Base exponential backoff delay (`delay = base * 2**attempt_idx`). |
| `AI_EXTRACTION_TIMEOUT_SECONDS` | `120.0` | Per-attempt HTTP request timeout in seconds (clamped to remaining overall deadline). |
| `AI_EXTRACTION_TOTAL_DEADLINE_SECONDS` | `240.0` | Total cooperative deadline across preprocessing, retries, and failover (`0` disables overall deadline). |
| `AI_EXTRACTION_ALLOW_SINGLE_PROVIDER_EMPTY_SCHEDULE` | `false` | Permit contextualised `shifts: []` completion without secondary corroboration (off by default). |
| `AI_EXTRACTION_PREPROCESS_IMAGES` | `false` | Optional non-destructive deskewing preprocessing (`false` by default). |

## Retry and Fallback Policies

| Condition | Retry Same Provider? | Triggers Fallback (when enabled)? | Outcome if Unresolved |
|---|---|---|---|
| HTTP `429` rate limit / transient `408`, `500`, `502`, `503`, `504` | Yes, up to `max_retries` with backoff | Yes, after retries exhaust | `extraction_status="failed"`, `manual_entry_required=True` |
| Network connection errors & request timeouts | Yes, up to `max_retries` with backoff | Yes, after retries exhaust | `extraction_status="failed"`, `manual_entry_required=True` |
| Malformed JSON or empty response content | Yes, up to `max_retries` | Yes, after retries exhaust | `extraction_status="failed"`, `manual_entry_required=True` |
| Mixed valid + rejected shift records (`partially_invalid_response`) | Yes, up to `max_retries` | Yes (no shift merging across providers) | `extraction_status="partial"`, `is_partial=True`, `confidence="low"`, `"partial_extraction_with_rejected_records"`, `manual_entry_required=True`; never reported as `"complete"` |
| Suspicious empty array (`shifts: []`) (`suspicious_empty_shifts`) | Yes, up to `max_retries` | Yes, to verify before trusting `0` shifts | `extraction_status="complete", is_empty_schedule=True, manual_entry_required=True` **only** if corroborated cleanly with schedule context across providers (else `extraction_status="failed"`, `is_empty_schedule=False`) |
| Truncated response (`finish_reason="length"` / `"max_tokens"`) | Yes, up to `max_retries` | Yes (no shift merging across providers) | Best single partial extraction returned as `extraction_status="partial"`, `is_partial=True`, `manual_entry_required=True`; never reported as `"complete"` |
| HTTP `401`/`403` auth error or missing/empty API key | **No** (short-circuits immediately) | Yes (`failover_on_auth_or_config_error=True`) | `extraction_status="failed"`, original failure preserved |
| Non-transient `400`/`404` config error | **No** (short-circuits immediately) | Yes (`failover_on_auth_or_config_error=True`) | `extraction_status="failed"`, original failure preserved |
| Valid schedule with missing (`null`) financial/break fields | **No** (valid extraction) | **No** | `extraction_status="complete"`, missing-field shifts flagged `needs_review` |
| Total processing deadline exhausted (including preprocessing) | **Aborts immediately** | **No** | `deadline_exhausted=True`, `extraction_status="failed"` (or `"partial"` if valid partial shifts were already recovered), `manual_entry_required=True` |

## Usage Examples

### Orchestrated Extraction (File or Uploaded Bytes for FastAPI Integration)

```python
from ai_extraction import ExtractionOrchestrator, ExtractionServiceConfig

# Loads defaults (Gemini primary -> NVIDIA fallback) or overrides from env
config = ExtractionServiceConfig.from_env()
orchestrator = ExtractionOrchestrator(config)

# From an uploaded file byte stream (FastAPI UploadFile bytes)
result = orchestrator.extract_bytes(
    uploaded_bytes,
    file_name="roster_nov_2026.pdf",
    target_worker="Maria Santos",
)

if result.is_complete:
    payload = result.to_payload_dict()  # All shifts remain needs_review until confirmed
elif result.is_partial:
    # Surface recovered shifts with warning + allow worker manual completion
    partial_payload = result.to_payload_dict()
else:
    # Explicit failure (`result.is_empty_schedule` is guaranteed False) -> manual entry flow
    error_reason = result.manual_entry_reason
```

### Independent Single-Provider Execution

```python
from ai_extraction import ExtractionOrchestrator, ExtractionServiceConfig

nvidia_only = ExtractionOrchestrator(
    ExtractionServiceConfig(primary_provider="nvidia", fallback_enabled=False)
)
res = nvidia_only.extract_file("data_validation/test_data/unstructured/images/img_01_screenshot_clean.png")
```

### Automated Mocked Tests and Offline Replay

```bash
# Run all AI extraction unit and failover regression tests (mocked; no live API calls)
.venv/bin/python -m unittest discover -s ai_extraction/tests -v

# Replay saved benchmark responses offline through V3.1 schema and deterministic validation
.venv/bin/python -m ai_extraction.benchmark \
  --replay-from ai_extraction/benchmark_output/gemini_35_lite_full/benchmark_results.json \
  --run-name v3_replay_check
```

## Failure Handling & Worker Safety Safeguards

- **Failed extraction never looks like an empty schedule:** Total failure sets `extraction_status="failed"`, `is_failed=True`, `is_empty_schedule=False`, `manual_entry_required=True`, and preserves `primary_failure_reason` / `fallback_failure_reason`.
- **Partial extraction never masquerades as complete:** Truncated partial recoveries set `extraction_status="partial"`, `is_partial=True`, `is_complete=False`, `succeeded=False`, `manual_entry_required=True`, and lower confidence on recovered rows (`confidence="low"`, `review_reasons` includes `"partial_json_recovery"`).
- **Zero cross-provider or cross-attempt merging:** Only one provider attempt's parsed result is returned; retries and failovers cannot duplicate shifts.
- **Conflicting duplicate protection:** Identical shift slots with conflicting financial/break/detail values are grouped into `conflict_groups` (`requires_conflict_resolution=True`) and cannot become `"confirmed"` or contribute to earnings until resolved explicitly via `resolve_conflict_group`.
- **Mandatory individual worker confirmation:** Regardless of `confidence="high"`, every AI-extracted shift starts with `confirmation_status="needs_review"`, `requires_worker_confirmation=True`, `requires_individual_review=True`, and `eligible_for_bulk_confirmation=False`, preserving `raw_values`, `normalised`, and `worker_corrected_values` separately.
- **Secret and reasoning protection:** API keys are scrubbed per adapter via `redact_secret` without cross-provider key access, `to_log_summary()` emits strictly non-sensitive operational counters/categories, and operational logs exclude `raw_response`, `reasoning_text`, shift contents, and local directory paths.
- **Data-processing policy for secondary AI providers:** Enabling automatic failover (`AI_EXTRACTION_FALLBACK_ENABLED=true`) transmits worker schedule documents to a second external vendor when the primary provider fails. Before processing real worker documents in production, ensure an approved data-processing agreement (DPA) and worker privacy notice cover every configured primary and fallback vendor.

## Benchmark Interpretation vs. Automated Failover Tests

- **Historical single-provider V3/V3.1 benchmarks (62/62 matched shifts):** The `62/62` shift-detection recall (`TP=62, FP=0, FN=0`) reported in V3/V3.1 comes from **separate full-dataset evaluations** of Gemini (`gemini-3.5-flash-lite`, offline replay of `gemini_35_lite_full`: `57/62` all-field exact, `59/62` money-field accurate) and NVIDIA (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, offline replay of `v2`: `53/62` all-field exact, `60/62` money-field accurate).
- **Phase 4 automatic failover verification:** Phase 4 orchestration (`ExtractionOrchestrator`) was verified through deterministic mocked provider tests covering all retry, auth/config short-circuit, failover, partial-recovery, mixed valid+rejected records, corroborated vs. suspicious empty schedules, cooperative deadline exhaustion, redaction, and earnings-isolation behaviors without making new live API requests. Live end-to-end latency and cross-provider production failover rates under live traffic remain to be measured only when live credentials and API runs are explicitly approved.

## Known Limitations & Environment Dependencies

- **Cooperative deadline enforcement (not a hard wall-clock interrupt):** Document preprocessing time is included in `total_deadline_seconds` before calling providers, and `urllib.request.urlopen` socket timeouts are clamped to the remaining deadline budget; however, synchronous CPU preprocessing or a stalled OS DNS lookup cannot be forcibly interrupted mid-operation until control returns to Python.
- **Python 3.15 / `.venv` test packages:** `pytest==9.2.0` and `httpx2==2.16.0` ([`requirements-dev.txt`](../requirements-dev.txt)) allow executing `backend/tests/`, `data_validation/tests/`, and `ai_extraction/tests/` via `pytest`.
- **Optional imaging/PDF dependencies:** On Linux Cloud Run containers without macOS `CoreGraphics`/`ImageIO`, install `pypdfium2` (or `poppler-utils`) for PDF rasterization and `pillow` if JPEG decoding/rotation is enabled (`preprocess_images=True`).
- **Geometric perspective correction:** `perspective_correct=True` currently records `"perspective_correct:not_implemented"` rather than applying projective homography unwarping.
- **Direct backend calls bypassing `ai_extraction`:** [`shift_calculations.py`](../backend/app/services/shift_calculations.py) checks `(worker_id, shift_date, start_time, end_time, location)` and holds only duplicate #2+; employer-aware conflict-group holding for raw API payloads without `ai_extraction` requires a future backend integration update.
