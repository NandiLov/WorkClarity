# WorkClarity AI Extraction Benchmark: Unseen PR #14 Dataset

This directory contains the frozen, reproducible benchmark results for the WorkClarity AI extraction engine evaluated against the unseen test dataset introduced in PR #14.

## Provenance and Commits

- **Source Dataset Commit**: `f9b8bc6` (`data_validation/test_data/unstructured_unseen`)
  - Description: Second set of unseen PDF and image schedules with handwritten ground-truth answer key.
- **Extraction Engine Commit**: `3f03fe1` (HEAD of `feature/ai-extraction`)
  - Description: Canonical WorkClarity AI extraction pipeline with structured JSON schema enforcement, image preprocessing (deskewing, aspect ratio preservation), worker disambiguation safeguards, and deterministic post-processing.
- **Benchmark Run Timestamps (UTC)**:
  - Gemini: `2026-11-20T11:54:23.949488+00:00`
  - NVIDIA: `2026-11-20T12:21:47.702514+00:00`

## Dataset Overview

The evaluation suite consists of 6 unseen documents comprising 28 expected shifts:

| Document | Format | Difficulty | Shifts | Key Characteristics Tested |
| :--- | :--- | :--- | :---: | :--- |
| `unseen_01_email_confirmation.pdf` | PDF | Medium | 4 | Email shift confirmation layout, single worker |
| `unseen_02_monthly_calendar.pdf` | PDF | Hard | 6 | Grid calendar layout, cancelled shift handling |
| `unseen_03_timesheet_clock.pdf` | PDF | Medium | 5 | Tabular timesheet, clock-in/out timestamps, overnight shift |
| `unseen_04_sms_two_senders.png` | PNG | Hard | 4 | Multi-sender SMS conversation, changed shift, multi-employer |
| `unseen_05_printed_rota_two_adas.jpg` | JPG | Hard | 4 | Printed multi-worker roster with similar worker names (`Ada Okoye` vs `Ada Lovelace`) |
| `unseen_06_missing_details_off_days.png` | PNG | Hard | 5 | Shift table with explicit OFF days, missing breaks, missing hours |

## Provider and Model Identifiers

- **Gemini**:
  - Provider Name: `gemini`
  - Model Identifier: `gemini-3.5-flash-lite`
  - Configuration: `temperature=0.2`, `max_output_tokens=8192`, `use_response_schema=True`, `pdf_dpi=200`, `preprocess_images=True`, `deskew=True`, `perspective_correct=False`
- **NVIDIA**:
  - Provider Name: `nvidia`
  - Model Identifier: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`
  - Endpoint: `https://integrate.api.nvidia.com/v1/chat/completions`
  - Configuration: `temperature=0.2`, `max_tokens=8192`, `reasoning_budget=2048`, `pdf_dpi=200`, `preprocess_images=True`, `deskew=True`, `perspective_correct=False`

## Benchmark Methodology

1. **Deterministic Execution**: The extraction engine executed against the frozen unseen documents with fixed configurations. No live API re-runs were conducted post-hoc to ensure complete reproducibility.
2. **Worker Attribution Safeguards**:
   - For multi-worker documents (specifically `unseen_05_printed_rota_two_adas.jpg`), the extraction pipeline targeted worker `Ada Okoye`.
   - The engine successfully filtered out non-target worker rows (`Ada Lovelace`) without cross-worker contamination or false positive shift attribution.
3. **No Prompt Tuning or Answer-Key Corrections**:
   - Zero prompt adjustments, regex additions, or answer-key modifications were made based on unseen dataset inspection.
   - All results reflect genuine out-of-distribution model performance.
4. **Comparator Tool Evaluation**:
   - Evaluated using `data_validation/tools/compare_extraction.py` against `data_validation/test_data/unstructured_unseen/answer_key.csv`.
   - Evaluated metrics include Shift Detection (TP/FP/FN, Precision, Recall, F1), All-Field Accuracy, Money-Field Accuracy (`hourly_rate`, `currency`), and Earnings-Critical Accuracy (`shift_date`, `start_time`, `end_time`, `break_minutes`, `hourly_rate`, `currency`, `shift_status`).

## Actual Benchmark Results

| Metric | Gemini 3.5 Flash Lite | NVIDIA Nemotron-3 Nano Omni |
| :--- | :---: | :---: |
| **Expected Shifts** | 28 | 28 |
| **Shifts Found** | 28 (100.0%) | 28 (100.0%) |
| **Shifts Missed (FN)** | 0 (0.0%) | 0 (0.0%) |
| **Invented Shifts (FP)** | 0 (0.0%) | 0 (0.0%) |
| **Precision / Recall / F1** | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| **Earnings-Critical Accuracy** | **28 / 28 (100.0%)** | **27 / 28 (96.4%)** |
| **Money Fields Accuracy** | **28 / 28 (100.0%)** | **27 / 28 (96.4%)** |
| **All Fields Exact Match** | 19 / 28 (67.9%) | 5 / 28 (17.9%) |
| **Details Invented** | 0 | 0 |
| **Details Dropped** | 9 | 38 |
| **Total Processing Time** | 30.42 s (avg 5.07 s/doc) | 115.94 s (avg 19.32 s/doc) |
| **Total Tokens** | 18,837 | 33,778 (incl. 10,648 reasoning) |

### Per-Field Accuracy Comparison

| Field | Gemini 3.5 Flash Lite | NVIDIA Nemotron-3 Nano Omni |
| :--- | :---: | :---: |
| `shift_date` | 100.0% (28/28) | 100.0% (28/28) |
| `start_time` | 100.0% (28/28) | 96.4% (27/28) |
| `end_time` | 100.0% (28/28) | 96.4% (27/28) |
| `break_minutes` | 100.0% (28/28) | 100.0% (28/28) |
| `employer_name` | 100.0% (28/28) | 57.1% (16/28) |
| `location` | 67.9% (19/28) | 32.1% (9/28) |
| `department` | 67.9% (19/28) | 28.6% (8/28) |
| `hourly_rate` | 100.0% (28/28) | 100.0% (28/28) |
| `currency` | 100.0% (28/28) | 100.0% (28/28) |
| `shift_status` | 100.0% (28/28) | 100.0% (28/28) |

## Known Comparator Difficulty Metadata Limitation

In the current version of `data_validation/tools/compare_extraction.py`, difficulty metadata is looked up exclusively from the primary dataset's `files.csv`. Because the unseen dataset in PR #14 was introduced in a separate directory (`data_validation/test_data/unstructured_unseen/`) with its own `files.csv`, the comparison tool did not load the directory-specific metadata mapping.

As a result:
- The `By difficulty` section of `comparison_report.txt` lists difficulty as `unknown` across all 28 shifts.
- The document-level difficulties are nonetheless fully known and tracked in `per_document_metrics.csv` (unseen_01: medium, unseen_02: hard, unseen_03: medium, unseen_04: hard, unseen_05: hard, unseen_06: hard).
- Updating `compare_extraction.py` to accept arbitrary dataset paths for metadata lookup is scheduled as tooling maintenance following PR #12.

## Publication Artifacts in this Directory

- `gemini_unseen_extracted.csv`: Complete extracted shift rows with confidence and worker attribution flags for Gemini.
- `nvidia_unseen_extracted.csv`: Complete extracted shift rows with confidence and worker attribution flags for NVIDIA.
- `gemini_comparison_report.txt`: Sanitised comparator report for Gemini 3.5 Flash Lite.
- `nvidia_comparison_report.txt`: Sanitised comparator report for NVIDIA Nemotron-3 Nano Omni.
- `gemini_differences.csv`: Field-level ground truth difference log for Gemini.
- `nvidia_differences.csv`: Field-level ground truth difference log for NVIDIA.
- `gemini_per_document_metrics.csv`: Per-document timing, token usage, and quality flags for Gemini.
- `nvidia_per_document_metrics.csv`: Per-document timing, token usage, and quality flags for NVIDIA.
- `gemini_extracted_review_queue.csv`: Sanitised review queue entries with attribution status for Gemini.
- `nvidia_extracted_review_queue.csv`: Sanitised review queue entries with attribution status for NVIDIA.
- `benchmark_summary.md`: Detailed comparative technical analysis.
- `SHA256SUMS.txt`: Cryptographic checksums of all tracked publication artifacts.
