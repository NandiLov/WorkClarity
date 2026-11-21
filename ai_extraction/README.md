# WorkClarity — AI Schedule Extraction & Automatic Failover Pipeline

Repeatable, provider-independent AI schedule extraction service and benchmarking pipeline for PDF and image rosters, built around the shared 10-field extraction schema, mandatory individual worker confirmation safeguards, and deterministic scoring against [`data_validation/tools/compare_extraction.py`](../data_validation/tools/compare_extraction.py).

## Architecture Overview

| Module | Responsibility |
|---|---|
| [`orchestrator.py`](orchestrator.py) | Reusable extraction orchestration service (`ExtractionOrchestrator`, `ExtractionServiceConfig`, `OrchestratedExtractionResult`, `run_provider_attempts`) supporting configurable primary + fallback providers, failure classification, exponential backoff retries, total processing deadlines, secret-free telemetry (`to_public_summary`), and FastAPI-ready byte/file entry points (`extract_bytes`, `extract_file`). |
| [`schema.py`](schema.py) | Shared 10-field extraction contract (`SharedShiftSchema`, `CSV_COLUMNS`, `CONFIRMATION_CSV_COLUMNS`), deterministic non-guessing normalisation, multi-envelope parsing, semantic invalid/empty rejection, safe truncated-JSON partial recovery (`parse_and_validate_model_json`), conflicting-duplicate grouping (`resolve_conflict_group`), raw/normalised/corrected separation (`apply_worker_correction`), and mandatory individual worker review safeguards (`ExtractedShiftRecord`). |
| [`prompt.py`](prompt.py) | V2 extraction prompts (`SYSTEM_PROMPT`, `build_user_prompt`) enforcing concise reasoning, unambiguous `week_of` header extraction, row-by-row alignment, missing (`null`) vs explicit `0` break preservation, `source_page`/`source_row`, and target-worker attribution. |
| [`pdf_utils.py`](pdf_utils.py) | Renders single/multi-page `.pdf` and `.png`/`.jpg` schedules from disk (`load_document_pages`) or uploaded bytes (`load_document_pages_from_bytes`) at configurable DPI (`200` default). Uses cross-platform `pypdfium2` + `Pillow` as the primary backend for Windows, macOS, and Linux/Cloud Run, with explicit fallbacks (`pymupdf`, `poppler-utils` `pdftoppm`, macOS `CoreGraphics`) and actionable `MissingRenderingDependencyError` diagnostics, plus optional non-destructive deskewing/contrast preprocessing (`preprocess_images=False` default). |
| [`providers/base.py`](providers/base.py) | Provider adapter interface (`ExtractionAdapter`), token/attempt telemetry (`TokenUsage`, `RequestAttemptRecord`), Gemini/OpenAI token reconciliation (`parse_token_usage`), transient vs permanent HTTP classification, `.env` credential lookup (`get_api_key`), and secret redaction (`redact_secret`). |
| [`providers/gemini.py`](providers/gemini.py) | Gemini multimodal adapter (`GeminiExtractionAdapter`) targeting `generativelanguage.googleapis.com`, defaulting to `gemini-3.5-flash-lite` with OpenAPI-subset `GEMINI_RESPONSE_SCHEMA`, using `GEMINI_API_KEY` independently. |
| [`providers/nvidia.py`](providers/nvidia.py) | NVIDIA multimodal `image_url` adapter (`NvidiaExtractionAdapter`) targeting `https://integrate.api.nvidia.com/v1/chat/completions`, defaulting to `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (`max_tokens=8192`, `reasoning_budget=2048`, `temperature=0.2`), using `NVIDIA_API_KEY` independently. |
| [`benchmark.py`](benchmark.py) | Runs single-provider benchmarks across the 14 synthetic schedules (or `--files` subsets) reusing `run_provider_attempts`, validates rendering dependencies upfront (`ensure_rendering_dependencies`), executes offline replays (`--replay-from`), isolates `answer_key.csv` strictly to scoring, evaluates unconfirmed vs confirmed eligibility separately against [`shift_calculations.py`](../backend/app/services/shift_calculations.py), and writes versioned output directories. |
| [`tests/test_ai_extraction.py`](tests/test_ai_extraction.py) | Fresh-checkout reproducible unit and regression test suite (`58` tests across Phase 1, V2, V3, V3.1, Phase 4 automatic failover, cross-platform PDF/image rendering, and missing-dependency safeguards — zero skipped tests). |

## Installation & Cross-Platform Dependencies

### Supported Python Versions & Pinned Packages

- **Runtime dependencies ([`requirements.txt`](../requirements.txt)):**
  - `fastapi==0.162.5` and `uvicorn==0.54.0` (existing backend dependencies, preserved unchanged)
  - `pypdfium2==5.14.0` and `Pillow==13.0.0` (cross-platform PDF rasterization and image decoding/deskewing via prebuilt wheels; no C compiler or macOS-native APIs required)
- **Test/dev dependencies ([`requirements-dev.txt`](../requirements-dev.txt)):** `pytest==9.2.0`, `httpx2==2.16.0`
- **Python compatibility:** Targets Python 3.10+ (including 3.13, 3.14, and verified locally on **Python 3.15.1** with prebuilt `cp315`/`py3` wheels for `pypdfium2==5.14.0` and `Pillow==13.0.0`). Windows does **not** depend on macOS `CoreGraphics` or `poppler-utils`.

### Clean Environment Setup

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m pytest backend/tests data_validation/tests ai_extraction/tests -v
```

**Windows (PowerShell):**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m pytest backend/tests data_validation/tests ai_extraction/tests -v
```

**Windows (Command Prompt):**

```cmd
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m pytest backend\tests data_validation\tests ai_extraction\tests -v
```

**Linux / Google Cloud Run container image:**

```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
# Optional fallback only if pypdfium2 wheels are unavailable for the base architecture:
# RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils
```

### PDF Rendering & Image Preprocessing Backend Order

| Stage | Priority / Fallback Order | Notes |
|---|---|---|
| **PDF rendering** (`PDF_RENDERING_BACKEND_ORDER`) | 1. `pypdfium2` (`+ Pillow`) → 2. `pymupdf` (`fitz`) → 3. `pdftoppm` (`poppler-utils`) → 4. `coregraphics` (`CoreGraphics`) | `pypdfium2==5.14.0` + `Pillow==13.0.0` serves Windows, macOS, and Linux identically without OS-native frameworks. Missing backends raise `MissingRenderingDependencyError` with install instructions rather than silently skipping PDFs. |
| **Image preprocessing** (`IMAGE_PREPROCESSING_BACKEND_ORDER`, when `preprocess_images=True`) | 1. `pillow` (`PIL.Image`) → 2. `coregraphics` (`ImageIO` + `CoreGraphics`) → 3. `pure_python_png` (PNG only) | Uses `Image.Resampling.BICUBIC` when `Pillow` is active. JPEG preprocessing without `Pillow` or macOS `CoreGraphics` raises `MissingRenderingDependencyError`. |

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
# Run all AI extraction unit, cross-platform rendering, and failover tests (0 skipped; no live API calls)
.venv/bin/python -m unittest discover -s ai_extraction/tests -v

# Replay saved benchmark responses offline (requires local benchmark_output artifacts from a prior run)
.venv/bin/python -m ai_extraction.benchmark \
  --replay-from ai_extraction/benchmark_output/gemini_35_lite_full/benchmark_results.json \
  --run-name v3_replay_check
```

#### Regression Fixtures vs. Historical Benchmark Replay

- **Deterministic regression fixtures ([`tests/test_ai_extraction.py`](tests/test_ai_extraction.py)):** Offline V1 partial-recovery tests, V3 Gemini/NVIDIA full-dataset target replay tests, and V3.1 conflicting-duplicate tests run against minimal, sanitised in-test regression fixtures derived from the parser contracts and synthetic answer key schema. They never commit raw provider dumps, chain-of-thought reasoning traces, or API credentials, and require zero local `ai_extraction/benchmark_output/` files on fresh checkouts.
- **Historical benchmark replay (`python -m ai_extraction.benchmark --replay-from ...`):** Used interactively to re-score preserved local `benchmark_output/*/benchmark_results.json` artifacts from earlier live benchmark runs (which remain gitignored).

## Failure Handling & Worker Safety Safeguards

- **Failed extraction never looks like an empty schedule:** Total failure sets `extraction_status="failed"`, `is_failed=True`, `is_empty_schedule=False`, `manual_entry_required=True`, and preserves `primary_failure_reason` / `fallback_failure_reason`.
- **Partial extraction never masquerades as complete:** Truncated partial recoveries set `extraction_status="partial"`, `is_partial=True`, `is_complete=False`, `succeeded=False`, `manual_entry_required=True`, and lower confidence on recovered rows (`confidence="low"`, `review_reasons` includes `"partial_json_recovery"`).
- **Zero cross-provider or cross-attempt merging:** Only one provider attempt's parsed result is returned; retries and failovers cannot duplicate shifts.
- **Conflicting duplicate protection:** Identical shift slots with conflicting financial/break/detail values are grouped into `conflict_groups` (`requires_conflict_resolution=True`) and cannot become `"confirmed"` or contribute to earnings until resolved explicitly via `resolve_conflict_group`.
- **Mandatory individual worker confirmation:** Regardless of `confidence="high"`, every AI-extracted shift starts with `confirmation_status="needs_review"`, `requires_worker_confirmation=True`, `requires_individual_review=True`, and `eligible_for_bulk_confirmation=False`, preserving `raw_values`, `normalised`, and `worker_corrected_values` separately.
- **Secret and reasoning protection:** API keys are scrubbed per adapter via `redact_secret` without cross-provider key access, `to_log_summary()` emits strictly non-sensitive operational counters/categories, and operational logs exclude `raw_response`, `reasoning_text`, shift contents, and local directory paths.
- **Data-processing policy for secondary AI providers:** Enabling automatic failover (`AI_EXTRACTION_FALLBACK_ENABLED=true`) transmits worker schedule documents to a second external vendor when the primary provider fails. Before processing real worker documents in production, ensure an approved data-processing agreement (DPA) and worker privacy notice cover every configured primary and fallback vendor.

## Benchmark Evidence vs. Automated Failover Tests

All results below are derived strictly from recorded benchmark runs and the automated mocked suite; individual provider runs, offline replays, the two-run V3.1 combined outcome, and mocked failover tests are reported separately.

| Evaluation / Run | Run Mode | Docs Evaluated | Shift Detection Recall (`Matched / Expected`) | All-Field Exact (`all_ok`) | Money-Field Exact (`money_ok`) | Earnings-Critical Exact (`earnings_critical_ok`) | Notes |
|---|---|---|---|---|---|---|---|
| **NVIDIA V1 (`v1_baseline`)** | Live API (`nvidia`) | 14 / 14 | **53 / 62** (85.5%) | 51 / 62 (82.3%) | 51 / 62 (82.3%) | *n/a* (pre-V3 comparator) | `2` JSON validation failures (`img_05` truncated, `pdf_06` reasoning budget exhausted); `68,950` tokens; `339.99s`. |
| **NVIDIA V1 (`v3_replay_v1_baseline`)** | Offline V3 replay | 14 / 14 | **57 / 62** (91.9%) | 55 / 62 (88.7%) | 55 / 62 (88.7%) | 55 / 62 (88.7%) | Recovers 4 closed shifts safely from truncated `img_05` JSON as low-confidence `needs_review`. |
| **NVIDIA V2 (`v2`)** | Live API (`nvidia`) | 14 / 14 | **62 / 62** (100.0%) | 53 / 62 (85.5%) | 60 / 62 (96.8%) | *n/a* (pre-V3 comparator) | `reasoning_budget=2048`, `max_tokens=8192`, bounded retries; `0` JSON failures; `68,389` tokens; `506.00s`. |
| **NVIDIA V2 (`v3_replay_v2`)** | Offline V3 replay | 14 / 14 | **62 / 62** (100.0%) | 53 / 62 (85.5%) | 60 / 62 (96.8%) | 56 / 62 (90.3%) | Separates `shift_status` mismatches (`56/62` earnings-critical) from non-money location/employer diffs (`53/62` all-field). |
| **Gemini Pre-V3 (`gemini_35_lite_full`)** | Live API (`gemini`) | 14 / 14 | **57 / 62** (91.9%) | 54 / 62 (87.1%) | 54 / 62 (87.1%) | *n/a* (pre-V3 comparator) | `img_02` returned list-wrapped envelope `[...]`, producing 1 phantom record in pre-V3 parser; `42,666` tokens; `119.58s`. |
| **Gemini Pre-V3 (`v3_replay_gemini_35_lite_full`)** | Offline V3 replay | 14 / 14 | **62 / 62** (100.0%) | 57 / 62 (91.9%) | 59 / 62 (95.2%) | 57 / 62 (91.9%) | V3 envelope unwrapping recovers all 5 `img_02` shifts with `0` phantom/invalid records; same `42,666` tokens / `119.58s`. |
| **Gemini V3.1 Deskew (`v3_1_gemini_final`)** | Live API (`gemini`, `preprocess_images=True`) | 14 / 14 attempted (**12 succeeded**, 2 transient `503`) | **54 / 62** overall (87.1%) / **54 / 54** (100.0% on 12 succeeded docs) | **54 / 62** overall / **54 / 54** on 12 docs | **54 / 62** overall / **54 / 54** on 12 docs | **54 / 62** overall / **54 / 54** on 12 docs | `pdf_01` and `img_04` failed all 3 attempts with transient Gemini `503 UNAVAILABLE`; `0` invented/dropped details on completed docs; `37,176` tokens; `114.30s`. |
| **NVIDIA V3.1 Manual Fallback (`v3_1_nvidia_fallback_retry`)** | Live API (`nvidia` subset) | 2 / 14 (`pdf_01`, `img_04`) | **8 / 8** (100.0%) | **8 / 8** (100.0%) | **8 / 8** (100.0%) | **8 / 8** (100.0%) | Manual follow-up run on the 2 documents that hit Gemini `503`; `8,825` tokens; `27.40s`. |
| **Combined V3.1 Two-Run Result** (`v3_1_gemini_final` [12 docs] + `v3_1_nvidia_fallback_retry` [2 docs]) | Separate live runs | 14 / 14 | **62 / 62** (100.0%) | **62 / 62** (100.0%) | **62 / 62** (100.0%) | **62 / 62** (100.0%) | Combined across separate Gemini and NVIDIA runs before automated Phase 4 failover was implemented. |
| **Phase 4 `ExtractionOrchestrator` Automatic Failover** | **Mocked providers** (no live API calls) | Synthetic mocked schedules | *Not benchmarked live* | *Not benchmarked live* | *Not benchmarked live* | *Not benchmarked live* | Verified via `20` deterministic mocked tests covering `429`/`5xx`/timeout/malformed-JSON/auth failover, partial recovery, suspicious empty schedules, cooperative deadlines, key redaction, and earnings exclusion. |

## Known Limitations & Environment Dependencies

- **Windows & Linux CI verification:** Primary PDF (`pypdfium2==5.14.0`) and image (`Pillow==13.0.0`) backends were verified end-to-end on macOS Python 3.15.1 including test simulations with macOS `CoreGraphics`, `ImageIO`, `pymupdf`, and `pdftoppm` disabled, while native execution on Windows and Linux environments remains to be run on those target OSes.
- **Cooperative deadline enforcement (not a hard wall-clock interrupt):** Document preprocessing time is included in `total_deadline_seconds` before calling providers, and `urllib.request.urlopen` socket timeouts are clamped to the remaining deadline budget; however, synchronous CPU preprocessing or a stalled OS DNS lookup cannot be forcibly interrupted mid-operation until control returns to Python.
- **Python 3.15 / `.venv` test packages:** `pytest==9.2.0` and `httpx2==2.16.0` ([`requirements-dev.txt`](../requirements-dev.txt)) allow executing `backend/tests/`, `data_validation/tests/`, and `ai_extraction/tests/` via `pytest`.
- **Optional imaging/PDF fallbacks:** [`requirements.txt`](../requirements.txt) installs `pypdfium2==5.14.0` and `Pillow==13.0.0` directly across Windows, macOS, and Linux/Cloud Run; `pymupdf`, `poppler-utils` (`pdftoppm`), and macOS `CoreGraphics` remain optional fallbacks.
- **Geometric perspective correction:** `perspective_correct=True` currently records `"perspective_correct:not_implemented"` rather than applying projective homography unwarping.
- **Direct backend calls bypassing `ai_extraction`:** [`shift_calculations.py`](../backend/app/services/shift_calculations.py) checks `(worker_id, shift_date, start_time, end_time, location)` and holds only duplicate #2+; employer-aware conflict-group holding for raw API payloads without `ai_extraction` requires a future backend integration update.
