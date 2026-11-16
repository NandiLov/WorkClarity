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
} from '../api/shiftsApi'
import { DEMO_WORKERS, SCHEDULE_PRESETS } from '../data/syntheticSchedules'
import type {
  BackendShiftResult,
  CommuteNotAssessed,
  ConfirmationStatus,
  CsvParseResult,
  EditableShiftValues,
  HealthResponse,
  ShiftConflict,
  ShiftRecord,
  WeeklySummaryItem,
} from '../types/shift'
import { parseScheduleCsv } from '../utils/csvParser'
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
  shifts: ShiftRecord[]
  selectedWeek: string | null
  savedAt: string
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
        return {
          workerId,
          activeFileName: parsed.activeFileName ?? null,
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

  useEffect(() => {
    persistWorkerState({
      workerId,
      activeFileName,
      shifts,
      selectedWeek,
      savedAt: new Date().toISOString(),
    })
  }, [workerId, activeFileName, shifts, selectedWeek])

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
        initialConfirmations?: ConfirmationStatus[]
        useCsvConfirmationColumn?: boolean
      },
    ): CsvParseResult => {
      const result = parseScheduleCsv(csvText, {
        workerId,
        fileName,
        initialConfirmations: options?.initialConfirmations,
        useCsvConfirmationColumn: options?.useCsvConfirmationColumn,
      })
      if (result.ok) {
        setIsCalculationStale(true)
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
      confirmationStatus?: ConfirmationStatus,
    ) => {
      setIsCalculationStale(true)
      const now = new Date().toISOString()
      setShifts((prev) =>
        prev.map((rec) => {
          if (rec.shift_id !== shiftId) return rec
          return {
            ...rec,
            current: { ...rec.current, ...changes },
            confirmation_status:
              confirmationStatus ?? rec.confirmation_status,
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

  const confirmReadyShifts = useCallback((): number => {
    let count = 0
    const now = new Date().toISOString()
    setShifts((prev) =>
      prev.map((rec) => {
        if (rec.confirmation_status !== 'unconfirmed') return rec
        const hasError = rec.calculated?.validation_status === 'invalid'
        const isDuplicate = rec.calculated?.flags.some(
          (f) => f.code === 'POSSIBLE_DUPLICATE',
        )
        const missingEssential =
          rec.current.break_minutes.trim() === '' ||
          rec.current.hourly_rate.trim() === '' ||
          rec.current.currency.trim() === ''
        if (hasError || isDuplicate || missingEssential) {
          return rec
        }
        count += 1
        return {
          ...rec,
          confirmation_status: 'confirmed',
          updated_at: now,
        }
      }),
    )
    if (count > 0) {
      setIsCalculationStale(true)
    }
    return count
  }, [])

  const resetShiftToExtracted = useCallback((shiftId: string) => {
    setIsCalculationStale(true)
    const now = new Date().toISOString()
    setShifts((prev) =>
      prev.map((rec) =>
        rec.shift_id === shiftId
          ? {
              ...rec,
              current: { ...rec.extracted },
              confirmation_status: 'unconfirmed',
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

  const warningsCount = useMemo(() => {
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
    return conflicts.length + commuteNotAssessed.length + flaggedShiftIds.size
  }, [shifts, conflicts.length, commuteNotAssessed.length])

  const value: ScheduleContextValue = {
    workerId,
    workers: DEMO_WORKERS,
    activeFileName,
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
    warningsCount,
    needsAttentionCount: reviewQueueCount,
    selectWorker,
    uploadCsvText,
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
