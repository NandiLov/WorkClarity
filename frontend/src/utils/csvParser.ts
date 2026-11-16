import type {
  ConfirmationStatus,
  CsvParseResult,
  EditableShiftValues,
  ShiftRecord,
  ShiftStatus,
} from '../types/shift'

export const CSV_TEMPLATE_CONTENT = [
  'shift_date,start_time,end_time,end_date,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status,stated_hours',
  '2026-11-09,09:00,17:00,,30,BrightMart,Store A,sales floor,16.00,USD,scheduled,8.0',
  '2026-11-10,10:00,18:00,,60,BrightMart,Store A,sales floor,16.00,USD,scheduled,8.0',
  '2026-11-11,22:00,06:00,2026-11-12,0,SwiftLogistics,Warehouse B,dispatch,18.00,USD,scheduled,8.0',
].join('\n')

const HEADER_ALIASES: Record<string, string> = {
  shift_date: 'shift_date',
  date: 'shift_date',
  start_time: 'start_time',
  end_time: 'end_time',
  end_date: 'end_date',
  break_minutes: 'break_minutes',
  employer_name: 'employer_name',
  employer: 'employer_name',
  location: 'location',
  location_text: 'location',
  department: 'department',
  hourly_rate: 'hourly_rate',
  currency: 'currency',
  shift_status: 'shift_status',
  stated_hours: 'stated_hours',
  confirmation_status: 'confirmation_status',
}

/**
 * Parse a single CSV line according to RFC-4180 (handles quoted fields and escaped "" quotes).
 */
export function parseCsvLine(line: string): string[] {
  const cells: string[] = []
  let current = ''
  let inQuotes = false

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') {
          current += '"'
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        current += ch
      }
    } else if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      cells.push(current)
      current = ''
    } else {
      current += ch
    }
  }
  cells.push(current)
  return cells
}

function splitCsvLines(rawText: string): string[] {
  const cleaned = rawText.replace(/^\uFEFF/, '')
  const lines: string[] = []
  let current = ''
  let inQuotes = false

  for (let i = 0; i < cleaned.length; i += 1) {
    const ch = cleaned[i]
    if (ch === '"') {
      if (inQuotes && i + 1 < cleaned.length && cleaned[i + 1] === '"') {
        current += '""'
        i += 1
      } else {
        inQuotes = !inQuotes
        current += ch
      }
    } else if ((ch === '\n' || ch === '\r') && !inQuotes) {
      if (ch === '\r' && i + 1 < cleaned.length && cleaned[i + 1] === '\n') {
        i += 1
      }
      if (current.trim().length > 0) {
        lines.push(current)
      }
      current = ''
    } else {
      current += ch
    }
  }
  if (current.trim().length > 0) {
    lines.push(current)
  }
  return lines
}

function normalizeShiftStatus(raw: string): ShiftStatus {
  const normalized = raw.trim().toLowerCase()
  if (normalized === 'cancelled') return 'cancelled'
  if (normalized === 'changed') return 'changed'
  return 'scheduled'
}

function normalizeConfirmationStatus(raw: string): ConfirmationStatus {
  const normalized = raw.trim().toLowerCase()
  if (normalized === 'confirmed') return 'confirmed'
  if (normalized === 'needs_review') return 'needs_review'
  if (normalized === 'rejected') return 'rejected'
  return 'unconfirmed'
}

function createScheduleId(fileName: string, overrideId?: string): string {
  if (overrideId) {
    return overrideId
  }
  const stem = fileName
    .replace(/\.[^.]+$/, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 20)
  const suffix = Math.random().toString(36).slice(2, 6).toUpperCase()
  return `${stem || 'CSV'}-${suffix}`
}

export interface ParseScheduleCsvOptions {
  workerId: string
  fileName: string
  scheduleId?: string
  initialConfirmations?: ConfirmationStatus[]
  useCsvConfirmationColumn?: boolean
}

export function parseScheduleCsv(
  rawText: string,
  options: ParseScheduleCsvOptions,
): CsvParseResult {
  const scheduleId = createScheduleId(options.fileName, options.scheduleId)
  const errors: string[] = []
  const warnings: string[] = []

  if (!rawText || rawText.trim().length === 0) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: ['The uploaded CSV file is empty.'],
      warnings,
    }
  }

  if (rawText.includes('\u0000')) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: [
        'This file appears to be binary or corrupted rather than a UTF-8 CSV text file.',
      ],
      warnings,
    }
  }

  const lines = splitCsvLines(rawText)
  if (lines.length < 2) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: [
        'The CSV file must include a header row and at least one shift row.',
      ],
      warnings,
    }
  }

  const rawHeaders = parseCsvLine(lines[0]).map((h) => h.trim().toLowerCase())
  const canonicalHeaders = rawHeaders.map((h) => HEADER_ALIASES[h] ?? h)

  const requiredColumns = ['shift_date', 'start_time', 'end_time']
  const missingHeaders = requiredColumns.filter(
    (col) => !canonicalHeaders.includes(col),
  )

  if (missingHeaders.length > 0) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: [
        `Missing required CSV header column(s): ${missingHeaders.join(', ')}. Download the CSV template to see the expected format.`,
      ],
      warnings,
    }
  }

  const nowIso = new Date().toISOString()
  const shifts: ShiftRecord[] = []

  for (let i = 1; i < lines.length; i += 1) {
    const rawLine = lines[i]
    const cells = parseCsvLine(rawLine)
    const rowMap: Record<string, string> = {}

    for (let colIdx = 0; colIdx < canonicalHeaders.length; colIdx += 1) {
      const key = canonicalHeaders[colIdx]
      rowMap[key] = (cells[colIdx] ?? '').trim()
    }

    if (cells.length > canonicalHeaders.length) {
      warnings.push(
        `Row ${i} has more columns than the header; extra trailing values were ignored.`,
      )
    }

    const extracted: EditableShiftValues = {
      shift_date: rowMap.shift_date ?? '',
      start_time: rowMap.start_time ?? '',
      end_time: rowMap.end_time ?? '',
      end_date: rowMap.end_date ?? '',
      // Preserve blank strings verbatim — never guess 0 for missing breaks or rates
      break_minutes: rowMap.break_minutes ?? '',
      employer_name: rowMap.employer_name ?? '',
      location: rowMap.location ?? '',
      department: rowMap.department ?? '',
      hourly_rate: rowMap.hourly_rate ?? '',
      currency: rowMap.currency ?? '',
      shift_status: normalizeShiftStatus(rowMap.shift_status ?? ''),
      stated_hours: rowMap.stated_hours ?? '',
    }

    let confirmationStatus: ConfirmationStatus = 'unconfirmed'
    if (options.initialConfirmations && options.initialConfirmations[i - 1]) {
      confirmationStatus = options.initialConfirmations[i - 1]
    } else if (
      options.useCsvConfirmationColumn &&
      rowMap.confirmation_status
    ) {
      confirmationStatus = normalizeConfirmationStatus(
        rowMap.confirmation_status,
      )
    }

    const lineNo = i
    const shiftId = `${scheduleId}-S${String(lineNo).padStart(2, '0')}`

    shifts.push({
      shift_id: shiftId,
      worker_id: options.workerId,
      schedule_id: scheduleId,
      line_no: lineNo,
      source_line: rawLine,
      extracted: { ...extracted },
      current: { ...extracted },
      confirmation_status: confirmationStatus,
      calculated: null,
      updated_at: nowIso,
    })
  }

  return {
    ok: true,
    scheduleId,
    fileName: options.fileName,
    shifts,
    errors,
    warnings,
  }
}

export function createBlankEditableShiftValues(): EditableShiftValues {
  return {
    shift_date: '',
    start_time: '',
    end_time: '',
    end_date: '',
    break_minutes: '',
    employer_name: '',
    location: '',
    department: '',
    hourly_rate: '',
    currency: '',
    shift_status: 'scheduled',
    stated_hours: '',
  }
}
