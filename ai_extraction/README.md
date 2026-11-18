# WorkClarity — AI Extraction Phase 1 & V2 Benchmark Pipeline

Repeatable, provider-independent AI schedule extraction and benchmarking pipeline for PDF and image rosters, built around the shared 10-field extraction schema and scored against [`data_validation/tools/compare_extraction.py`](../data_validation/tools/compare_extraction.py).

## Components

| Module | Responsibility |
|---|---|
| [`schema.py`](schema.py) | Shared 10-field extraction contract (`SharedShiftSchema`, `CSV_COLUMNS`), deterministic non-guessing normalisation, safe truncated-JSON partial recovery (`parse_and_validate_model_json`), raw/corrected value preservation (`apply_worker_correction`), and mandatory individual review safeguards (`ExtractedShiftRecord`). |
| [`prompt.py`](prompt.py) | V2 extraction prompts (`SYSTEM_PROMPT`, `build_user_prompt`) enforcing concise thinking, unambiguous `week_of` header extraction, row-by-row alignment on wide/tilted tables, missing (`null`) vs explicit `0` break preservation, `source_page`/`source_row`, and target-worker attribution. |
| [`pdf_utils.py`](pdf_utils.py) | Renders single/multi-page `.pdf` and `.png`/`.jpg` schedules at configurable DPI (`200` default). Supports Linux/Cloud Run backends (`pypdfium2`, `pymupdf`, `poppler-utils` `pdftoppm`) and macOS `CoreGraphics`, plus optional non-destructive in-memory deskew/autocontrast preprocessing (`--preprocess-images`, off by default). |
| [`providers/base.py`](providers/base.py) | Provider adapter interface (`ExtractionAdapter`), token/attempt telemetry (`TokenUsage`, `RequestAttemptRecord`), transient vs permanent HTTP error classification, `.env` credential lookup (`get_api_key`), and secret redaction (`redact_secret`). |
| [`providers/nvidia.py`](providers/nvidia.py) | NVIDIA multimodal `image_url` adapter targeting `https://integrate.api.nvidia.com/v1/chat/completions` (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`), configured with V2 defaults `max_tokens=8192`, `reasoning_budget=2048`, `temperature=0.2`, and `max_retries=2`. |
| [`providers/gemini.py`](providers/gemini.py) | Future Gemini provider adapter (`GeminiExtractionAdapter`) implementing the same `ExtractionAdapter` contract using `GEMINI_API_KEY`. |
| [`benchmark.py`](benchmark.py) | Runs extraction with bounded retries and attempt-level telemetry across all 14 synthetic documents (or selected `--files`) without ever passing `answer_key.csv` to the extractor, writes versioned outputs (`v2`, `v3`, ...), evaluates against `compare_extraction.py`, and provides offline V1 recovery verification (`evaluate_v1_offline_recovery`). |
| [`tests/test_ai_extraction.py`](tests/test_ai_extraction.py) | Automated mocked regression suite (23 tests) covering V1 + V2 schema, truncation/reasoning exhaustion, safe partial recovery, retry & token accounting, duplicate prevention, worker-attribution safeguards, versioned outputs, and offline V1 recovery. |

## Updated V2 Configuration Defaults

| Parameter | Default | Purpose |
|---|---|---|
| `model_id` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | Audited V1/V2 NVIDIA multimodal model |
| `max_tokens` | `8192` | Prevents `finish_reason="length"` truncation on multi-row tables |
| `reasoning_budget` | `2048` | Caps NVIDIA internal reasoning tokens before JSON emission |
| `temperature` | `0.2` | Breaks greedy `0.0` token repetition loops while staying near-deterministic |
| `max_retries` | `2` (max 3 attempts) | Retries transient API errors (with exponential backoff), empty, truncated, or malformed JSON |
| `dpi` | `200` | Retains 200 DPI baseline resolution (configurable via `--dpi`) |
| `preprocess_images` | `false` | Optional in-memory deskew/autocontrast disabled initially to avoid confounding V2 comparison |

### Cloud Run (Linux) PDF Rendering Dependency

In a Linux container (such as Google Cloud Run), ensure at least one PDF rendering backend is installed:

- Preferred Python wheel: add `pypdfium2` (or `pymupdf`) to the container requirements, **or**
- System binary: `apt-get install -y poppler-utils` (provides `pdftoppm`, automatically detected by `pdf_utils.py`).

## Mandatory AI Confirmation & Review Safeguards

- **Every AI-extracted shift** enters the workflow with `requires_worker_confirmation=True`, `confirmation_status="needs_review"`, `requires_individual_review=True`, and `eligible_for_bulk_confirmation=False` (no AI-extracted shift can be bulk-confirmed in MVP).
- Explicit `review_reasons` flag low/medium confidence, missing money fields, missing `employer_name` or `location`, `cancelled`/`changed` statuses, ambiguous/unverified worker attribution on multi-employee rosters, and partially recovered truncated JSON shifts.
- Original `raw_values` and `normalised` values remain preserved separately when worker corrections are stored in `worker_corrected_values` via `apply_worker_correction`.
- Existing CSV upload and backend earnings validation rules remain completely unchanged.

## Running Automated Regression Tests (Offline / Mocked)

```bash
.venv/bin/python -m unittest discover -s ai_extraction/tests -v
```

To verify safe partial JSON recovery offline on preserved V1 baseline outputs (`ai_extraction/benchmark_output/v1_baseline/benchmark_results.json`):

```bash
.venv/bin/python -c "import json; from ai_extraction.benchmark import evaluate_v1_offline_recovery; print(json.dumps(evaluate_v1_offline_recovery(), indent=2))"
```

## Retesting the Three Problematic V1 Documents (Live NVIDIA API)

Export `NVIDIA_API_KEY` in your shell, then retest only the 3 failed/misaligned V1 files into a versioned output folder while keeping the full 62-shift comparison methodology intact:

```bash
export NVIDIA_API_KEY="your-nvidia-api-key"
.venv/bin/python -m ai_extraction.benchmark \
  --provider nvidia \
  --run-name v2_retest_3files \
  --files img_05_cropped_perspective.jpg pdf_06_team_roster_multi_employee.pdf img_07_photo_missing_details.jpg
```

## Running the Complete NVIDIA V2 Benchmark (All 14 Synthetic Documents)

```bash
export NVIDIA_API_KEY="your-nvidia-api-key"
.venv/bin/python -m ai_extraction.benchmark --provider nvidia --run-name v2
```

Each benchmark run creates a separate versioned directory under `ai_extraction/benchmark_output/` (automatically incrementing `v2`, `v3`, ... if `--run-name` already exists), preserving `v1_baseline/` and all earlier runs cleanly out of Git.
