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

let scheduleBatchSeq = 0

interface StrictCsvLineResult {
  cells: string[]
  error?: string
}

/**
 * Parse a single CSV line strictly according to RFC-4180.
 * Detects unclosed quotes, stray unescaped quotes inside unquoted fields,
 * and unexpected trailing characters after closing quotes.
 */
export function parseCsvLineStrict(
  line: string,
  rowLabel = 'row',
): StrictCsvLineResult {
  const cells: string[] = []
  let current = ''
  let inQuotes = false
  let atFieldStart = true
  let justClosedQuote = false

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]

    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') {
          current += '"'
          i += 1
        } else {
          inQuotes = false
          justClosedQuote = true
        }
      } else {
        current += ch
      }
      continue
    }

    if (justClosedQuote) {
      if (ch === ',') {
        cells.push(current)
        current = ''
        atFieldStart = true
        justClosedQuote = false
      } else {
        return {
          cells,
          error: `Malformed CSV quote in ${rowLabel}: unexpected character "${ch}" after closing quote.`,
        }
      }
      continue
    }

    if (ch === '"') {
      if (!atFieldStart) {
        return {
          cells,
          error: `Malformed CSV quote in ${rowLabel}: unexpected quotation mark inside unquoted field.`,
        }
      }
      inQuotes = true
      atFieldStart = false
    } else if (ch === ',') {
      cells.push(current)
      current = ''
      atFieldStart = true
    } else {
      current += ch
      atFieldStart = false
    }
  }

  if (inQuotes) {
    return {
      cells,
      error: `Malformed CSV quote in ${rowLabel}: unclosed quotation mark.`,
    }
  }

  cells.push(current)
  return { cells }
}

/**
 * Convenience parser for well-formed CSV lines (used by fixtures/tests).
 */
export function parseCsvLine(line: string): string[] {
  return parseCsvLineStrict(line).cells
}

function splitCsvLinesStrict(rawText: string): {
  lines: string[]
  error?: string
} {
  const cleaned = rawText.replace(/^\uFEFF/, '')
  const lines: string[] = []
  let current = ''
  let inQuotes = false
  let atFieldStart = true
  let justClosedQuote = false

  for (let i = 0; i < cleaned.length; i += 1) {
    const ch = cleaned[i]
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < cleaned.length && cleaned[i + 1] === '"') {
          current += '""'
          i += 1
        } else {
          inQuotes = false
          justClosedQuote = true
          current += ch
        }
      } else {
        current += ch
      }
      continue
    }

    if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && i + 1 < cleaned.length && cleaned[i + 1] === '\n') {
        i += 1
      }
      if (current.trim().length > 0) {
        lines.push(current)
      }
      current = ''
      atFieldStart = true
      justClosedQuote = false
      continue
    }

    if (justClosedQuote) {
      if (ch === ',') {
        atFieldStart = true
        justClosedQuote = false
      } else {
        return {
          lines,
          error: `Malformed CSV quote on line ${lines.length + 1}: unexpected character "${ch}" after closing quote.`,
        }
      }
      current += ch
      continue
    }

    if (ch === '"') {
      if (!atFieldStart) {
        return {
          lines,
          error: `Malformed CSV quote on line ${lines.length + 1}: unexpected quotation mark inside unquoted field.`,
        }
      }
      inQuotes = true
      atFieldStart = false
    } else if (ch === ',') {
      atFieldStart = true
    } else {
      atFieldStart = false
    }
    current += ch
  }

  if (inQuotes) {
    return {
      lines,
      error:
        'Malformed CSV file: unclosed quotation mark detected. Ensure every quoted field has a matching closing quote.',
    }
  }

  if (current.trim().length > 0) {
    lines.push(current)
  }

  return { lines }
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

function createScheduleId(
  fileName: string,
  overrideId?: string,
  existingScheduleIds?: Set<string>,
): string {
  if (overrideId && !existingScheduleIds?.has(overrideId)) {
    return overrideId
  }
  const stem = fileName
    .replace(/\.[^.]+$/, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 20)

  let candidate: string
  do {
    scheduleBatchSeq += 1
    const suffix = Math.random().toString(36).slice(2, 6).toUpperCase()
    candidate = `${stem || 'CSV'}-${scheduleBatchSeq}-${suffix}`
  } while (existingScheduleIds?.has(candidate))

  return candidate
}

export interface ParseScheduleCsvOptions {
  workerId: string
  fileName: string
  scheduleId?: string
  existingScheduleIds?: Set<string>
  initialConfirmations?: ConfirmationStatus[]
  useCsvConfirmationColumn?: boolean
}

export function parseScheduleCsv(
  rawText: string,
  options: ParseScheduleCsvOptions,
): CsvParseResult {
  const scheduleId = createScheduleId(
    options.fileName,
    options.scheduleId,
    options.existingScheduleIds,
  )
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

  const splitResult = splitCsvLinesStrict(rawText)
  if (splitResult.error) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: [splitResult.error],
      warnings,
    }
  }

  const lines = splitResult.lines
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

  const headerParse = parseCsvLineStrict(lines[0], 'header row')
  if (headerParse.error) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: [headerParse.error],
      warnings,
    }
  }

  const rawHeaders = headerParse.cells.map((h) => h.trim().toLowerCase())
  if (rawHeaders.some((h) => h === '')) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: [
        'CSV header contains an empty column name. Ensure every column has a valid header.',
      ],
      warnings,
    }
  }

  const canonicalHeaders = rawHeaders.map((h) => HEADER_ALIASES[h] ?? h)
  const seenCanonical = new Map<string, string>()
  const duplicateHeaders: string[] = []
  for (let idx = 0; idx < canonicalHeaders.length; idx += 1) {
    const canon = canonicalHeaders[idx]
    const raw = rawHeaders[idx]
    const existingRaw = seenCanonical.get(canon)
    if (existingRaw !== undefined) {
      duplicateHeaders.push(
        existingRaw === raw ? raw : `${existingRaw} & ${raw} (${canon})`,
      )
    } else {
      seenCanonical.set(canon, raw)
    }
  }

  if (duplicateHeaders.length > 0) {
    return {
      ok: false,
      scheduleId,
      fileName: options.fileName,
      shifts: [],
      errors: [
        `Duplicate or conflicting CSV header column(s): ${duplicateHeaders.join(', ')}. Each column header must appear only once.`,
      ],
      warnings,
    }
  }

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
    const parsedRow = parseCsvLineStrict(rawLine, `row ${i}`)
    if (parsedRow.error) {
      return {
        ok: false,
        scheduleId,
        fileName: options.fileName,
        shifts: [],
        errors: [parsedRow.error],
        warnings,
      }
    }

    const cells = parsedRow.cells
    if (cells.length !== canonicalHeaders.length) {
      return {
        ok: false,
        scheduleId,
        fileName: options.fileName,
        shifts: [],
        errors: [
          `Row ${i} has ${cells.length} column(s), but the header defines ${canonicalHeaders.length}. Check for unquoted commas or missing fields so shift values are not misaligned.`,
        ],
        warnings,
      }
    }

    const rowMap: Record<string, string> = {}
    for (let colIdx = 0; colIdx < canonicalHeaders.length; colIdx += 1) {
      const key = canonicalHeaders[colIdx]
      rowMap[key] = (cells[colIdx] ?? '').trim()
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
