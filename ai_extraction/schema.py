"""Shared extraction schema, deterministic normalisation, partial recovery, and confirmation safeguards."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

EXTRACTION_FIELDS: tuple[str, ...] = (
    "shift_date",
    "start_time",
    "end_time",
    "break_minutes",
    "employer_name",
    "location",
    "department",
    "hourly_rate",
    "currency",
    "shift_status",
)

MONEY_FIELDS: tuple[str, ...] = (
    "shift_date",
    "start_time",
    "end_time",
    "break_minutes",
    "hourly_rate",
    "currency",
)

CSV_COLUMNS: tuple[str, ...] = ("file_name", *EXTRACTION_FIELDS)
CONFIRMATION_CSV_COLUMNS: tuple[str, ...] = (
    *CSV_COLUMNS,
    "confidence",
    "confirmation_status",
    "requires_worker_confirmation",
    "requires_individual_review",
    "eligible_for_bulk_confirmation",
    "source_page",
    "source_row",
    "worker_attribution_status",
    "partially_recovered",
    "conflict_group_id",
    "conflicting_fields",
    "requires_conflict_resolution",
    "review_reasons",
)

EMPTY_MARKERS: frozenset[str] = frozenset(
    {
        "",
        "-",
        "\u2013",
        "\u2014",
        "n/a",
        "na",
        "null",
        "unknown",
        "tbc",
        "tbd",
        "?",
        "missing",
    }
)

EXPLICIT_ZERO_BREAK_WORDS: frozenset[str] = frozenset(
    {
        "0",
        "0m",
        "0 min",
        "0 mins",
        "0 minute",
        "0 minutes",
        "no break",
        "none",
        "nil",
    }
)

VALID_SHIFT_STATUSES: frozenset[str] = frozenset({"scheduled", "cancelled", "changed"})
ALLOWED_CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")
TRUNCATION_FINISH_REASONS: frozenset[str] = frozenset({"length", "max_tokens"})

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_TAIL_RE = re.compile(r"<think>.*$", flags=re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*(.*?)```",
    flags=re.DOTALL | re.IGNORECASE,
)
_OPEN_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*", flags=re.IGNORECASE)
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_SHIFTS_ARRAY_START_RE = re.compile(r'"shifts"\s*:\s*\[')
_WEEK_OF_KEY_RE = re.compile(r'"week_of"\s*:\s*')

_DATE_FORMATS_WITH_YEAR: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%a %d %b %Y",
    "%a, %d %b %Y",
    "%a %d %B %Y",
    "%a, %d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%a %b %d, %Y",
)

_DATE_FORMATS_NO_YEAR: tuple[str, ...] = (
    "%a %d %b",
    "%a, %d %b",
    "%a %d %B",
    "%a, %d %B",
    "%d %b",
    "%d %B",
)

_TIME_FORMATS: tuple[str, ...] = (
    "%H:%M",
    "%H:%M:%S",
    "%I:%M %p",
    "%I:%M%p",
    "%I %p",
    "%I%p",
)


class SharedShiftSchema(BaseModel):
    """Canonical 10-field normalised shift contract shared across providers."""

    model_config = ConfigDict(extra="forbid")

    shift_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    break_minutes: str | None = None
    employer_name: str | None = None
    location: str | None = None
    department: str | None = None
    hourly_rate: str | None = None
    currency: str | None = None
    shift_status: Literal["scheduled", "cancelled", "changed"] = "scheduled"


class ExtractedShiftRecord(BaseModel):
    """Extracted shift retaining raw values, normalised values, and review safeguards."""

    model_config = ConfigDict(extra="forbid")

    raw_values: dict[str, Any] = Field(default_factory=dict)
    normalised: SharedShiftSchema
    worker_corrected_values: SharedShiftSchema | None = None
    source_page: int | None = None
    source_row: int | None = None
    worker_name: str | None = None
    worker_attribution_status: Literal[
        "not_applicable",
        "verified_target_worker",
        "ambiguous_or_unverified",
    ] = "not_applicable"
    confidence: Literal["high", "medium", "low"] = "medium"
    uncertain_fields: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    partially_recovered: bool = False
    confirmation_status: Literal["unconfirmed", "needs_review", "confirmed", "rejected"] = (
        "needs_review"
    )
    requires_worker_confirmation: bool = True
    requires_individual_review: bool = True
    eligible_for_bulk_confirmation: bool = False
    deduplicated_provenance: list[dict[str, Any]] = Field(default_factory=list)
    conflict_group_id: str | None = None
    conflicting_fields: list[str] = Field(default_factory=list)
    requires_conflict_resolution: bool = False
    conflict_resolved: bool = False

    def effective_values(self) -> SharedShiftSchema:
        """Return worker-corrected values if present, otherwise normalised extracted values."""
        return self.worker_corrected_values or self.normalised

    def apply_worker_correction(
        self,
        changes: dict[str, Any],
        *,
        confirm_individually: bool = False,
        resolve_conflict: bool = False,
    ) -> ExtractedShiftRecord:
        """Store worker edits separately while preserving original raw and normalised values."""
        base = self.effective_values().model_dump()
        for key, val in changes.items():
            if key in EXTRACTION_FIELDS:
                base[key] = val
        updated_schema = SharedShiftSchema.model_validate(base)
        is_resolved = self.conflict_resolved or resolve_conflict
        blocked_by_conflict = self.requires_conflict_resolution and not is_resolved
        new_status: Literal["unconfirmed", "needs_review", "confirmed", "rejected"]
        if self.confirmation_status == "rejected" and not confirm_individually:
            new_status = "rejected"
        elif confirm_individually and not blocked_by_conflict:
            new_status = "confirmed"
        else:
            new_status = "needs_review"

        updated_reasons = list(self.review_reasons)
        if (
            confirm_individually
            and blocked_by_conflict
            and "conflict_resolution_required_before_confirmation" not in updated_reasons
        ):
            updated_reasons.append("conflict_resolution_required_before_confirmation")

        return self.model_copy(
            update={
                "worker_corrected_values": updated_schema,
                "confirmation_status": new_status,
                "conflict_resolved": is_resolved,
                "review_reasons": updated_reasons,
            }
        )

    def to_compare_csv_row(self, file_name: str) -> dict[str, str]:
        """Format as an 11-column row compatible with compare_extraction.py."""
        data = self.effective_values().model_dump()
        row: dict[str, str] = {"file_name": file_name}
        for field in EXTRACTION_FIELDS:
            val = data[field]
            row[field] = "" if val is None else str(val)
        return row


class DocumentExtractionResult(BaseModel):
    """Complete normalised output, partial recovery telemetry, and validation state."""

    model_config = ConfigDict(extra="forbid")

    file_name: str
    model_id: str
    week_of: str | None = None
    target_worker: str | None = None
    shifts: list[ExtractedShiftRecord] = Field(default_factory=list)
    filtered_other_worker_shifts: int = 0
    deduplicated_shifts: int = 0
    deduplicated_records: list[dict[str, Any]] = Field(default_factory=list)
    conflicting_duplicate_count: int = 0
    conflict_groups: list[dict[str, Any]] = Field(default_factory=list)
    invalid_or_empty_records: int = 0
    rejected_records: list[dict[str, Any]] = Field(default_factory=list)
    partially_recovered_shift_count: int = 0
    incomplete_extraction: bool = False
    partial_recovery_triggered: bool = False
    json_validation_failure: bool = False
    json_validation_errors: list[str] = Field(default_factory=list)

    def resolve_conflict_group(
        self,
        conflict_group_id: str,
        *,
        selected_source_row: int | None = None,
        selected_shift_index: int | None = None,
        worker_corrections: dict[str, Any] | None = None,
        confirm_selected: bool = True,
    ) -> DocumentExtractionResult:
        """
        Explicitly resolve a conflicting duplicate group by selecting one shift record
        (optionally applying worker corrections and confirming it) and marking all other
        records in the same conflict group as 'rejected' while preserving them.
        """
        member_indices = [
            idx
            for idx, rec in enumerate(self.shifts)
            if rec.conflict_group_id == conflict_group_id
        ]
        if len(member_indices) < 2:
            raise ValueError(
                f"Conflict group {conflict_group_id!r} must contain at least 2 shift records"
            )

        if selected_shift_index is not None:
            if selected_shift_index not in member_indices:
                raise ValueError(
                    f"selected_shift_index={selected_shift_index} is not in {conflict_group_id!r}"
                )
            chosen_idx = selected_shift_index
        elif selected_source_row is not None:
            matches = [
                idx
                for idx in member_indices
                if self.shifts[idx].source_row == selected_source_row
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"selected_source_row={selected_source_row} did not uniquely match a member of {conflict_group_id!r}"
                )
            chosen_idx = matches[0]
        else:
            raise ValueError(
                "Either selected_source_row or selected_shift_index must be specified"
            )

        updated_shifts: list[ExtractedShiftRecord] = []
        for idx, rec in enumerate(self.shifts):
            if idx == chosen_idx:
                updated_shifts.append(
                    rec.apply_worker_correction(
                        worker_corrections or {},
                        confirm_individually=confirm_selected,
                        resolve_conflict=True,
                    )
                )
            elif idx in member_indices:
                reasons = list(rec.review_reasons)
                if "rejected_in_conflict_resolution" not in reasons:
                    reasons.append("rejected_in_conflict_resolution")
                updated_shifts.append(
                    rec.model_copy(
                        update={
                            "confirmation_status": "rejected",
                            "conflict_resolved": True,
                            "review_reasons": reasons,
                        }
                    )
                )
            else:
                updated_shifts.append(rec)

        return self.model_copy(update={"shifts": updated_shifts})


def resolve_conflict_group(
    document: DocumentExtractionResult,
    conflict_group_id: str,
    *,
    selected_source_row: int | None = None,
    selected_shift_index: int | None = None,
    worker_corrections: dict[str, Any] | None = None,
    confirm_selected: bool = True,
) -> DocumentExtractionResult:
    """Resolve an explicit conflict group on a DocumentExtractionResult."""
    return document.resolve_conflict_group(
        conflict_group_id,
        selected_source_row=selected_source_row,
        selected_shift_index=selected_shift_index,
        worker_corrections=worker_corrections,
        confirm_selected=confirm_selected,
    )


def _is_empty_marker(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in EMPTY_MARKERS
    return False


def _clean_text(value: Any) -> str | None:
    if _is_empty_marker(value):
        return None
    if isinstance(value, bool):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return None if text.lower() in EMPTY_MARKERS else text


def _parse_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        iv = int(value)
        return iv if iv >= 1 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            iv = int(text)
            return iv if iv >= 1 else None
    return None


def _extract_reference_year(week_of: Any, raw_shifts: list[dict[str, Any]]) -> int | None:
    if isinstance(week_of, str):
        m = _YEAR_RE.search(week_of)
        if m:
            return int(m.group(1))
    for item in raw_shifts:
        val = item.get("shift_date")
        if isinstance(val, str):
            m = _YEAR_RE.search(val)
            if m:
                return int(m.group(1))
    return None


def _normalise_date(
    value: Any,
    reference_year: int | None,
) -> tuple[str | None, str | None]:
    """Return (normalised_iso_date, warning_or_none). Never invents an unknown date."""
    if _is_empty_marker(value):
        return None, None
    if isinstance(value, bool):
        return None, "shift_date is boolean; cannot interpret as date"
    text = re.sub(r"\s+", " ", str(value)).strip()
    for fmt in _DATE_FORMATS_WITH_YEAR:
        try:
            return datetime.strptime(text, fmt).date().isoformat(), None
        except ValueError:
            continue
    if reference_year is not None:
        for fmt in _DATE_FORMATS_NO_YEAR:
            try:
                parsed = datetime.strptime(f"{text} {reference_year}", f"{fmt} %Y").date()
                return (
                    parsed.isoformat(),
                    f"shift_date year {reference_year} inherited from week heading",
                )
            except ValueError:
                continue
    return None, f"unparseable shift_date {text!r}; left blank for worker review"


def _normalise_time(value: Any) -> tuple[str | None, str | None]:
    """Return (24h HH:MM, warning_or_none). Handles 12h AM/PM without guessing."""
    if _is_empty_marker(value):
        return None, None
    if isinstance(value, bool):
        return None, "time value is boolean; left blank for worker review"
    text = re.sub(r"\s+", " ", str(value)).strip().upper()
    text = re.sub(r"(?<=\d)\.(?=\d{2}\s*(AM|PM)?$)", ":", text)
    text = text.replace(".", "")
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M"), None
        except ValueError:
            continue
    return None, f"unparseable time {str(value)!r}; left blank for worker review"


def _normalise_break_minutes(value: Any) -> tuple[str | None, str | None]:
    """Preserve explicit zero while keeping missing/unknown break values as None."""
    if _is_empty_marker(value):
        return None, None
    if isinstance(value, bool):
        return None, "break_minutes is boolean; left blank for worker review"
    if isinstance(value, int):
        if value < 0:
            return None, f"negative break_minutes {value}; left blank for worker review"
        return str(value), None
    if isinstance(value, float):
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            return None, f"non-integer break_minutes {value!r}; left blank for worker review"
        return str(int(value)), None

    text = re.sub(r"\s+", " ", str(value)).strip().lower()
    if text in EXPLICIT_ZERO_BREAK_WORDS:
        return "0", None
    m = re.fullmatch(r"(\d+)(?:\s*(?:m|min|mins|minute|minutes))?", text)
    if m:
        return str(int(m.group(1))), None
    return None, f"unparseable break_minutes {str(value)!r}; left blank for worker review"


def _normalise_hourly_rate(value: Any) -> tuple[str | None, str | None]:
    """Parse explicit numeric hourly rate without inventing missing rates."""
    if _is_empty_marker(value):
        return None, None
    if isinstance(value, bool):
        return None, "hourly_rate is boolean; left blank for worker review"
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None, f"non-finite hourly_rate {value!r}; left blank for worker review"
        dec = Decimal(str(value))
        if dec < 0:
            return None, f"negative hourly_rate {value!r}; left blank for worker review"
        return f"{dec:.2f}", None

    raw_text = re.sub(r"\s+", " ", str(value)).strip()
    stripped = re.sub(
        r"(?:/\s*h|/\s*hr|\s+per\s+hour)$", "", raw_text, flags=re.IGNORECASE
    ).strip()
    m = re.fullmatch(r"[^\d.\-]*(\d+(?:\.\d+)?)\s*(?:[A-Z]{3})?", stripped)
    if not m:
        return None, f"unparseable hourly_rate {str(value)!r}; left blank for worker review"
    try:
        dec = Decimal(m.group(1))
    except InvalidOperation:
        return None, f"invalid decimal hourly_rate {str(value)!r}; left blank for worker review"
    if dec < 0:
        return None, f"negative hourly_rate {str(value)!r}; left blank for worker review"
    return f"{dec:.2f}", None


def _normalise_currency(value: Any) -> tuple[str | None, str | None]:
    """Normalise explicit 3-letter ISO currency code; never guess from missing text."""
    if _is_empty_marker(value):
        return None, None
    if isinstance(value, bool):
        return None, "currency is boolean; left blank for worker review"
    text = re.sub(r"\s+", "", str(value)).upper()
    if _ISO_CURRENCY_RE.fullmatch(text):
        return text, None
    return None, f"unrecognised currency {str(value)!r}; left blank for worker review"


def _normalise_shift_status(
    value: Any,
) -> tuple[Literal["scheduled", "cancelled", "changed"], str | None]:
    if _is_empty_marker(value):
        return "scheduled", "shift_status omitted; defaulted to 'scheduled' for review"
    if isinstance(value, bool):
        return "scheduled", "shift_status is boolean; defaulted to 'scheduled' for review"
    text = re.sub(r"\s+", " ", str(value)).strip().lower()
    if text in VALID_SHIFT_STATUSES:
        return text, None  # type: ignore[return-value]
    if "cancel" in text:
        return "cancelled", None
    if "chang" in text or "modif" in text or "updat" in text:
        return "changed", None
    return "scheduled", f"unrecognised shift_status {str(value)!r}; marked for review"


def _strip_reasoning_and_fences(raw_text: str) -> str:
    """Remove <think> traces cleanly (never mine inside them) and unwrap markdown fences."""
    cleaned = _THINK_BLOCK_RE.sub("", raw_text)
    cleaned = _UNCLOSED_THINK_TAIL_RE.sub("", cleaned).strip()
    fences = _CODE_FENCE_RE.findall(cleaned)
    if fences:
        return fences[-1].strip()
    if cleaned.startswith("```"):
        cleaned = _OPEN_CODE_FENCE_RE.sub("", cleaned).strip()
    return cleaned


def _decode_json_payload(raw_text: str) -> Any:
    candidate = _strip_reasoning_and_fences(raw_text)
    if not candidate:
        raise ValueError("Empty response content after removing reasoning tags")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        first_obj = candidate.find("{")
        first_arr = candidate.find("[")
        starts = [idx for idx in (first_obj, first_arr) if idx != -1]
        if not starts:
            raise ValueError("No JSON object or array found in model response") from None
        start_idx = min(starts)
        try:
            return json.loads(candidate[start_idx:])
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc


def _extract_raw_worker_name(raw_shift: dict[str, Any]) -> str | None:
    for key in ("worker_name", "employee_name", "employee", "staff_name"):
        cleaned = _clean_text(raw_shift.get(key))
        if cleaned is not None:
            return cleaned
    return None


def _classify_worker_attribution(
    candidate_worker: str | None,
    target_worker: str | None,
    raw_uncertain: list[str],
) -> Literal[
    "not_applicable",
    "verified_target_worker",
    "ambiguous_or_unverified",
    "other_worker",
]:
    if not target_worker:
        return "not_applicable"

    if candidate_worker is None:
        return "ambiguous_or_unverified"

    norm_cand = re.sub(r"\s+", " ", candidate_worker).strip().casefold()
    norm_target = re.sub(r"\s+", " ", target_worker).strip().casefold()
    worker_marked_uncertain = any(
        u in ("worker_name", "employee_name", "employee", "staff_name")
        for u in raw_uncertain
    )
    if norm_cand == norm_target and not worker_marked_uncertain:
        return "verified_target_worker"

    cand_tokens = {tok for tok in re.split(r"[\s,.-]+", norm_cand) if len(tok) >= 2}
    target_tokens = {tok for tok in re.split(r"[\s,.-]+", norm_target) if len(tok) >= 2}
    if cand_tokens & target_tokens:
        # Partial token overlap (e.g., "Maria" vs "Maria Santos", or initial "M. Santos") is ambiguous.
        return "ambiguous_or_unverified"

    return "other_worker"


def _recover_complete_shifts_from_truncated_content(
    raw_text: str,
    *,
    finish_reason: str | None,
) -> tuple[bool, list[tuple[str | None, int | None, list[dict[str, Any]]]], int]:
    """
    Attempt safe partial recovery from truncated final response content ONLY.

    Never reads reasoning_text. Supports both `{ "week_of": ..., "shifts": [...] }` and
    list-wrapped `[{ "week_of": ..., "shifts": [...] }, ...]` payloads, recovering only
    syntactically closed dict items inside each 'shifts' array when truncation evidence exists.
    Returns (truncation_detected, recovered_segments, trailing_incomplete_count).
    """
    candidate = _strip_reasoning_and_fences(raw_text)
    if not candidate:
        return finish_reason in TRUNCATION_FINISH_REASONS, [], 0

    arr_matches = list(_SHIFTS_ARRAY_START_RE.finditer(candidate))
    if not arr_matches:
        return finish_reason in TRUNCATION_FINISH_REASONS, [], 0

    truncation_evidence = bool(
        finish_reason in TRUNCATION_FINISH_REASONS
        or not candidate.rstrip().endswith(("}", "]"))
    )
    if not truncation_evidence:
        return False, [], 0

    decoder = json.JSONDecoder()
    segments: list[tuple[str | None, int | None, list[dict[str, Any]]]] = []
    incomplete_tail = 0
    search_start = 0

    for arr_match in arr_matches:
        if arr_match.start() < search_start:
            continue
        header_slice = candidate[search_start : arr_match.start()]
        week_of: str | None = None
        wk_matches = list(_WEEK_OF_KEY_RE.finditer(header_slice))
        if wk_matches:
            try:
                wk_val, _ = decoder.raw_decode(header_slice, wk_matches[-1].end())
                week_of = _clean_text(wk_val)
            except json.JSONDecodeError:
                week_of = None

        env_page: int | None = None
        sp_matches = list(re.finditer(r'"source_page"\s*:\s*', header_slice))
        if sp_matches:
            try:
                sp_val, _ = decoder.raw_decode(header_slice, sp_matches[-1].end())
                env_page = _parse_positive_int(sp_val)
            except json.JSONDecodeError:
                env_page = None

        recovered: list[dict[str, Any]] = []
        idx = arr_match.end()
        length = len(candidate)

        while idx < length:
            while idx < length and candidate[idx] in " \t\r\n,":
                idx += 1
            if idx >= length:
                break
            ch = candidate[idx]
            if ch == "]":
                idx += 1
                break
            if ch != "{":
                incomplete_tail += 1
                break
            try:
                obj, next_idx = decoder.raw_decode(candidate, idx)
            except json.JSONDecodeError:
                incomplete_tail += 1
                break
            if isinstance(obj, dict):
                recovered.append(obj)
            else:
                incomplete_tail += 1
                break
            idx = next_idx

        search_start = idx
        if recovered:
            segments.append((week_of, env_page, recovered))

    return True, segments, incomplete_tail


def normalise_extracted_shift(
    raw_shift: dict[str, Any],
    reference_year: int | None = None,
    *,
    worker_attribution_status: Literal[
        "not_applicable",
        "verified_target_worker",
        "ambiguous_or_unverified",
    ] = "not_applicable",
    partially_recovered: bool = False,
) -> ExtractedShiftRecord:
    """Normalise one raw extracted shift dictionary and apply strict MVP AI review safeguards."""
    raw_copy = dict(raw_shift)
    uncertain: list[str] = []
    warnings: list[str] = []
    review_reasons: list[str] = ["ai_extracted_requires_individual_confirmation"]

    raw_conf = str(raw_shift.get("confidence", "medium")).strip().lower()
    confidence: Literal["high", "medium", "low"] = (
        raw_conf if raw_conf in ALLOWED_CONFIDENCES else "medium"  # type: ignore[assignment]
    )
    if partially_recovered:
        confidence = "low"
        review_reasons.append("partial_json_recovery")
        warnings.append(
            "Recovered from a truncated response; verify against the original schedule."
        )

    declared_uncertain = raw_shift.get("uncertain_fields")
    raw_uncertain_all: list[str] = []
    if isinstance(declared_uncertain, list):
        for field_name in declared_uncertain:
            if isinstance(field_name, str):
                raw_uncertain_all.append(field_name)
                if field_name in EXTRACTION_FIELDS:
                    uncertain.append(field_name)

    shift_date, w = _normalise_date(raw_shift.get("shift_date"), reference_year)
    if w:
        warnings.append(w)
        if shift_date is None:
            uncertain.append("shift_date")

    start_time, w = _normalise_time(raw_shift.get("start_time"))
    if w:
        warnings.append(w)
        uncertain.append("start_time")

    end_time, w = _normalise_time(raw_shift.get("end_time"))
    if w:
        warnings.append(w)
        uncertain.append("end_time")

    break_minutes, w = _normalise_break_minutes(raw_shift.get("break_minutes"))
    if w:
        warnings.append(w)
        uncertain.append("break_minutes")

    employer_name = _clean_text(raw_shift.get("employer_name"))
    location = _clean_text(raw_shift.get("location"))
    department = _clean_text(raw_shift.get("department"))

    hourly_rate, w = _normalise_hourly_rate(raw_shift.get("hourly_rate"))
    if w:
        warnings.append(w)
        uncertain.append("hourly_rate")

    currency, w = _normalise_currency(raw_shift.get("currency"))
    if w:
        warnings.append(w)
        uncertain.append("currency")

    shift_status, w = _normalise_shift_status(raw_shift.get("shift_status"))
    if w:
        warnings.append(w)

    if confidence != "high" or uncertain:
        review_reasons.append("low_or_medium_confidence")

    normalised = SharedShiftSchema(
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
        break_minutes=break_minutes,
        employer_name=employer_name,
        location=location,
        department=department,
        hourly_rate=hourly_rate,
        currency=currency,
        shift_status=shift_status,
    )

    normalised_dict = normalised.model_dump()
    missing_money_fields = [f for f in MONEY_FIELDS if normalised_dict.get(f) is None]
    if missing_money_fields:
        warnings.append(
            "Missing or unreadable earnings-critical field(s): "
            + ", ".join(missing_money_fields)
        )
        for mf in missing_money_fields:
            review_reasons.append(f"missing_money_field:{mf}")

    if employer_name is None:
        warnings.append("Missing employer_name; verify which employer issued this shift.")
        review_reasons.append("missing_employer")

    if location is None:
        warnings.append("Missing location; commute feasibility cannot be assessed.")
        review_reasons.append("missing_location")

    if shift_status == "cancelled":
        review_reasons.append("cancelled_shift")
    elif shift_status == "changed":
        review_reasons.append("changed_shift")

    if worker_attribution_status == "ambiguous_or_unverified":
        confidence = "low"
        warnings.append(
            "Ambiguous or unverified worker attribution on multi-employee roster; verify employee identity."
        )
        review_reasons.append("ambiguous_worker_attribution")

    dedup_uncertain = list(dict.fromkeys(uncertain))
    dedup_warnings = list(dict.fromkeys(warnings))
    dedup_reasons = list(dict.fromkeys(review_reasons))

    # MVP AI safeguard: ALL AI-extracted shifts require individual worker review & confirmation.
    return ExtractedShiftRecord(
        raw_values=raw_copy,
        normalised=normalised,
        worker_corrected_values=None,
        source_page=_parse_positive_int(raw_shift.get("source_page")),
        source_row=_parse_positive_int(raw_shift.get("source_row")),
        worker_name=_extract_raw_worker_name(raw_shift),
        worker_attribution_status=worker_attribution_status,
        confidence=confidence,
        uncertain_fields=dedup_uncertain,
        validation_warnings=dedup_warnings,
        review_reasons=dedup_reasons,
        partially_recovered=partially_recovered,
        confirmation_status="needs_review",
        requires_worker_confirmation=True,
        requires_individual_review=True,
        eligible_for_bulk_confirmation=False,
    )


def _canonical_dedup_key(rec: ExtractedShiftRecord) -> tuple[Any, ...]:
    n = rec.normalised
    return (
        n.shift_date,
        n.start_time,
        n.end_time,
        n.break_minutes,
        (n.employer_name or "").strip().casefold() or None,
        (n.location or "").strip().casefold() or None,
        (n.department or "").strip().casefold() or None,
        n.hourly_rate,
        n.currency,
        n.shift_status,
        (rec.worker_name or "").strip().casefold() or None,
    )


def _records_conflict(a: ExtractedShiftRecord, b: ExtractedShiftRecord) -> bool:
    """
    Determine whether two non-identical shift records represent conflicting duplicates
    for the same worker and shift slot rather than legitimate simultaneous multi-employer shifts.
    """
    na, nb = a.normalised, b.normalised
    if na.shift_date is None or na.start_time is None or na.end_time is None:
        return False
    if (na.shift_date, na.start_time, na.end_time) != (
        nb.shift_date,
        nb.start_time,
        nb.end_time,
    ):
        return False

    worker_a = (a.worker_name or "").strip().casefold()
    worker_b = (b.worker_name or "").strip().casefold()
    if worker_a != worker_b:
        return False

    emp_a = (na.employer_name or "").strip().casefold()
    emp_b = (nb.employer_name or "").strip().casefold()
    if emp_a and emp_b and emp_a != emp_b:
        return False

    return True


def _annotate_conflicting_duplicates(
    records: list[ExtractedShiftRecord],
) -> tuple[list[ExtractedShiftRecord], list[dict[str, Any]]]:
    """Group conflicting duplicate records without silently merging or selecting one."""
    n = len(records)
    if n < 2:
        return records, []

    adj: dict[int, set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if _records_conflict(records[i], records[j]):
                adj[i].add(j)
                adj[j].add(i)

    visited: set[int] = set()
    components: list[list[int]] = []
    for start in range(n):
        if start in visited or not adj[start]:
            continue
        stack = [start]
        comp: list[int] = []
        visited.add(start)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in adj[cur]:
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
        comp.sort()
        if len(comp) >= 2:
            components.append(comp)

    if not components:
        return records, []

    updated = list(records)
    conflict_groups: list[dict[str, Any]] = []
    group_counter = 0

    for member_indices in components:
        diff_fields = [
            f
            for f in EXTRACTION_FIELDS
            if len({getattr(records[m].normalised, f) for m in member_indices}) > 1
        ]
        if not diff_fields:
            continue
        group_counter += 1
        cg_id = f"conflict_group_{group_counter}"
        rows_label = [records[m].source_row for m in member_indices]
        warning_msg = (
            f"Conflicting duplicate shift in {cg_id} (rows {rows_label}): "
            f"differing values for {', '.join(diff_fields)}. Explicit worker resolution required."
        )
        for m in member_indices:
            rec = updated[m]
            updated[m] = rec.model_copy(
                update={
                    "conflict_group_id": cg_id,
                    "conflicting_fields": diff_fields,
                    "requires_conflict_resolution": True,
                    "conflict_resolved": False,
                    "uncertain_fields": list(
                        dict.fromkeys([*rec.uncertain_fields, *diff_fields])
                    ),
                    "validation_warnings": list(
                        dict.fromkeys([*rec.validation_warnings, warning_msg])
                    ),
                    "review_reasons": list(
                        dict.fromkeys(
                            [
                                *rec.review_reasons,
                                "conflicting_duplicate",
                                *(f"conflicting_field:{f}" for f in diff_fields),
                            ]
                        )
                    ),
                }
            )
        first_norm = records[member_indices[0]].normalised
        conflict_groups.append(
            {
                "conflict_group_id": cg_id,
                "shift_date": first_norm.shift_date,
                "start_time": first_norm.start_time,
                "end_time": first_norm.end_time,
                "employer_name": next(
                    (
                        records[m].normalised.employer_name
                        for m in member_indices
                        if records[m].normalised.employer_name
                    ),
                    None,
                ),
                "member_indices": member_indices,
                "source_pages": [records[m].source_page for m in member_indices],
                "source_rows": rows_label,
                "conflicting_fields": diff_fields,
            }
        )

    return updated, conflict_groups


def _validate_semantic_shift(
    raw_item: dict[str, Any],
    record: ExtractedShiftRecord,
) -> str | None:
    """Reject semantically empty records or misplaced envelope objects before emitting."""
    if "shifts" in raw_item:
        return "Rejected misplaced document envelope containing 'shifts' key inside shift list"

    norm = record.normalised
    data_fields = (
        norm.shift_date,
        norm.start_time,
        norm.end_time,
        norm.break_minutes,
        norm.employer_name,
        norm.location,
        norm.department,
        norm.hourly_rate,
        norm.currency,
    )
    if all(v is None for v in data_fields):
        return "Rejected semantically empty shift record (no schedule fields extracted)"

    temporal_fields = (norm.shift_date, norm.start_time, norm.end_time)
    if all(v is None for v in temporal_fields):
        return (
            "Rejected semantically invalid shift record "
            "(missing shift_date, start_time, and end_time)"
        )
    return None


def _extract_envelope_segments(
    payload: Any,
) -> tuple[list[tuple[str | None, int | None, list[dict[str, Any]]]], list[str]]:
    """
    Normalise top-level JSON structures into validated (week_of, source_page, shift_dicts) segments.

    Supports:
    - Single document envelope: {"week_of": ..., "shifts": [...]}
    - Single-element list wrapping an envelope: [{"week_of": ..., "shifts": [...]}]
    - Multiple document envelopes: [{"week_of": ..., "shifts": [...]}, ...]
    - Flat list of shift objects: [{"shift_date": ..., "start_time": ...}, ...]
    """
    if isinstance(payload, dict):
        if "shifts" not in payload:
            return [], ["JSON object must contain a 'shifts' list"]
        raw_shifts = payload["shifts"]
        if not isinstance(raw_shifts, list):
            return [], ["'shifts' field must be a JSON array"]
        bad = [
            f"shifts[{idx}] is not an object ({type(item).__name__})"
            for idx, item in enumerate(raw_shifts)
            if not isinstance(item, dict)
        ]
        if bad:
            return [], bad
        wk = _clean_text(payload.get("week_of"))
        sp = _parse_positive_int(payload.get("source_page"))
        return [(wk, sp, list(raw_shifts))], []

    if isinstance(payload, list):
        if not payload:
            return [(None, None, [])], []

        non_dict_errs = [
            f"Top-level array[{idx}] is not an object ({type(item).__name__})"
            for idx, item in enumerate(payload)
            if not isinstance(item, dict)
        ]
        if non_dict_errs:
            return [], non_dict_errs

        has_shifts = ["shifts" in item for item in payload]
        if any(has_shifts) and not all(has_shifts):
            return [], [
                "Ambiguous mixed top-level array combining document envelopes and bare objects"
            ]

        if all(has_shifts):
            segments: list[tuple[str | None, int | None, list[dict[str, Any]]]] = []
            errs: list[str] = []
            for env_idx, env in enumerate(payload):
                raw_shifts = env.get("shifts")
                if not isinstance(raw_shifts, list):
                    errs.append(f"envelope[{env_idx}].shifts must be a JSON array")
                    continue
                inner_bad = [
                    f"envelope[{env_idx}].shifts[{idx}] is not an object ({type(item).__name__})"
                    for idx, item in enumerate(raw_shifts)
                    if not isinstance(item, dict)
                ]
                if inner_bad:
                    errs.extend(inner_bad)
                    continue
                wk = _clean_text(env.get("week_of"))
                sp = _parse_positive_int(env.get("source_page"))
                segments.append((wk, sp, list(raw_shifts)))
            return ([] if errs else segments), errs

        # Flat list of shift objects without envelope wrapper
        return [(None, None, list(payload))], []

    return [], [
        f"Expected top-level JSON object or list, got {type(payload).__name__}"
    ]


def _normalise_segments(
    segments: list[tuple[str | None, int | None, list[dict[str, Any]]]],
    *,
    target_worker: str | None,
    partially_recovered: bool,
) -> tuple[
    str | None,
    list[ExtractedShiftRecord],
    int,
    int,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    """Normalise envelope segments independently while preserving per-envelope week & page context."""
    records: list[ExtractedShiftRecord] = []
    seen_by_key: dict[tuple[Any, ...], int] = {}
    filtered_other_worker = 0
    deduplicated = 0
    deduplicated_records: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    errors: list[str] = []
    week_labels: list[str] = []

    for env_idx, (seg_week_of, env_source_page, raw_items) in enumerate(segments):
        if seg_week_of and seg_week_of not in week_labels:
            week_labels.append(seg_week_of)
        ref_year = _extract_reference_year(seg_week_of, raw_items)

        for idx, orig_item in enumerate(raw_items):
            item = dict(orig_item)
            if env_source_page is not None and _parse_positive_int(item.get("source_page")) is None:
                item["source_page"] = env_source_page

            if "shifts" in item:
                reason = (
                    f"envelope[{env_idx}].shifts[{idx}]: "
                    "Rejected misplaced document envelope containing 'shifts' key inside shift list"
                )
                errors.append(reason)
                rejected_records.append(
                    {"envelope_index": env_idx, "raw_values": orig_item, "reason": reason}
                )
                continue

            declared_unc = item.get("uncertain_fields")
            raw_unc_list = (
                [u for u in declared_unc if isinstance(u, str)]
                if isinstance(declared_unc, list)
                else []
            )
            candidate_worker = _extract_raw_worker_name(item)
            attribution = _classify_worker_attribution(
                candidate_worker, target_worker, raw_unc_list
            )
            if attribution == "other_worker":
                filtered_other_worker += 1
                continue

            try:
                rec = normalise_extracted_shift(
                    item,
                    reference_year=ref_year,
                    worker_attribution_status=attribution,
                    partially_recovered=partially_recovered,
                )
            except ValidationError as exc:
                reason = f"envelope[{env_idx}].shifts[{idx}] failed schema validation: {exc}"
                errors.append(reason)
                rejected_records.append(
                    {"envelope_index": env_idx, "raw_values": orig_item, "reason": reason}
                )
                continue

            sem_err = _validate_semantic_shift(orig_item, rec)
            if sem_err is not None:
                reason = f"envelope[{env_idx}].shifts[{idx}]: {sem_err}"
                errors.append(reason)
                rejected_records.append(
                    {"envelope_index": env_idx, "raw_values": orig_item, "reason": reason}
                )
                continue

            dedup_key = _canonical_dedup_key(rec)
            if dedup_key in seen_by_key:
                deduplicated += 1
                kept_idx = seen_by_key[dedup_key]
                kept = records[kept_idx]
                prov = {
                    "source_page": rec.source_page,
                    "source_row": rec.source_row,
                    "raw_values": dict(orig_item),
                }
                records[kept_idx] = kept.model_copy(
                    update={
                        "deduplicated_provenance": [*kept.deduplicated_provenance, prov],
                        "review_reasons": list(
                            dict.fromkeys(
                                [*kept.review_reasons, "exact_duplicate_deduplicated"]
                            )
                        ),
                    }
                )
                deduplicated_records.append(
                    {
                        "kept_index": kept_idx,
                        "kept_source_page": kept.source_page,
                        "kept_source_row": kept.source_row,
                        "duplicate_source_page": rec.source_page,
                        "duplicate_source_row": rec.source_row,
                        "raw_values": dict(orig_item),
                    }
                )
                continue

            seen_by_key[dedup_key] = len(records)
            records.append(rec)

    records, conflict_groups = _annotate_conflicting_duplicates(records)
    if rejected_records and records:
        rejected_warn = (
            "Document contained rejected invalid/empty shift record(s); "
            "verify that no shifts from the source schedule are missing."
        )
        records = [
            rec.model_copy(
                update={
                    "confidence": "low",
                    "review_reasons": list(
                        dict.fromkeys(
                            [
                                *rec.review_reasons,
                                "partial_extraction_with_rejected_records",
                                "low_or_medium_confidence",
                            ]
                        )
                    ),
                    "validation_warnings": list(
                        dict.fromkeys([*rec.validation_warnings, rejected_warn])
                    ),
                }
            )
            for rec in records
        ]
    combined_week_of = " | ".join(week_labels) if week_labels else None
    return (
        combined_week_of,
        records,
        filtered_other_worker,
        deduplicated,
        deduplicated_records,
        conflict_groups,
        rejected_records,
        errors,
    )


def parse_and_validate_model_json(
    raw_text: str,
    *,
    file_name: str,
    model_id: str,
    target_worker: str | None = None,
    finish_reason: str | None = None,
    allow_partial_recovery: bool = True,
) -> DocumentExtractionResult:
    """Parse raw model content into DocumentExtractionResult with semantic checks and safe truncation recovery."""
    try:
        payload = _decode_json_payload(raw_text)
    except Exception as exc:
        if allow_partial_recovery:
            (
                trunc_detected,
                recovered_segments,
                incomplete_tail,
            ) = _recover_complete_shifts_from_truncated_content(
                raw_text, finish_reason=finish_reason
            )
            if trunc_detected and recovered_segments:
                (
                    wk_of,
                    records,
                    filtered,
                    dedup,
                    dedup_records,
                    conflict_groups,
                    rejected_records,
                    item_errs,
                ) = _normalise_segments(
                    recovered_segments,
                    target_worker=target_worker,
                    partially_recovered=True,
                )
                conflicting_count = sum(
                    len(g["member_indices"]) for g in conflict_groups
                )
                recovery_errors = [
                    (
                        f"Incomplete extraction (truncated response): recovered {len(records)} "
                        f"complete shift(s) from partial JSON"
                        + (
                            f" and discarded {incomplete_tail} incomplete trailing shift object."
                            if incomplete_tail
                            else "."
                        )
                    ),
                    f"Original JSON error: {exc}",
                    *item_errs,
                ]
                return DocumentExtractionResult(
                    file_name=file_name,
                    model_id=model_id,
                    week_of=wk_of,
                    target_worker=target_worker,
                    shifts=records,
                    filtered_other_worker_shifts=filtered,
                    deduplicated_shifts=dedup,
                    deduplicated_records=dedup_records,
                    conflicting_duplicate_count=conflicting_count,
                    conflict_groups=conflict_groups,
                    invalid_or_empty_records=len(rejected_records),
                    rejected_records=rejected_records,
                    partially_recovered_shift_count=len(records),
                    incomplete_extraction=True,
                    partial_recovery_triggered=True,
                    json_validation_failure=True,
                    json_validation_errors=recovery_errors,
                )

        trunc_suffix = (
            f" (finish_reason={finish_reason})"
            if finish_reason in TRUNCATION_FINISH_REASONS
            else ""
        )
        return DocumentExtractionResult(
            file_name=file_name,
            model_id=model_id,
            target_worker=target_worker,
            incomplete_extraction=finish_reason in TRUNCATION_FINISH_REASONS,
            json_validation_failure=True,
            json_validation_errors=[f"Malformed JSON output{trunc_suffix}: {exc}"],
        )

    segments, structural_errors = _extract_envelope_segments(payload)
    if structural_errors:
        return DocumentExtractionResult(
            file_name=file_name,
            model_id=model_id,
            week_of=_clean_text(payload.get("week_of")) if isinstance(payload, dict) else None,
            target_worker=target_worker,
            json_validation_failure=True,
            json_validation_errors=structural_errors,
        )

    (
        week_of,
        records,
        filtered_other_worker,
        deduplicated,
        deduplicated_records,
        conflict_groups,
        rejected_records,
        item_errors,
    ) = _normalise_segments(
        segments,
        target_worker=target_worker,
        partially_recovered=False,
    )

    truncated_envelope = finish_reason in TRUNCATION_FINISH_REASONS
    if truncated_envelope:
        item_errors.append(
            f"Response reached finish_reason={finish_reason!r}; treat extraction as incomplete."
        )

    has_incomplete = truncated_envelope or (bool(rejected_records) and bool(records))
    conflicting_count = sum(len(g["member_indices"]) for g in conflict_groups)

    return DocumentExtractionResult(
        file_name=file_name,
        model_id=model_id,
        week_of=week_of,
        target_worker=target_worker,
        shifts=records,
        filtered_other_worker_shifts=filtered_other_worker,
        deduplicated_shifts=deduplicated,
        deduplicated_records=deduplicated_records,
        conflicting_duplicate_count=conflicting_count,
        conflict_groups=conflict_groups,
        invalid_or_empty_records=len(rejected_records),
        rejected_records=rejected_records,
        partially_recovered_shift_count=0,
        incomplete_extraction=has_incomplete,
        partial_recovery_triggered=False,
        json_validation_failure=bool(item_errors),
        json_validation_errors=item_errors,
    )
