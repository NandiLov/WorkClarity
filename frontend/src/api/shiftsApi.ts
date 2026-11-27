import type {
  HealthResponse,
  ShiftCalculationRequestPayload,
  ShiftCalculationResponse,
  ShiftExtractionResponse,
  ShiftRecord,
} from '../types/shift'

export function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL
  if (typeof configured !== 'string') {
    return ''
  }
  return configured.trim().replace(/\/+$/, '')
}

export class ApiClientError extends Error {
  readonly status?: number
  readonly isNetworkError: boolean

  constructor(message: string, status?: number, isNetworkError = false) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
    this.isNetworkError = isNetworkError
  }
}

function normalizeOptionalString(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function normalizeBreakMinutes(value: string): number | string | null {
  const trimmed = value.trim()
  if (trimmed === '') {
    return null
  }
  if (/^\d+$/.test(trimmed)) {
    return Number.parseInt(trimmed, 10)
  }
  return trimmed
}

/**
 * Convert a frontend ShiftRecord into the payload accepted by POST /api/v1/shifts/calculate.
 * Missing breaks, rates, and currencies are explicitly preserved as null rather than defaulted.
 */
export function toBackendShiftInput(record: ShiftRecord): Record<string, unknown> {
  const v = record.current
  return {
    shift_id: record.shift_id,
    worker_id: record.worker_id,
    shift_date: normalizeOptionalString(v.shift_date),
    start_time: normalizeOptionalString(v.start_time),
    end_time: normalizeOptionalString(v.end_time),
    end_date: normalizeOptionalString(v.end_date),
    break_minutes: normalizeBreakMinutes(v.break_minutes),
    employer_name: normalizeOptionalString(v.employer_name),
    location: normalizeOptionalString(v.location),
    department: normalizeOptionalString(v.department),
    hourly_rate: normalizeOptionalString(v.hourly_rate),
    currency: normalizeOptionalString(v.currency),
    shift_status: v.shift_status || 'scheduled',
    confirmation_status: record.confirmation_status,
    source_line: record.source_line,
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown }
    if (typeof data?.detail === 'string') {
      return data.detail
    }
    if (Array.isArray(data?.detail) && data.detail.length > 0) {
      return data.detail
        .map((item) =>
          typeof item === 'object' && item !== null && 'msg' in item
            ? String((item as { msg: unknown }).msg)
            : JSON.stringify(item),
        )
        .join('; ')
    }
  } catch {
    // Fall back to HTTP status text when response body is not JSON
  }
  return `Backend request failed (${response.status} ${response.statusText || 'Error'})`
}

export async function checkHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const url = `${getApiBaseUrl()}/health`
  let response: Response
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    throw new ApiClientError(
      'Unable to reach the WorkClarity calculation service. Ensure the FastAPI backend is running.',
      undefined,
      true,
    )
  }

  if (!response.ok) {
    throw new ApiClientError(await parseErrorDetail(response), response.status)
  }

  return (await response.json()) as HealthResponse
}

export async function calculateShifts(
  workerId: string,
  records: ShiftRecord[],
  includeUnconfirmed = true,
  signal?: AbortSignal,
): Promise<ShiftCalculationResponse> {
  const url = `${getApiBaseUrl()}/api/v1/shifts/calculate`
  const payload: ShiftCalculationRequestPayload = {
    worker_id: workerId,
    shifts: records.map(toBackendShiftInput),
    include_unconfirmed: includeUnconfirmed,
  }

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    throw new ApiClientError(
      'Unable to connect to the WorkClarity backend to validate shifts and calculate earnings.',
      undefined,
      true,
    )
  }

  if (!response.ok) {
    throw new ApiClientError(await parseErrorDetail(response), response.status)
  }

  return (await response.json()) as ShiftCalculationResponse
}

export interface ExtractScheduleFileOptions {
  targetWorker?: string
  signal?: AbortSignal
}

/**
 * Send an unstructured schedule document (PDF, PNG, JPEG, WebP) to POST /api/v1/shifts/extract.
 * Uses FormData without manual Content-Type header so the browser sets the multipart boundary.
 */
export async function extractScheduleFile(
  file: File,
  options?: ExtractScheduleFileOptions,
): Promise<ShiftExtractionResponse> {
  const url = `${getApiBaseUrl()}/api/v1/shifts/extract`
  const formData = new FormData()
  formData.append('file', file)
  if (options?.targetWorker && options.targetWorker.trim()) {
    formData.append('target_worker', options.targetWorker.trim())
  }

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
      },
      body: formData,
      signal: options?.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    throw new ApiClientError(
      'Unable to connect to the WorkClarity extraction service. Ensure the FastAPI backend is running.',
      undefined,
      true,
    )
  }

  if (!response.ok) {
    throw new ApiClientError(await parseErrorDetail(response), response.status)
  }

  return (await response.json()) as ShiftExtractionResponse
}
