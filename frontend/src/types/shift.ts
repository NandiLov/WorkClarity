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

export type WorkerAttributionStatus =
  | 'not_applicable'
  | 'verified_target_worker'
  | 'ambiguous_or_unverified'

export type ExtractionConfidence = 'high' | 'medium' | 'low'

export interface ExtractionShiftMetadata {
  confidence: ExtractionConfidence
  provider?: string | null
  model_id?: string | null
  worker_name?: string | null
  worker_attribution_status: WorkerAttributionStatus
  source_page?: number | null
  source_row?: number | null
  requires_individual_review: boolean
  eligible_for_bulk_confirmation: boolean
  review_reasons: string[]
  uncertain_fields: string[]
  validation_warnings: string[]
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
  is_ai_extracted?: boolean
  ai_metadata?: ExtractionShiftMetadata
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

export interface ExtractedNormalisedShift {
  shift_date: string | null
  start_time: string | null
  end_time: string | null
  break_minutes: string | number | null
  employer_name: string | null
  location: string | null
  department: string | null
  hourly_rate: string | number | null
  currency: string | null
  shift_status: ShiftStatus
}

export interface ExtractedShiftRecordItem {
  raw_values?: Record<string, unknown>
  normalised: ExtractedNormalisedShift
  worker_corrected_values?: ExtractedNormalisedShift | null
  source_page?: number | null
  source_row?: number | null
  worker_name?: string | null
  worker_attribution_status: WorkerAttributionStatus
  confidence: ExtractionConfidence
  uncertain_fields?: string[]
  validation_warnings?: string[]
  review_reasons?: string[]
  partially_recovered?: boolean
  confirmation_status: ConfirmationStatus
  requires_worker_confirmation: boolean
  requires_individual_review: boolean
  eligible_for_bulk_confirmation: boolean
  deduplicated_provenance?: Record<string, unknown>[]
  conflict_group_id?: string | null
  conflicting_fields?: string[]
  requires_conflict_resolution?: boolean
  conflict_resolved?: boolean
}

export interface TokenUsagePayload {
  prompt_tokens: number
  completion_tokens: number
  reasoning_tokens?: number
  total_tokens: number
}

export interface ShiftExtractionResponse {
  file_name: string
  target_worker: string | null
  page_count: number
  extraction_status: string
  succeeded: boolean
  is_complete: boolean
  is_partial: boolean
  is_failed: boolean
  is_empty_schedule: boolean
  manual_entry_required: boolean
  manual_entry_reason: string | null
  active_provider: string | null
  active_model_id: string | null
  fallback_triggered: boolean
  fallback_trigger_category?: string | null
  processing_time_seconds: number
  token_usage?: TokenUsagePayload | null
  total_shifts_extracted: number
  shifts: ExtractedShiftRecordItem[]
}

export interface ExtractionIntegrationResult {
  ok: boolean
  scheduleId: string
  fileName: string
  shifts: ShiftRecord[]
  extraction?: ShiftExtractionResponse
  errors: string[]
  warnings: string[]
}
