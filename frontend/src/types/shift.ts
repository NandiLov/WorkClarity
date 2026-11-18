export type ShiftStatus = 'scheduled' | 'changed' | 'cancelled'

export type ConfirmationStatus =
  | 'unconfirmed'
  | 'needs_review'
  | 'confirmed'
  | 'rejected'

export type ValidationStatus = 'valid' | 'warning' | 'invalid'

export type EarningsStatus =
  | 'counted'
  | 'incomplete'
  | 'excluded'
  | 'unconfirmed'
  | 'needs_review'
  | 'rejected'
  | 'cancelled'

export type FlagSeverity = 'error' | 'warning' | 'info'

export interface ShiftFlag {
  code: string
  flag_type_id: string
  flag_name: string
  severity: FlagSeverity
  reason: string
  message: string
}

export interface EditableShiftValues {
  shift_date: string
  start_time: string
  end_time: string
  end_date: string
  break_minutes: string
  employer_name: string
  location: string
  department: string
  hourly_rate: string
  currency: string
  shift_status: ShiftStatus
  stated_hours: string
}

export interface BackendShiftResult {
  shift_id: string
  date: string | null
  week_start: string | null
  paid_hours: number | null
  hourly_rate: number | null
  currency: string | null
  gross_earnings: number | null
  validation_status: ValidationStatus
  earnings_status: EarningsStatus
  eligible_for_earnings: boolean
  earnings_reason: string | null
  flags: ShiftFlag[]
  source_line?: string | null
}

export interface ShiftRecord {
  shift_id: string
  worker_id: string
  schedule_id: string
  line_no: number
  source_line: string
  extracted: EditableShiftValues
  previous_current?: EditableShiftValues
  current: EditableShiftValues
  confirmation_status: ConfirmationStatus
  calculated: BackendShiftResult | null
  updated_at: string
}

export type UploadMode = 'append' | 'replace'

export interface WeeklySummaryItem {
  week_start: string
  currency: string | null
  shifts: number
  paid_hours: number
  incomplete_hours: number
  pending_hours: number
  gross_earnings: number | null
  incomplete_shifts: number
  pending_shifts: number
  earnings_incomplete: boolean
  cancelled_shifts: number
}

export interface ShiftConflict {
  shift_a_id: string
  shift_b_id: string
  conflict_type: 'overlap' | 'commute_conflict' | string
  gap_minutes: number | null
  flag_type_id: string
  flag_name: string
  message: string
}

export interface CommuteNotAssessed {
  shift_a_id: string
  shift_b_id: string
  gap_minutes: number | null
  message: string
}

export interface ShiftCalculationRequestPayload {
  worker_id: string
  shifts: Record<string, unknown>[]
  include_unconfirmed?: boolean
}

export interface ShiftCalculationResponse {
  worker_id: string
  shifts: BackendShiftResult[]
  weekly_summary: WeeklySummaryItem[]
  conflicts: ShiftConflict[]
  commute_not_assessed: CommuteNotAssessed[]
}

export interface HealthResponse {
  status: string
  service: string
  version: string
}

export interface WorkerProfile {
  worker_id: string
  worker_name: string
  role_summary: string
}

export interface SchedulePreset {
  id: string
  title: string
  subtitle: string
  workerId: string
  fileName: string
  csvText: string
  initialConfirmations?: ConfirmationStatus[]
  scenarioTag: string
}

export interface FieldDiff {
  field: keyof EditableShiftValues
  label: string
  originalValue: string
  currentValue: string
}

export interface CsvParseResult {
  ok: boolean
  scheduleId: string
  fileName: string
  shifts: ShiftRecord[]
  errors: string[]
  warnings: string[]
}
