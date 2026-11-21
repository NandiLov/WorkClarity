# WorkClarity AI Extraction: Unseen Benchmark Summary (PR #14 Dataset)

## Executive Summary

This report evaluates the zero-shot extraction generalization of two multimodal AI backends against the PR #14 unseen dataset (commit `f9b8bc6`):
1. **Google Gemini 3.5 Flash Lite**
2. **NVIDIA Nemotron-3 Nano Omni (30B A3B Reasoning)**

Both models achieved **100.0% Shift Detection Precision and Recall** (28/28 shifts detected, 0 missed, 0 hallucinated).

For downstream wage calculation, **Gemini 3.5 Flash Lite achieved 100.0% accuracy across all earnings-critical fields** (date, hours, breaks, pay rate, status), while **NVIDIA Nemotron-3 Nano Omni achieved 96.4%** due to an off-by-one hour error in a complex multi-sender SMS message.

---

## Comparative Performance Overview

| Metric | Gemini 3.5 Flash Lite | NVIDIA Nemotron-3 Nano Omni | Variance / Note |
| :--- | :---: | :---: | :--- |
| **Ground Truth Shifts** | 28 | 28 | 6 unseen documents |
| **Detected Shifts (TP)** | 28 | 28 | Both detected 100% of shifts |
| **Missed Shifts (FN)** | 0 | 0 | Zero recall omissions |
| **Invented Shifts (FP)** | 0 | 0 | Zero phantom shifts |
| **Detection Precision** | **100.0%** | **100.0%** | Perfect shift boundary isolation |
| **Detection Recall** | **100.0%** | **100.0%** | Perfect shift capture |
| **Detection F1 Score** | **1.000** | **1.000** | |
| **Earnings-Critical Accuracy** | **100.0% (28/28)** | **96.4% (27/28)** | Gemini +3.6% (critical for wages) |
| **Money Fields Accuracy** | **100.0% (28/28)** | **96.4% (27/28)** | Rate & currency verification |
| **All-Fields Exact Match** | **67.9% (19/28)** | **17.9% (5/28)** | Gemini +50.0% exact field match |
| **Invented Details** | 0 | 0 | Neither model fabricated values |
| **Dropped Details** | **9** | **38** | NVIDIA dropped 4.2x more details |
| **Total Benchmark Latency** | **30.42 s** | **115.94 s** | Gemini is 3.8x faster |
| **Average Document Latency** | **5.07 s** | **19.32 s** | |
| **Total Prompt Tokens** | **13,903** | **18,967** | |
| **Total Output Tokens** | **4,934** | **14,811** | NVIDIA generated 10,648 reasoning tokens |
| **Total Tokens Consumed** | **18,837** | **33,778** | NVIDIA consumed 1.79x more tokens |

---

## Per-Document Breakdown

### 1. Document Extraction Matrix

| Document | Key Challenge | Gemini Status | NVIDIA Status |
| :--- | :--- | :--- | :--- |
| `unseen_01_email_confirmation.pdf` (4 shifts) | Email confirmation, nested layout | 4/4 exact earnings | 4/4 exact earnings (dropped department) |
| `unseen_02_monthly_calendar.pdf` (6 shifts) | Monthly calendar grid, cancelled shift | 6/6 exact earnings (cancelled captured) | 6/6 exact earnings (cancelled captured) |
| `unseen_03_timesheet_clock.pdf` (5 shifts) | Tabular clock-in/out, overnight shift | 5/5 exact earnings (overnight 22:00-06:00 correct) | 5/5 exact earnings (overnight 22:00-06:00 correct) |
| `unseen_04_sms_two_senders.png` (4 shifts) | Multi-sender SMS, shift modification | 4/4 exact earnings (17:00-00:00 captured) | 3/4 exact earnings (1 hr discrepancy on 11/18) |
| `unseen_05_printed_rota_two_adas.jpg` (4 shifts) | Multi-worker rota, similar worker names | 4/4 exact earnings, Ada Okoye isolated | 4/4 exact earnings, Ada Okoye isolated |
| `unseen_06_missing_details_off_days.png` (5 shifts) | Explicit OFF days, missing breaks/times | 5/5 exact earnings, OFF days excluded | 5/5 exact earnings, OFF days excluded |

---

## Detailed Error & Difference Analysis

### Gemini 3.5 Flash Lite
- **Shift Boundary & Timing Errors**: 0
- **Money & Status Errors**: 0
- **Metadata Merging (Dropped Details: 9)**:
  - In `unseen_05_printed_rota_two_adas.jpg` (4 shifts): Location `hotel front` was merged into Department `hotel front (banquets)`, leaving the location column empty.
  - In `unseen_06_missing_details_off_days.png` (5 shifts): Location `depot` was merged into Department `depot (loading)`, leaving the location column empty.
  - *Impact*: Zero impact on earnings calculation. All shift times, hourly wages, dates, and worker attributions remained 100% accurate.

### NVIDIA Nemotron-3 Nano Omni
- **Shift Timing Discrepancy (1 shift)**:
  - In `unseen_04_sms_two_senders.png`: For the shift on `2026-11-18`, the model extracted `16:00-23:00` instead of the expected `17:00-00:00` (an off-by-one error originating from the SMS conversational context).
  - Also transcribed employer `quickserve foods` as `quickservice foods`.
- **Dropped Details (38 fields)**:
  - `unseen_01`: Dropped `department: shop floor` (merged with location).
  - `unseen_02`: Dropped `department: counter` across all 6 shifts (merged with location).
  - `unseen_04`: Dropped `department: loading` on 1 shift.
  - `unseen_05`: Dropped `employer_name`, `location`, and `department` across all 4 shifts.
  - `unseen_06`: Dropped `employer_name`, `location`, and `department` across all 5 shifts.

---

## Worker Attribution & Disambiguation Evaluation

A critical test in this benchmark is `unseen_05_printed_rota_two_adas.jpg`, which contains shifts for both `Ada Okoye` and `Ada Lovelace`.
- **Target Worker**: `Ada Okoye`
- **Safeguard Verification**:
  - Both Gemini and NVIDIA correctly attributed all 4 shifts to `Ada Okoye`.
  - Both models tagged the attribution status as `verified_target_worker`.
  - Shifts belonging to `Ada Lovelace` were cleanly filtered out.
  - Neither model generated conflicting shifts or duplicate cross-attributions.

---

## Latency and Token Economics

| Metric | Gemini 3.5 Flash Lite | NVIDIA Nemotron-3 Nano Omni | Delta |
| :--- | :---: | :---: | :---: |
| **Minimum Document Latency** | 3.26 s | 16.33 s | Gemini 5.0x faster |
| **Maximum Document Latency** | 6.50 s | 24.84 s | Gemini 3.8x faster |
| **Average Document Latency** | 5.07 s | 19.32 s | Gemini 3.8x faster |
| **Average Prompt Tokens / Doc** | 2,317 | 3,161 | NVIDIA +36.4% |
| **Average Output Tokens / Doc** | 822 | 2,469 (incl. reasoning) | NVIDIA +200.4% |
| **Reasoning Token Overhead** | 0 | 10,648 tokens total | ~1,775 reasoning tokens/doc |

### Key Takeaways
1. **Gemini 3.5 Flash Lite** provides optimal balance for production deployment: superior latency (5s/doc), lower token footprint, 100% earnings accuracy, and zero timing errors.
2. **NVIDIA Nemotron-3 Nano Omni** provides strong shift detection (100% F1) and good reasoning capabilities, but incurs significant reasoning token overhead (10.6k tokens) and 3.8x higher latency, with minor timing drift in colloquial SMS text.
