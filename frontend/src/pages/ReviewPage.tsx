import { useMemo, useState } from 'react'
import {
  Check,
  CheckCheck,
  Clock,
  Edit3,
  Moon,
  Plus,
  RotateCcw,
  Upload,
  XCircle,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { DiffPill } from '../components/shifts/DiffPill'
import {
  ConfirmationBadge,
  EarningsStatusBadge,
  FlagBadge,
} from '../components/shifts/FlagBadge'
import { ShiftEditModal } from '../components/shifts/ShiftEditModal'
import { TechnicalDetailsDisclosure } from '../components/shifts/TechnicalDetailsDisclosure'
import { useSchedule } from '../context/scheduleContextStore'
import type { ShiftRecord } from '../types/shift'
import {
  formatCurrency,
  formatDateDisplay,
  formatHours,
  isOvernightShift,
} from '../utils/formatters'

type ReviewFilter = 'attention' | 'counted' | 'cancelled' | 'rejected' | 'all'

export function ReviewPage() {
  const {
    shifts,
    isCalculationStale,
    updateShift,
    setShiftConfirmation,
    confirmReadyShifts,
    resetShiftToExtracted,
    addManualShift,
  } = useSchedule()

  const [filter, setFilter] = useState<ReviewFilter>('attention')
  const [editingShift, setEditingShift] = useState<ShiftRecord | null>(null)
  const [modalMode, setModalMode] = useState<'edit' | 'add' | null>(null)
  const [batchMessage, setBatchMessage] = useState<string | null>(null)

  const counts = useMemo(() => {
    let attention = 0
    let counted = 0
    let cancelled = 0
    let rejected = 0

    for (const s of shifts) {
      const es = s.calculated?.earnings_status
      if (es === 'counted') counted += 1
      else if (es === 'cancelled') cancelled += 1
      else if (es === 'rejected' || s.confirmation_status === 'rejected')
        rejected += 1
      else attention += 1
    }

    return {
      attention,
      counted,
      cancelled,
      rejected,
      all: shifts.length,
    }
  }, [shifts])

  const filteredShifts = useMemo(() => {
    return shifts.filter((s) => {
      const es = s.calculated?.earnings_status
      switch (filter) {
        case 'attention':
          if (!es) return s.confirmation_status !== 'rejected'
          return (
            es === 'unconfirmed' ||
            es === 'needs_review' ||
            es === 'incomplete' ||
            es === 'excluded'
          )
        case 'counted':
          return es === 'counted'
        case 'cancelled':
          return es === 'cancelled'
        case 'rejected':
          return es === 'rejected' || s.confirmation_status === 'rejected'
        case 'all':
          return true
      }
    })
  }, [shifts, filter])

  const handleConfirmReady = () => {
    const confirmedCount = confirmReadyShifts()
    if (confirmedCount > 0) {
      setBatchMessage(
        `Confirmed ${confirmedCount} ready shift(s) and sent to the backend for calculation.`,
      )
    } else {
      setBatchMessage(
        'No unconfirmed shifts were ready for one-tap confirmation (shifts with missing breaks/rates, errors, or duplicates must be reviewed individually).',
      )
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Review &amp; Correct Shifts
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Inspect extracted shift details, supply missing breaks or hourly
            rates, and confirm or reject shifts. Original CSV values are always
            preserved.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setEditingShift(null)
              setModalMode('add')
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-xs hover:bg-slate-50"
          >
            <Plus className="h-4 w-4" />
            Add Shift
          </button>
          {shifts.length > 0 && (
            <button
              type="button"
              onClick={handleConfirmReady}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-2 text-xs font-semibold text-white shadow-xs hover:bg-emerald-700"
            >
              <CheckCheck className="h-4 w-4" />
              Confirm Ready Shifts
            </button>
          )}
        </div>
      </div>

      {batchMessage && (
        <div className="flex items-center justify-between rounded-xl border border-teal-200 bg-teal-50 px-4 py-3 text-xs font-medium text-teal-900">
          <span>{batchMessage}</span>
          <button
            type="button"
            onClick={() => setBatchMessage(null)}
            className="ml-4 font-semibold underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {shifts.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <Upload className="mx-auto h-10 w-10 text-slate-400" />
          <h2 className="mt-3 text-base font-semibold text-slate-900">
            No shifts to review yet
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Upload a CSV schedule or load a synthetic demo schedule to review
            and validate your shifts.
          </p>
          <Link
            to="/upload"
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
          >
            Go to Upload Schedule
          </Link>
        </div>
      ) : (
        <>
          {/* Filter Tabs */}
          <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
            {(
              [
                {
                  id: 'attention',
                  label: 'Needs Attention',
                  count: counts.attention,
                },
                {
                  id: 'counted',
                  label: 'Confirmed & Counted',
                  count: counts.counted,
                },
                {
                  id: 'cancelled',
                  label: 'Cancelled',
                  count: counts.cancelled,
                },
                {
                  id: 'rejected',
                  label: 'Rejected',
                  count: counts.rejected,
                },
                { id: 'all', label: 'All Shifts', count: counts.all },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setFilter(tab.id)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  filter === tab.id
                    ? 'bg-slate-900 text-white'
                    : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                <span>{tab.label}</span>
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${
                    filter === tab.id
                      ? 'bg-slate-700 text-slate-100'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {tab.count}
                </span>
              </button>
            ))}
          </div>

          {filteredShifts.length === 0 ? (
            <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
              No shifts match this filter.
            </div>
          ) : (
            <div className="space-y-3">
              {filteredShifts.map((shift) => {
                const calc = shift.calculated
                const cur = shift.current
                const overnight = isOvernightShift(
                  cur.start_time,
                  cur.end_time,
                  cur.shift_date,
                  cur.end_date,
                )
                const missingBreak = cur.break_minutes.trim() === ''
                const missingRate = cur.hourly_rate.trim() === ''
                const missingCurrency = cur.currency.trim() === ''

                return (
                  <article
                    key={shift.shift_id}
                    className={`rounded-2xl border bg-white p-4 shadow-xs transition sm:p-5 ${
                      shift.confirmation_status === 'rejected'
                        ? 'border-slate-200 bg-slate-50/80 opacity-80'
                        : calc?.validation_status === 'invalid'
                          ? 'border-rose-200'
                          : 'border-slate-200'
                    }`}
                  >
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      {/* Left details */}
                      <div className="min-w-0 flex-1 space-y-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-bold text-slate-900">
                            {cur.employer_name || 'Shift'}
                          </span>
                          <ConfirmationBadge
                            status={shift.confirmation_status}
                          />
                          <EarningsStatusBadge
                            status={calc?.earnings_status}
                            stale={isCalculationStale}
                          />
                          {overnight && (
                            <span className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-800">
                              <Moon className="h-3 w-3" />
                              Overnight
                              {cur.end_date ? ` → ${cur.end_date}` : ' (+1 day)'}
                            </span>
                          )}
                          <DiffPill
                            extracted={shift.extracted}
                            current={shift.current}
                            compact
                          />
                        </div>

                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-4">
                          <div>
                            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                              Date &amp; Time
                            </div>
                            <div className="mt-0.5 text-sm font-semibold text-slate-900">
                              {formatDateDisplay(cur.shift_date)}
                            </div>
                            <div className="font-mono text-xs text-slate-600">
                              {cur.start_time || '??:??'} –{' '}
                              {cur.end_time || '??:??'}
                            </div>
                          </div>

                          <div>
                            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                              Employer &amp; Location
                            </div>
                            <div className="mt-0.5 text-sm font-semibold text-slate-900">
                              {cur.employer_name || (
                                <span className="text-amber-700">
                                  Missing employer
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-slate-600">
                              {cur.location || (
                                <span className="text-amber-700">
                                  Missing location
                                </span>
                              )}
                            </div>
                          </div>

                          <div>
                            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                              Unpaid Break &amp; Paid Hours
                            </div>
                            <div className="mt-0.5 text-sm font-medium text-slate-900">
                              {missingBreak ? (
                                <span className="font-semibold text-amber-700">
                                  Break not confirmed
                                </span>
                              ) : (
                                `${cur.break_minutes} min break`
                              )}
                            </div>
                            <div className="text-xs text-slate-600">
                              Paid:{' '}
                              <span className="font-semibold tabular-nums">
                                {isCalculationStale
                                  ? '—'
                                  : formatHours(calc?.paid_hours)}
                              </span>
                            </div>
                          </div>

                          <div>
                            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                              Rate &amp; Est. Gross
                            </div>
                            <div className="mt-0.5 text-sm font-medium text-slate-900">
                              {missingRate ? (
                                <span className="font-semibold text-amber-700">
                                  Missing rate
                                </span>
                              ) : missingCurrency ? (
                                <span className="font-semibold text-amber-700">
                                  {cur.hourly_rate} (missing currency)
                                </span>
                              ) : (
                                `${cur.hourly_rate}/hr ${cur.currency}`
                              )}
                            </div>
                            <div
                              className={`text-xs font-bold tabular-nums ${
                                calc?.gross_earnings === null
                                  ? 'text-amber-700'
                                  : 'text-emerald-700'
                              }`}
                            >
                              {isCalculationStale
                                ? 'Pending update'
                                : formatCurrency(
                                    calc?.gross_earnings,
                                    calc?.currency ?? cur.currency,
                                  )}
                            </div>
                          </div>
                        </div>

                        {/* Flags and Plain-Language Explanations */}
                        {calc && calc.flags.length > 0 && (
                          <div className="space-y-1.5 pt-1">
                            <div className="flex flex-wrap gap-1.5">
                              {calc.flags.map((flag, idx) => (
                                <FlagBadge
                                  key={`${flag.code}-${idx}`}
                                  flag={flag}
                                />
                              ))}
                            </div>
                            {calc.earnings_reason && (
                              <p className="text-xs text-slate-600">
                                {calc.earnings_reason}
                              </p>
                            )}
                          </div>
                        )}

                        <DiffPill
                          extracted={shift.extracted}
                          current={shift.current}
                          onReset={() => resetShiftToExtracted(shift.shift_id)}
                        />

                        <TechnicalDetailsDisclosure shift={shift} />
                      </div>

                      {/* Right Actions */}
                      <div className="flex shrink-0 flex-wrap items-center gap-2 lg:flex-col lg:items-stretch">
                        {missingBreak &&
                          shift.confirmation_status !== 'rejected' && (
                            <button
                              type="button"
                              onClick={() =>
                                updateShift(shift.shift_id, {
                                  break_minutes: '0',
                                })
                              }
                              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100"
                            >
                              <Clock className="h-3.5 w-3.5" />
                              Confirm 0 min break
                            </button>
                          )}

                        <button
                          type="button"
                          onClick={() => {
                            setEditingShift(shift)
                            setModalMode('edit')
                          }}
                          className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                          Edit Details
                        </button>

                        {shift.confirmation_status !== 'confirmed' &&
                          shift.confirmation_status !== 'rejected' && (
                            <button
                              type="button"
                              onClick={() =>
                                setShiftConfirmation(
                                  shift.shift_id,
                                  'confirmed',
                                )
                              }
                              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
                            >
                              <Check className="h-3.5 w-3.5" />
                              Confirm Shift
                            </button>
                          )}

                        {shift.confirmation_status !== 'rejected' ? (
                          <button
                            type="button"
                            onClick={() =>
                              setShiftConfirmation(shift.shift_id, 'rejected')
                            }
                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700"
                          >
                            <XCircle className="h-3.5 w-3.5" />
                            Reject
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() =>
                              setShiftConfirmation(
                                shift.shift_id,
                                'unconfirmed',
                              )
                            }
                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            Restore to Review
                          </button>
                        )}
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          )}
        </>
      )}

      {modalMode && (
        <ShiftEditModal
          shift={editingShift}
          mode={modalMode}
          onClose={() => {
            setModalMode(null)
            setEditingShift(null)
          }}
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
