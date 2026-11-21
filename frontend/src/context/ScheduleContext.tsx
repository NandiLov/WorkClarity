import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  ApiClientError,
  calculateShifts,
  checkHealth,
  extractScheduleFile,
} from '../api/shiftsApi'
import { DEMO_WORKERS, SCHEDULE_PRESETS } from '../data/syntheticSchedules'
import type {
  BackendShiftResult,
  CommuteNotAssessed,
  ConfirmationStatus,
  CsvParseResult,
  EditableShiftValues,
  ExtractionIntegrationResult,
  HealthResponse,
  ShiftConflict,
  ShiftExtractionResponse,
  ShiftRecord,
  UploadMode,
  WeeklySummaryItem,
} from '../types/shift'
import { createScheduleId, parseScheduleCsv } from '../utils/csvParser'
import {
  ScheduleContext,
  type BackendConnectionStatus,
  type ScheduleContextValue,
} from './scheduleContextStore'

const STORAGE_PREFIX = 'workclarity_dev_state_v1_'
const ACTIVE_WORKER_KEY = 'workclarity_dev_active_worker_v1'

interface PersistedWorkerState {
  workerId: string
  activeFileName: string | null
  uploadedFiles?: string[]
  shifts: ShiftRecord[]
  selectedWeek: string | null
  savedAt: string
}

const EDITABLE_KEYS: Array<keyof EditableShiftValues> = [
  'shift_date',
  'start_time',
  'end_time',
  'end_date',
  'break_minutes',
  'employer_name',
  'location',
  'department',
  'hourly_rate',
  'currency',
  'shift_status',
  'stated_hours',
]

function haveShiftValuesChanged(
  a: EditableShiftValues,
  b: EditableShiftValues,
): boolean {
  return EDITABLE_KEYS.some((key) => a[key] !== b[key])
}

function isShiftReadyForBulkConfirm(rec: ShiftRecord): boolean {
  if (rec.confirmation_status !== 'unconfirmed') return false
  if (
    rec.is_ai_extracted ||
    rec.ai_metadata?.eligible_for_bulk_confirmation === false ||
    rec.ai_metadata?.requires_individual_review
  ) {
    return false
  }
  if (!rec.calculated) return false
  if (rec.calculated.validation_status === 'invalid') return false
  const hasBlockingFlag = rec.calculated.flags.some(
    (f) => f.code === 'POSSIBLE_DUPLICATE' || f.code === 'OVERLAP',
  )
  if (hasBlockingFlag) return false

  const c = rec.current
  if (
    c.shift_date.trim() === '' ||
    c.start_time.trim() === '' ||
    c.end_time.trim() === '' ||
    c.break_minutes.trim() === '' ||
    c.hourly_rate.trim() === '' ||
    c.currency.trim() === ''
  ) {
    return false
  }
  return true
}

function shiftDuplicateKey(v: EditableShiftValues): string {
  return [
    v.shift_date.trim(),
    v.start_time.trim(),
    v.end_time.trim(),
    v.location.trim().toLowerCase(),
  ].join('|')
}

function formatUploadedFilesSummary(files: string[]): string | null {
  if (files.length === 0) return null
  if (files.length === 1) return files[0]
  return `${files.length} schedules: ${files.join(', ')}`
}

function getStorageKey(workerId: string): string {
  return `${STORAGE_PREFIX}${workerId}`
}

function loadInitialWorkerId(): string {
  try {
    const saved = localStorage.getItem(ACTIVE_WORKER_KEY)
    if (saved && DEMO_WORKERS.some((w) => w.worker_id === saved)) {
      return saved
    }
  } catch {
    // Ignore storage errors
  }
  return DEMO_WORKERS[0].worker_id
}

function loadPersistedWorkerState(workerId: string): PersistedWorkerState {
  try {
    const raw = localStorage.getItem(getStorageKey(workerId))
    if (raw) {
      const parsed = JSON.parse(raw) as PersistedWorkerState
      if (parsed && Array.isArray(parsed.shifts)) {
        const files = Array.isArray(parsed.uploadedFiles)
          ? parsed.uploadedFiles
          : parsed.activeFileName
            ? [parsed.activeFileName]
            : []
        return {
          workerId,
          activeFileName:
            parsed.activeFileName ?? formatUploadedFilesSummary(files),
          uploadedFiles: files,
          shifts: parsed.shifts,
          selectedWeek: parsed.selectedWeek ?? null,
          savedAt: parsed.savedAt ?? new Date().toISOString(),
        }
      }
    }
  } catch {
    // Ignore malformed local storage
  }
  return {
    workerId,
    activeFileName: null,
    uploadedFiles: [],
    shifts: [],
    selectedWeek: null,
    savedAt: new Date().toISOString(),
  }
}

function persistWorkerState(state: PersistedWorkerState): void {
  try {
    localStorage.setItem(getStorageKey(state.workerId), JSON.stringify(state))
  } catch {
    // Ignore quota/storage errors in restricted contexts
  }
}

export function ScheduleProvider({ children }: { children: ReactNode }) {
  const [workerId, setWorkerId] = useState<string>(() => loadInitialWorkerId())
  const initialState = useMemo(
    () => loadPersistedWorkerState(loadInitialWorkerId()),
    [],
  )

  const [uploadedFiles, setUploadedFiles] = useState<string[]>(
    initialState.uploadedFiles ?? [],
  )
  const [activeFileName, setActiveFileName] = useState<string | null>(
    initialState.activeFileName,
  )
  const [shifts, setShifts] = useState<ShiftRecord[]>(initialState.shifts)
  const [selectedWeek, setSelectedWeek] = useState<string | null>(
    initialState.selectedWeek,
  )

  const [weeklySummary, setWeeklySummary] = useState<WeeklySummaryItem[]>([])
  const [conflicts, setConflicts] = useState<ShiftConflict[]>([])
  const [commuteNotAssessed, setCommuteNotAssessed] = useState<
    CommuteNotAssessed[]
  >([])

  const [backendStatus, setBackendStatus] =
    useState<BackendConnectionStatus>('checking')
  const [backendHealth, setBackendHealth] = useState<HealthResponse | null>(
    null,
  )
  const [isRecalculating, setIsRecalculating] = useState<boolean>(false)
  const [isCalculationStale, setIsCalculationStale] = useState<boolean>(
    initialState.shifts.length > 0,
  )
  const [calculationError, setCalculationError] = useState<string | null>(null)
  const [lastCalculatedAt, setLastCalculatedAt] = useState<string | null>(null)

  const requestCounterRef = useRef<number>(0)
  const abortControllerRef = useRef<AbortController | null>(null)
  const [syncTrigger, setSyncTrigger] = useState<number>(0)

  const shiftInputSignature = useMemo(
    () =>
      JSON.stringify(
        shifts.map((s) => ({
          id: s.shift_id,
          c: s.current,
          cs: s.confirmation_status,
        })),
      ),
    [shifts],
  )

  const shiftsSnapshotRef = useRef<ShiftRecord[]>(shifts)
  useEffect(() => {
    shiftsSnapshotRef.current = shifts
  }, [shifts])

  const uploadedFilesSnapshotRef = useRef<string[]>(uploadedFiles)
  useEffect(() => {
    uploadedFilesSnapshotRef.current = uploadedFiles
  }, [uploadedFiles])

  useEffect(() => {
    persistWorkerState({
      workerId,
      activeFileName,
      uploadedFiles,
      shifts,
      selectedWeek,
      savedAt: new Date().toISOString(),
    })
  }, [workerId, activeFileName, uploadedFiles, shifts, selectedWeek])

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVE_WORKER_KEY, workerId)
    } catch {
      // Ignore storage errors
    }
  }, [workerId])

  useEffect(() => {
    const currentShifts = shiftsSnapshotRef.current
    const requestId = ++requestCounterRef.current
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    let cancelled = false

    async function syncWithBackend() {
      setIsRecalculating(true)
      setCalculationError(null)

      try {
        const healthPromise = checkHealth(controller.signal)

        if (currentShifts.length === 0) {
          const health = await healthPromise
          if (cancelled || requestId !== requestCounterRef.current) return
          setBackendHealth(health)
          setBackendStatus('online')
          setWeeklySummary([])
          setConflicts([])
          setCommuteNotAssessed([])
          setIsCalculationStale(false)
          setIsRecalculating(false)
          setLastCalculatedAt(new Date().toISOString())
          return
        }

        const [health, calcResponse] = await Promise.all([
          healthPromise.catch(() => null),
          calculateShifts(workerId, currentShifts, true, controller.signal),
        ])

        if (cancelled || requestId !== requestCounterRef.current) {
          return
        }

        if (health) {
          setBackendHealth(health)
        }
        setBackendStatus('online')

        const resultById = new Map<string, BackendShiftResult>()
        for (const item of calcResponse.shifts) {
          resultById.set(item.shift_id, item)
        }

        setShifts((prev) =>
          prev.map((rec) => ({
            ...rec,
            calculated: resultById.get(rec.shift_id) ?? null,
          })),
        )
        setWeeklySummary(calcResponse.weekly_summary)
        setConflicts(calcResponse.conflicts)
        setCommuteNotAssessed(calcResponse.commute_not_assessed)
        setIsCalculationStale(false)
        setCalculationError(null)
        setLastCalculatedAt(new Date().toISOString())
        setIsRecalculating(false)

        const weeks = Array.from(
          new Set(
            calcResponse.weekly_summary
              .map((w) => w.week_start)
              .filter(Boolean),
          ),
        ).sort()
        setSelectedWeek((currentWeek) => {
          if (currentWeek && weeks.includes(currentWeek)) {
            return currentWeek
          }
          return weeks[0] ?? null
        })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return
        }
        if (cancelled || requestId !== requestCounterRef.current) {
          return
        }
        const message =
          err instanceof ApiClientError
            ? err.message
            : 'Failed to communicate with the FastAPI calculation service.'
        setBackendStatus('offline')
        setIsCalculationStale(true)
        setCalculationError(message)
        setIsRecalculating(false)
      }
    }

    void syncWithBackend()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [workerId, syncTrigger, shiftInputSignature])

  const selectWorker = useCallback(
    (newWorkerId: string) => {
      if (newWorkerId === workerId) return
      const loaded = loadPersistedWorkerState(newWorkerId)
      setWorkerId(newWorkerId)
      setUploadedFiles(loaded.uploadedFiles ?? [])
      setActiveFileName(loaded.activeFileName)
      setShifts(loaded.shifts)
      setSelectedWeek(loaded.selectedWeek)
      setWeeklySummary([])
      setConflicts([])
      setCommuteNotAssessed([])
      setIsCalculationStale(loaded.shifts.length > 0)
      setCalculationError(null)
    },
    [workerId],
  )

  const uploadCsvText = useCallback(
    (
      csvText: string,
      fileName: string,
      options?: {
        mode?: UploadMode
        initialConfirmations?: ConfirmationStatus[]
        useCsvConfirmationColumn?: boolean
      },
    ): CsvParseResult => {
      const existingShifts = shiftsSnapshotRef.current
      const mode: UploadMode =
        existingShifts.length === 0 ? 'replace' : (options?.mode ?? 'append')
      const existingScheduleIds =
        mode === 'append'
          ? new Set(existingShifts.map((s) => s.schedule_id))
          : undefined

      const result = parseScheduleCsv(csvText, {
        workerId,
        fileName,
        existingScheduleIds,
        initialConfirmations: options?.initialConfirmations,
        useCsvConfirmationColumn: options?.useCsvConfirmationColumn,
      })

      if (!result.ok) {
        return result
      }

      if (mode === 'append' && existingShifts.length > 0) {
        const existingKeys = new Set(
          existingShifts
            .filter((s) => s.confirmation_status !== 'rejected')
            .map((s) => shiftDuplicateKey(s.current)),
        )
        const matchingDuplicates = result.shifts.filter((s) =>
          existingKeys.has(shiftDuplicateKey(s.current)),
        ).length
        if (matchingDuplicates > 0) {
          result.warnings.push(
            `${matchingDuplicates} imported shift(s) match existing shifts (same date, times, and location) and will be held for review so earnings are never double-counted.`,
          )
        }

        const nextFiles = [...uploadedFilesSnapshotRef.current, fileName]
        setIsCalculationStale(true)
        setUploadedFiles(nextFiles)
        setActiveFileName(formatUploadedFilesSummary(nextFiles))
        setShifts((prev) => [...prev, ...result.shifts])
      } else {
        const nextFiles = [fileName]
        setIsCalculationStale(true)
        setUploadedFiles(nextFiles)
        setActiveFileName(fileName)
        setShifts(result.shifts)
        setSelectedWeek(null)
        setWeeklySummary([])
        setConflicts([])
        setCommuteNotAssessed([])
      }

      return result
    },
    [workerId],
  )

  const uploadExtractionResult = useCallback(
    (
      extraction: ShiftExtractionResponse,
      options?: { mode?: UploadMode },
    ): ExtractionIntegrationResult => {
      const existingShifts = shiftsSnapshotRef.current
      const mode: UploadMode =
        existingShifts.length === 0 ? 'replace' : (options?.mode ?? 'append')
      const existingScheduleIds =
        mode === 'append'
          ? new Set(existingShifts.map((s) => s.schedule_id))
          : undefined

      const scheduleId = createScheduleId(
        extraction.file_name,
        undefined,
        existingScheduleIds,
      )

      const errors: string[] = []
      const warnings: string[] = []

      if (extraction.shifts.length === 0) {
        if (!extraction.succeeded) {
          errors.push(
            extraction.manual_entry_reason ||
              'Schedule extraction could not extract shifts from the provided document.',
          )
        } else if (extraction.is_empty_schedule) {
          errors.push(
            extraction.manual_entry_reason ||
              'The uploaded document contains no scheduled shifts for this period. Please verify or enter shifts manually.',
          )
        } else {
          errors.push(
            'No valid shifts could be extracted from this document. Manual entry is required.',
          )
        }

        return {
          ok: false,
          scheduleId,
          fileName: extraction.file_name,
          shifts: [],
          extraction,
          errors,
          warnings,
        }
      }

      if (extraction.is_partial) {
        warnings.push(
          extraction.manual_entry_reason ||
            'Only part of the schedule could be extracted. Please review every shift and enter any missing shifts manually.',
        )
      }

      if (extraction.fallback_triggered && extraction.active_provider) {
        warnings.push(
          `Primary provider was unavailable. Shifts were extracted using fallback provider (${extraction.active_provider}).`,
        )
      }

      const nowIso = new Date().toISOString()
      const convertedShifts: ShiftRecord[] = extraction.shifts.map(
        (item, index) => {
          const lineNo = item.source_row ?? index + 1
          const shiftId = `${scheduleId}-AI${String(index + 1).padStart(2, '0')}`

          const extractedValues: EditableShiftValues = {
            shift_date: item.normalised.shift_date ?? '',
            start_time: item.normalised.start_time ?? '',
            end_time: item.normalised.end_time ?? '',
            end_date: '',
            break_minutes: item.normalised.break_minutes != null ? String(item.normalised.break_minutes) : '',
            employer_name: item.normalised.employer_name ?? '',
            location: item.normalised.location ?? '',
            department: item.normalised.department ?? '',
            hourly_rate: item.normalised.hourly_rate != null ? String(item.normalised.hourly_rate) : '',
            currency: item.normalised.currency ?? '',
            shift_status: item.normalised.shift_status ?? 'scheduled',
            stated_hours: '',
          }

          // Individual confirmation is mandatory for all AI-extracted shifts
          const record: ShiftRecord = {
            shift_id: shiftId,
            worker_id: workerId,
            schedule_id: scheduleId,
            line_no: lineNo,
            source_line: item.raw_values
              ? JSON.stringify(item.raw_values)
              : JSON.stringify(item.normalised),
            extracted: { ...extractedValues },
            current: { ...extractedValues },
            confirmation_status: 'needs_review',
            calculated: null,
            updated_at: nowIso,
            is_ai_extracted: true,
            ai_metadata: {
              confidence: item.confidence,
              provider: extraction.active_provider,
              model_id: extraction.active_model_id,
              worker_name: item.worker_name,
              worker_attribution_status: item.worker_attribution_status,
              source_page: item.source_page,
              source_row: item.source_row,
              requires_individual_review: true,
              eligible_for_bulk_confirmation: false,
              review_reasons: item.review_reasons ?? [],
              uncertain_fields: item.uncertain_fields ?? [],
              validation_warnings: item.validation_warnings ?? [],
            },
          }

          return record
        },
      )

      if (
        convertedShifts.some(
          (s) =>
            s.ai_metadata?.worker_attribution_status ===
            'ambiguous_or_unverified',
        )
      ) {
        warnings.push(
          'One or more shifts have ambiguous worker attribution. Please verify worker names before confirming.',
        )
      }

      if (mode === 'append' && existingShifts.length > 0) {
        const existingKeys = new Set(
          existingShifts
            .filter((s) => s.confirmation_status !== 'rejected')
            .map((s) => shiftDuplicateKey(s.current)),
        )
        const matchingDuplicates = convertedShifts.filter((s) =>
          existingKeys.has(shiftDuplicateKey(s.current)),
        ).length
        if (matchingDuplicates > 0) {
          warnings.push(
            `${matchingDuplicates} extracted shift(s) match existing shifts (same date, times, and location) and will be held for review so earnings are never double-counted.`,
          )
        }

        const nextFiles = [
          ...uploadedFilesSnapshotRef.current,
          extraction.file_name,
        ]
        setIsCalculationStale(true)
        setUploadedFiles(nextFiles)
        setActiveFileName(formatUploadedFilesSummary(nextFiles))
        setShifts((prev) => [...prev, ...convertedShifts])
      } else {
        const nextFiles = [extraction.file_name]
        setIsCalculationStale(true)
        setUploadedFiles(nextFiles)
        setActiveFileName(extraction.file_name)
        setShifts(convertedShifts)
        setSelectedWeek(null)
        setWeeklySummary([])
        setConflicts([])
        setCommuteNotAssessed([])
      }

      return {
        ok: errors.length === 0,
        scheduleId,
        fileName: extraction.file_name,
        shifts: convertedShifts,
        extraction,
        errors,
        warnings,
      }
    },
    [workerId],
  )

  const extractAndUploadFile = useCallback(
    async (
      file: File,
      options?: {
        mode?: UploadMode
        targetWorker?: string
      },
    ): Promise<ExtractionIntegrationResult> => {
      try {
        const activeWorkerName =
          DEMO_WORKERS.find((w) => w.worker_id === workerId)?.worker_name ??
          workerId
        const targetWorker = options?.targetWorker ?? activeWorkerName
        const extraction = await extractScheduleFile(file, { targetWorker })
        return uploadExtractionResult(extraction, { mode: options?.mode })
      } catch (err) {
        const errorMsg =
          err instanceof ApiClientError
            ? err.message
            : err instanceof Error
              ? err.message
              : 'Failed to extract shifts from the uploaded document.'
        return {
          ok: false,
          scheduleId: '',
          fileName: file.name,
          shifts: [],
          errors: [errorMsg],
          warnings: [],
        }
      }
    },
    [workerId, uploadExtractionResult],
  )

  const loadPresetSchedule = useCallback(
    (presetId: string): CsvParseResult | null => {
      const preset = SCHEDULE_PRESETS.find((p) => p.id === presetId)
      if (!preset) return null

      setWorkerId(preset.workerId)
      const result = parseScheduleCsv(preset.csvText, {
        workerId: preset.workerId,
        fileName: preset.fileName,
        initialConfirmations: preset.initialConfirmations,
      })
      if (result.ok) {
        setIsCalculationStale(true)
        setUploadedFiles([preset.fileName])
        setActiveFileName(preset.fileName)
        setShifts(result.shifts)
        setSelectedWeek(null)
        setWeeklySummary([])
        setConflicts([])
        setCommuteNotAssessed([])
      }
      return result
    },
    [],
  )

  const updateShift = useCallback(
    (
      shiftId: string,
      changes: Partial<EditableShiftValues>,
      explicitConfirmationStatus?: ConfirmationStatus,
    ) => {
      setIsCalculationStale(true)
      const now = new Date().toISOString()
      setShifts((prev) =>
        prev.map((rec) => {
          if (rec.shift_id !== shiftId) return rec
          const nextCurrent: EditableShiftValues = { ...rec.current, ...changes }
          const detailChanged = haveShiftValuesChanged(rec.current, nextCurrent)

          let nextStatus: ConfirmationStatus
          if (explicitConfirmationStatus !== undefined) {
            nextStatus = explicitConfirmationStatus
          } else if (detailChanged && rec.confirmation_status === 'confirmed') {
            // Any edit to details of a previously confirmed shift requires renewed confirmation
            nextStatus = rec.is_ai_extracted ? 'needs_review' : 'unconfirmed'
          } else {
            nextStatus = rec.confirmation_status
          }

          return {
            ...rec,
            previous_current: detailChanged
              ? { ...rec.current }
              : rec.previous_current,
            current: nextCurrent,
            confirmation_status: nextStatus,
            updated_at: now,
          }
        }),
      )
    },
    [],
  )

  const setShiftConfirmation = useCallback(
    (shiftId: string, status: ConfirmationStatus) => {
      setIsCalculationStale(true)
      const now = new Date().toISOString()
      setShifts((prev) =>
        prev.map((rec) =>
          rec.shift_id === shiftId
            ? { ...rec, confirmation_status: status, updated_at: now }
            : rec,
        ),
      )
    },
    [],
  )

  const readyToConfirmCount = useMemo(
    () => shifts.filter(isShiftReadyForBulkConfirm).length,
    [shifts],
  )

  const canBulkConfirm =
    !isRecalculating &&
    !isCalculationStale &&
    backendStatus === 'online' &&
    readyToConfirmCount > 0

  const confirmReadyShifts = useCallback((): number => {
    if (isRecalculating || isCalculationStale || backendStatus !== 'online') {
      return 0
    }
    const eligibleIds = new Set(
      shiftsSnapshotRef.current
        .filter(isShiftReadyForBulkConfirm)
        .map((s) => s.shift_id),
    )
    if (eligibleIds.size === 0) {
      return 0
    }

    setIsCalculationStale(true)
    const now = new Date().toISOString()
    setShifts((prev) =>
      prev.map((rec) =>
        eligibleIds.has(rec.shift_id)
          ? { ...rec, confirmation_status: 'confirmed', updated_at: now }
          : rec,
      ),
    )
    return eligibleIds.size
  }, [isRecalculating, isCalculationStale, backendStatus])

  const resetShiftToExtracted = useCallback((shiftId: string) => {
    setIsCalculationStale(true)
    const now = new Date().toISOString()
    setShifts((prev) =>
      prev.map((rec) =>
        rec.shift_id === shiftId
          ? {
              ...rec,
              previous_current: undefined,
              current: { ...rec.extracted },
              confirmation_status: rec.is_ai_extracted
                ? 'needs_review'
                : 'unconfirmed',
              updated_at: now,
            }
          : rec,
      ),
    )
  }, [])

  const addManualShift = useCallback(
    (values: EditableShiftValues) => {
      setIsCalculationStale(true)
      const now = new Date().toISOString()
      const suffix = Math.random().toString(36).slice(2, 6).toUpperCase()
      const newRecord: ShiftRecord = {
        shift_id: `MANUAL-${Date.now()}-${suffix}`,
        worker_id: workerId,
        schedule_id: 'MANUAL',
        line_no: shifts.length + 1,
        source_line: 'Manual entry in WorkClarity',
        extracted: { ...values },
        current: { ...values },
        confirmation_status: 'unconfirmed',
        calculated: null,
        updated_at: now,
      }
      setShifts((prev) => [...prev, newRecord])
    },
    [shifts.length, workerId],
  )

  const clearWorkerSchedule = useCallback(() => {
    setUploadedFiles([])
    setActiveFileName(null)
    setShifts([])
    setSelectedWeek(null)
    setWeeklySummary([])
    setConflicts([])
    setCommuteNotAssessed([])
    setIsCalculationStale(false)
    setCalculationError(null)
  }, [])

  const retryCalculation = useCallback(() => {
    setSyncTrigger((n) => n + 1)
  }, [])

  const availableWeeks = useMemo(() => {
    const weeks = new Set<string>()
    for (const w of weeklySummary) {
      if (w.week_start) weeks.add(w.week_start)
    }
    for (const s of shifts) {
      if (s.calculated?.week_start) weeks.add(s.calculated.week_start)
    }
    return Array.from(weeks).sort()
  }, [weeklySummary, shifts])

  const reviewQueueCount = useMemo(() => {
    return shifts.filter((s) => {
      const status = s.calculated?.earnings_status
      if (!status) {
        return s.confirmation_status !== 'rejected'
      }
      return (
        status === 'unconfirmed' ||
        status === 'needs_review' ||
        status === 'incomplete' ||
        status === 'excluded'
      )
    }).length
  }, [shifts])

  const scheduleAlertsCount = useMemo(
    () => conflicts.length + commuteNotAssessed.length,
    [conflicts.length, commuteNotAssessed.length],
  )

  const flaggedShiftsCount = useMemo(() => {
    const flaggedShiftIds = new Set<string>()
    for (const s of shifts) {
      if (s.confirmation_status === 'rejected') continue
      const hasActionableFlag = s.calculated?.flags.some(
        (f) => f.severity === 'error' || f.severity === 'warning',
      )
      if (hasActionableFlag) {
        flaggedShiftIds.add(s.shift_id)
      }
    }
    return flaggedShiftIds.size
  }, [shifts])

  const warningsCount = scheduleAlertsCount + flaggedShiftsCount

  const value: ScheduleContextValue = {
    workerId,
    workers: DEMO_WORKERS,
    activeFileName,
    uploadedFiles,
    shifts,
    weeklySummary,
    conflicts,
    commuteNotAssessed,
    availableWeeks,
    selectedWeek,
    setSelectedWeek,
    backendStatus,
    backendHealth,
    isRecalculating,
    isCalculationStale,
    calculationError,
    lastCalculatedAt,
    reviewQueueCount,
    scheduleAlertsCount,
    flaggedShiftsCount,
    warningsCount,
    needsAttentionCount: reviewQueueCount,
    readyToConfirmCount,
    canBulkConfirm,
    selectWorker,
    uploadCsvText,
    uploadExtractionResult,
    extractAndUploadFile,
    loadPresetSchedule,
    updateShift,
    setShiftConfirmation,
    confirmReadyShifts,
    resetShiftToExtracted,
    addManualShift,
    clearWorkerSchedule,
    retryCalculation,
  }

  return (
    <ScheduleContext.Provider value={value}>{children}</ScheduleContext.Provider>
  )
}
