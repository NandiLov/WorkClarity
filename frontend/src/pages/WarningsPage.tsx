import { useMemo, useState } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Edit3,
  MapPinOff,
  Route,
  XCircle,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  AiExtractionBadge,
  FlagBadge,
  WorkerAttributionBadge,
} from '../components/shifts/FlagBadge'
import { ShiftEditModal } from '../components/shifts/ShiftEditModal'
import { TechnicalDetailsDisclosure } from '../components/shifts/TechnicalDetailsDisclosure'
import { useSchedule } from '../context/scheduleContextStore'
import type { ShiftRecord } from '../types/shift'
import { formatDateDisplay } from '../utils/formatters'

export function WarningsPage() {
  const {
    shifts,
    workerId,
    workers,
    conflicts,
    commuteNotAssessed,
    isCalculationStale,
    updateShift,
    setShiftConfirmation,
    confirmWorkerAssignment,
    resetShiftToExtracted,
    addManualShift,
  } = useSchedule()

  const [editingShift, setEditingShift] = useState<ShiftRecord | null>(null)

  const shiftById = useMemo(() => {
    const map = new Map<string, ShiftRecord>()
    for (const s of shifts) map.set(s.shift_id, s)
    return map
  }, [shifts])

  const overlaps = conflicts.filter((c) => c.conflict_type === 'overlap')
  const commuteConflicts = conflicts.filter(
    (c) => c.conflict_type !== 'overlap',
  )

  const duplicateShifts = shifts.filter(
    (s) =>
      s.confirmation_status !== 'rejected' &&
      s.calculated?.flags.some((f) => f.code === 'POSSIBLE_DUPLICATE'),
  )

  const detailIssueShifts = shifts.filter((s) => {
    if (s.confirmation_status === 'rejected') return false
    return s.calculated?.flags.some(
      (f) => f.severity === 'error' || f.severity === 'warning',
    )
  })

  const totalAlerts =
    overlaps.length +
    commuteConflicts.length +
    commuteNotAssessed.length +
    detailIssueShifts.length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Warnings &amp; Conflicts
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Resolve overlapping shifts, possible duplicates, short travel gaps,
          and missing shift details before confirming earnings.
        </p>
      </div>

      {shifts.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <p className="text-sm text-slate-600">
            No schedule loaded yet. Upload a CSV schedule to check for
            conflicts and missing details.
          </p>
          <Link
            to="/upload"
            className="mt-4 inline-flex rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
          >
            Upload Schedule
          </Link>
        </div>
      ) : isCalculationStale ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
          Schedule warnings are paused until the calculation service reconnects.
          Use the retry button above once the connection is restored.
        </div>
      ) : totalAlerts === 0 ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-8 text-center">
          <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-600" />
          <h2 className="mt-3 text-base font-semibold text-emerald-950">
            No active warnings or conflicts
          </h2>
          <p className="mt-1 text-sm text-emerald-800">
            All active shifts passed overlap, commute, duplicate, and detail
            checks.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Overlapping Shifts */}
          {overlaps.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-5 w-5 text-rose-600" />
                <h2 className="text-base font-semibold text-slate-900">
                  Overlapping Shifts ({overlaps.length})
                </h2>
              </div>

              {overlaps.map((c, idx) => {
                const a = shiftById.get(c.shift_a_id)
                const b = shiftById.get(c.shift_b_id)
                return (
                  <div
                    key={`${c.shift_a_id}-${c.shift_b_id}-${idx}`}
                    className="rounded-2xl border border-rose-200 bg-white p-4 shadow-xs"
                  >
                    <p className="text-sm font-semibold text-rose-900">
                      {c.message}
                    </p>
                    <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                      {[a, b].map(
                        (item) =>
                          item && (
                            <div
                              key={item.shift_id}
                              className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3"
                            >
                              <div>
                                <div className="text-xs font-semibold text-slate-900">
                                  {item.current.employer_name || 'Shift'} (Row #
                                  {item.line_no})
                                </div>
                                <div className="mt-0.5 text-xs text-slate-600">
                                  {formatDateDisplay(item.current.shift_date)} •{' '}
                                  <span className="font-mono">
                                    {item.current.start_time}–
                                    {item.current.end_time}
                                  </span>
                                </div>
                                <div className="text-xs text-slate-500">
                                  {item.current.location || 'Location missing'}
                                </div>
                              </div>
                              <div className="flex shrink-0 gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => setEditingShift(item)}
                                  className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setShiftConfirmation(
                                      item.shift_id,
                                      'rejected',
                                    )
                                  }
                                  className="rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                                >
                                  Reject
                                </button>
                              </div>
                            </div>
                          ),
                      )}
                    </div>
                  </div>
                )
              })}
            </section>
          )}

          {/* Possible Duplicates */}
          {duplicateShifts.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <Copy className="h-5 w-5 text-amber-600" />
                <h2 className="text-base font-semibold text-slate-900">
                  Possible Duplicate Shifts Held for Review (
                  {duplicateShifts.length})
                </h2>
              </div>
              <p className="text-xs text-slate-600">
                Possible duplicate entries are held out of earnings to prevent
                double counting. Rejecting the extra duplicate releases the
                matching valid shift for counting.
              </p>

              <div className="space-y-2.5">
                {duplicateShifts.map((item) => (
                  <div
                    key={item.shift_id}
                    className="rounded-2xl border border-amber-200 bg-white p-4"
                  >
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">
                          {item.current.employer_name || 'Shift'} —{' '}
                          {formatDateDisplay(item.current.shift_date)} (
                          {item.current.start_time}–{item.current.end_time})
                        </div>
                        <p className="mt-1 text-xs text-amber-900">
                          {item.calculated?.earnings_reason}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        <button
                          type="button"
                          onClick={() => setEditingShift(item)}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                        >
                          Review
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setShiftConfirmation(item.shift_id, 'rejected')
                          }
                          className="inline-flex items-center gap-1 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700"
                        >
                          <XCircle className="h-3.5 w-3.5" />
                          Reject Duplicate
                        </button>
                      </div>
                    </div>
                    <TechnicalDetailsDisclosure shift={item} />
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Insufficient Commute Gaps */}
          {commuteConflicts.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <Route className="h-5 w-5 text-amber-600" />
                <h2 className="text-base font-semibold text-slate-900">
                  Short Travel Gaps Between Locations ({commuteConflicts.length}
                  )
                </h2>
              </div>
              <p className="text-xs text-slate-600">
                Note: A gap under 30 minutes between different locations is a
                scheduling heuristic, not a verified travel-time estimate.
              </p>

              {commuteConflicts.map((c, idx) => {
                const a = shiftById.get(c.shift_a_id)
                const b = shiftById.get(c.shift_b_id)
                return (
                  <div
                    key={`${c.shift_a_id}-${c.shift_b_id}-${idx}`}
                    className="rounded-2xl border border-amber-200 bg-white p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-amber-950">
                        {c.message}
                      </span>
                      {c.gap_minutes !== null && (
                        <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-bold text-amber-900">
                          {c.gap_minutes} min gap
                        </span>
                      )}
                    </div>
                    <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {[a, b].map(
                        (item) =>
                          item && (
                            <div
                              key={item.shift_id}
                              className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
                            >
                              <div>
                                <div className="font-semibold text-slate-900">
                                  {item.current.location || 'Location missing'}
                                </div>
                                <div className="text-slate-600">
                                  {item.current.shift_date} •{' '}
                                  {item.current.start_time}–
                                  {item.current.end_time}
                                </div>
                              </div>
                              <button
                                type="button"
                                onClick={() => setEditingShift(item)}
                                className="font-semibold text-emerald-700 hover:underline"
                              >
                                Edit
                              </button>
                            </div>
                          ),
                      )}
                    </div>
                  </div>
                )
              })}
            </section>
          )}

          {/* Commute Not Assessed */}
          {commuteNotAssessed.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <MapPinOff className="h-5 w-5 text-slate-600" />
                <h2 className="text-base font-semibold text-slate-900">
                  Commute Feasibility Not Assessed ({commuteNotAssessed.length})
                </h2>
              </div>
              {commuteNotAssessed.map((item, idx) => {
                const a = shiftById.get(item.shift_a_id)
                const b = shiftById.get(item.shift_b_id)
                return (
                  <div
                    key={`${item.shift_a_id}-${item.shift_b_id}-${idx}`}
                    className="rounded-2xl border border-slate-200 bg-white p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-slate-900">
                        Not assessed — {item.message}
                      </span>
                      {item.gap_minutes !== null && (
                        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                          {item.gap_minutes} min gap
                        </span>
                      )}
                    </div>
                    <div className="mt-2.5 flex flex-wrap gap-2">
                      {[a, b].map(
                        (s) =>
                          s && (
                            <button
                              key={s.shift_id}
                              type="button"
                              onClick={() => setEditingShift(s)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
                            >
                              <Edit3 className="h-3.5 w-3.5" />
                              {s.current.employer_name || 'Shift'} (
                              {s.current.start_time}–{s.current.end_time}):{' '}
                              {s.current.location || 'Missing location'}
                            </button>
                          ),
                      )}
                    </div>
                  </div>
                )
              })}
            </section>
          )}

          {/* Shift Validation & Missing Field Warnings */}
          {detailIssueShifts.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-amber-600" />
                <h2 className="text-base font-semibold text-slate-900">
                  Shifts Requiring Attention ({detailIssueShifts.length})
                </h2>
              </div>

              <div className="space-y-2.5">
                {detailIssueShifts.map((shift) => {
                  const missingBreak = shift.current.break_minutes.trim() === ''
                  const requiresWorkerAssignment =
                    shift.is_ai_extracted &&
                    shift.ai_metadata?.worker_attribution_status ===
                      'ambiguous_or_unverified' &&
                    !shift.ai_metadata?.worker_assignment_confirmed_by_user
                  const canQuickConfirm =
                    shift.confirmation_status !== 'confirmed' &&
                    shift.calculated?.validation_status !== 'invalid' &&
                    !shift.calculated?.flags.some(
                      (f) => f.code === 'POSSIBLE_DUPLICATE',
                    )

                  return (
                    <div
                      key={shift.shift_id}
                      className="rounded-2xl border border-slate-200 bg-white p-4"
                    >
                      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                        <div className="space-y-2">
                          <div className="text-sm font-semibold text-slate-900">
                            {shift.current.employer_name ||
                              'Employer not listed'}{' '}
                            • {formatDateDisplay(shift.current.shift_date)} (
                            {shift.current.start_time || '??:??'}–
                            {shift.current.end_time || '??:??'})
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {shift.is_ai_extracted && (
                              <AiExtractionBadge
                                confidence={shift.ai_metadata?.confidence}
                                provider={shift.ai_metadata?.provider}
                              />
                            )}
                            {shift.ai_metadata?.worker_attribution_status && (
                              <WorkerAttributionBadge
                                status={
                                  shift.ai_metadata.worker_attribution_status
                                }
                                workerName={shift.ai_metadata.worker_name}
                              />
                            )}
                            {shift.calculated?.flags.map((flag, idx) => (
                              <FlagBadge
                                key={`${flag.code}-${idx}`}
                                flag={flag}
                              />
                            ))}
                          </div>
                          <ul className="space-y-1 text-xs text-slate-600">
                            {shift.calculated?.flags.map((flag, idx) => (
                              <li key={`${flag.code}-reason-${idx}`}>
                                • {flag.reason}
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="flex shrink-0 flex-wrap gap-2">
                          {missingBreak && (
                            <button
                              type="button"
                              onClick={() =>
                                updateShift(shift.shift_id, {
                                  break_minutes: '0',
                                })
                              }
                              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100"
                            >
                              <Clock className="h-3.5 w-3.5" />
                              Confirm 0 min break
                            </button>
                          )}
                          {canQuickConfirm &&
                            (requiresWorkerAssignment ? (
                              <button
                                type="button"
                                onClick={() =>
                                  confirmWorkerAssignment(shift.shift_id)
                                }
                                className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white hover:bg-amber-700"
                              >
                                <Check className="h-3.5 w-3.5" />
                                Assign to{' '}
                                {workers.find((w) => w.worker_id === workerId)
                                  ?.worker_name ?? 'Selected Worker'}
                              </button>
                            ) : (
                              <button
                                type="button"
                                onClick={() =>
                                  setShiftConfirmation(
                                    shift.shift_id,
                                    'confirmed',
                                  )
                                }
                                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
                              >
                                <Check className="h-3.5 w-3.5" />
                                Confirm Shift
                              </button>
                            ))}
                          <button
                            type="button"
                            onClick={() => setEditingShift(shift)}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                            Review &amp; Fix
                          </button>
                        </div>
                      </div>
                      <TechnicalDetailsDisclosure shift={shift} />
                    </div>
                  )
                })}
              </div>
            </section>
          )}
        </div>
      )}

      {editingShift && (
        <ShiftEditModal
          shift={editingShift}
          mode="edit"
          onClose={() => setEditingShift(null)}
          onSaveEdit={(shiftId, values, status) =>
            updateShift(shiftId, values, status)
          }
          onAddManual={addManualShift}
          onResetToExtracted={resetShiftToExtracted}
        />
      )}
    </div>
  )
}
