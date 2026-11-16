import type { EditableShiftValues, FieldDiff } from '../types/shift'

const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  ZMW: 'ZMW ',
}

const FIELD_LABELS: Array<{ key: keyof EditableShiftValues; label: string }> = [
  { key: 'shift_date', label: 'Shift date' },
  { key: 'end_date', label: 'End date' },
  { key: 'start_time', label: 'Start time' },
  { key: 'end_time', label: 'End time' },
  { key: 'break_minutes', label: 'Unpaid break (min)' },
  { key: 'employer_name', label: 'Employer' },
  { key: 'location', label: 'Location' },
  { key: 'department', label: 'Department' },
  { key: 'hourly_rate', label: 'Hourly rate' },
  { key: 'currency', label: 'Currency' },
  { key: 'shift_status', label: 'Shift status' },
]

/**
 * Display-only currency formatter. Never computes earnings.
 * Displays "Not counted yet" whenever the backend returns null gross earnings.
 */
export function formatCurrency(
  amount: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount === null || amount === undefined) {
    return 'Not counted yet'
  }
  const code = (currency ?? '').trim().toUpperCase()
  const formatted = amount.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  if (!code) {
    return formatted
  }
  const symbol = CURRENCY_SYMBOLS[code]
  if (symbol) {
    return `${symbol}${formatted}`
  }
  return `${code} ${formatted}`
}

export function formatCurrencyWithCode(
  amount: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount === null || amount === undefined) {
    return 'Not counted yet'
  }
  const code = (currency ?? '').trim().toUpperCase()
  const base = formatCurrency(amount, currency)
  if (!code) return base
  if (base.startsWith(code)) return base
  return `${base} (${code})`
}

export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) {
    return '—'
  }
  const fixed = Number(hours.toFixed(2))
  return `${fixed} hrs`
}

function parseIsoDateUtc(isoDate: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(isoDate.trim())) {
    return null
  }
  const [y, m, d] = isoDate.trim().split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  if (
    dt.getUTCFullYear() !== y ||
    dt.getUTCMonth() !== m - 1 ||
    dt.getUTCDate() !== d
  ) {
    return null
  }
  return dt
}

export function formatDateDisplay(isoDate: string | null | undefined): string {
  if (!isoDate) return 'Missing date'
  const dt = parseIsoDateUtc(isoDate)
  if (!dt) return isoDate
  return dt.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

export function formatShortDay(isoDate: string): {
  weekday: string
  dayMonth: string
} {
  const dt = parseIsoDateUtc(isoDate)
  if (!dt) {
    return { weekday: isoDate, dayMonth: '' }
  }
  return {
    weekday: dt.toLocaleDateString('en-US', {
      weekday: 'long',
      timeZone: 'UTC',
    }),
    dayMonth: dt.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    }),
  }
}

export function formatWeekRange(weekStartIso: string): string {
  const start = parseIsoDateUtc(weekStartIso)
  if (!start) return weekStartIso
  const end = new Date(start.getTime() + 6 * 24 * 60 * 60 * 1000)
  const startLabel = start.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
  const endLabel = end.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  })
  return `${startLabel} – ${endLabel}`
}

export function getWeekDates(weekStartIso: string): string[] {
  const start = parseIsoDateUtc(weekStartIso)
  if (!start) return []
  const dates: string[] = []
  for (let i = 0; i < 7; i += 1) {
    const dt = new Date(start.getTime() + i * 24 * 60 * 60 * 1000)
    dates.push(dt.toISOString().slice(0, 10))
  }
  return dates
}

export function isOvernightShift(
  startTime: string,
  endTime: string,
  shiftDate: string,
  endDate?: string,
): boolean {
  if (endDate && shiftDate && endDate.trim() > shiftDate.trim()) {
    return true
  }
  const timeRe = /^([01]\d|2[0-3]):([0-5]\d)$/
  if (timeRe.test(startTime.trim()) && timeRe.test(endTime.trim())) {
    return endTime.trim() < startTime.trim()
  }
  return false
}

export function getChangedFields(
  extracted: EditableShiftValues,
  current: EditableShiftValues,
): FieldDiff[] {
  const diffs: FieldDiff[] = []
  for (const { key, label } of FIELD_LABELS) {
    const orig = (extracted[key] ?? '').trim()
    const curr = (current[key] ?? '').trim()
    if (orig !== curr) {
      diffs.push({
        field: key,
        label,
        originalValue: orig || '(empty)',
        currentValue: curr || '(empty)',
      })
    }
  }
  return diffs
}

const FRIENDLY_FLAG_LABELS: Record<string, string> = {
  MISSING_DATE: 'Date needed',
  INVALID_TIME: 'Check start or end time',
  INVALID_END_DATE: 'Check end date',
  INVALID_DURATION: 'Shift length invalid (max 16 hrs)',
  INVALID_BREAK: 'Break length invalid',
  MISSING_BREAK: 'Break not confirmed',
  MISSING_RATE: 'Hourly rate needed',
  MISSING_CURRENCY: 'Currency needed',
  MISSING_EMPLOYER: 'Employer not listed',
  MISSING_LOCATION: 'Location not listed',
  UNKNOWN_LOCATION: 'Unrecognized location',
  POSSIBLE_DUPLICATE: 'Possible duplicate shift',
  CANCELLED: 'Cancelled shift',
  UNCONFIRMED: 'Waiting for confirmation',
  NEEDS_REVIEW: 'Needs review',
  LOW_CONFIDENCE: 'Please double-check details',
  OVERLAP: 'Overlaps another shift',
  COMMUTE_GAP: 'Short travel gap (< 30 min)',
}

export function getFriendlyFlagLabel(code: string): string {
  return (
    FRIENDLY_FLAG_LABELS[code] ??
    code
      .toLowerCase()
      .replace(/_/g, ' ')
      .replace(/^\w/, (c) => c.toUpperCase())
  )
}

