import { createContext, useContext } from 'react'
import type { DEMO_WORKERS } from '../data/syntheticSchedules'
import type {
  CommuteNotAssessed,
  ConfirmationStatus,
  CsvParseResult,
  EditableShiftValues,
  HealthResponse,
  ShiftConflict,
  ShiftRecord,
  WeeklySummaryItem,
} from '../types/shift'

export type BackendConnectionStatus = 'checking' | 'online' | 'offline'

export interface ScheduleContextValue {
  workerId: string
  workers: typeof DEMO_WORKERS
  activeFileName: string | null
  shifts: ShiftRecord[]
  weeklySummary: WeeklySummaryItem[]
  conflicts: ShiftConflict[]
  commuteNotAssessed: CommuteNotAssessed[]
  availableWeeks: string[]
  selectedWeek: string | null
  setSelectedWeek: (week: string | null) => void

  // Backend sync & stale guards
  backendStatus: BackendConnectionStatus
  backendHealth: HealthResponse | null
  isRecalculating: boolean
  isCalculationStale: boolean
  calculationError: string | null
  lastCalculatedAt: string | null

  // Derived badge counts for navigation
  reviewQueueCount: number
  warningsCount: number
  needsAttentionCount: number

  // Actions
  selectWorker: (newWorkerId: string) => void
  uploadCsvText: (
    csvText: string,
    fileName: string,
    options?: {
      initialConfirmations?: ConfirmationStatus[]
      useCsvConfirmationColumn?: boolean
    },
  ) => CsvParseResult
  loadPresetSchedule: (presetId: string) => CsvParseResult | null
  updateShift: (
    shiftId: string,
    changes: Partial<EditableShiftValues>,
    confirmationStatus?: ConfirmationStatus,
  ) => void
  setShiftConfirmation: (shiftId: string, status: ConfirmationStatus) => void
  confirmReadyShifts: () => number
  resetShiftToExtracted: (shiftId: string) => void
  addManualShift: (values: EditableShiftValues) => void
  clearWorkerSchedule: () => void
  retryCalculation: () => void
}

export const ScheduleContext = createContext<ScheduleContextValue | null>(null)

export function useSchedule(): ScheduleContextValue {
  const ctx = useContext(ScheduleContext)
  if (!ctx) {
    throw new Error('useSchedule must be used within a ScheduleProvider')
  }
  return ctx
}
