import { useMemo } from 'react'
import { AlertTriangle, Info, Wallet } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EarningsStatusBadge } from '../components/shifts/FlagBadge'
import { TechnicalDetailsDisclosure } from '../components/shifts/TechnicalDetailsDisclosure'
import { useSchedule } from '../context/scheduleContextStore'
import {
  formatCurrency,
  formatCurrencyWithCode,
  formatDateDisplay,
  formatHours,
  formatWeekRange,
} from '../utils/formatters'

export function EarningsPage() {
  const {
    shifts,
    weeklySummary,
    availableWeeks,
    selectedWeek,
    setSelectedWeek,
    isCalculationStale,
  } = useSchedule()

  const activeWeek = selectedWeek ?? availableWeeks[0] ?? null

  const weekSummaries = useMemo(() => {
    if (!activeWeek) return weeklySummary
    return weeklySummary.filter((w) => w.week_start === activeWeek)
  }, [weeklySummary, activeWeek])

  const weekShifts = useMemo(() => {
    return shifts.filter((s) => {
      if (s.confirmation_status === 'rejected') return false
      if (!activeWeek) return true
      return s.calculated?.week_start === activeWeek
    })
  }, [shifts, activeWeek])

  const rejectedShifts = useMemo(
    () => shifts.filter((s) => s.confirmation_status === 'rejected'),
    [shifts],
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Weekly Earnings
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Estimated gross earnings (before tax or deductions) calculated from
            your confirmed and validated shifts.
          </p>
        </div>

        {availableWeeks.length > 1 && (
          <select
            value={activeWeek ?? ''}
            onChange={(e) => setSelectedWeek(e.target.value || null)}
            aria-label="Select pay week"
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800"
          >
            {availableWeeks.map((w) => (
              <option key={w} value={w}>
                Week of {formatWeekRange(w)}
              </option>
            ))}
          </select>
        )}
      </div>

      {shifts.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <Wallet className="mx-auto h-10 w-10 text-slate-400" />
          <h2 className="mt-3 text-base font-semibold text-slate-900">
            No earnings data yet
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Upload a CSV schedule and confirm your shifts to see estimated
            weekly gross earnings.
          </p>
          <Link
            to="/upload"
            className="mt-4 inline-flex rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
          >
            Upload CSV Schedule
          </Link>
        </div>
      ) : isCalculationStale ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-900">
          Earnings cannot be displayed while the calculation service is
          unavailable or updating. Restore connection and retry above to view
          authoritative totals.
        </div>
      ) : (
        <>
          {/* Per-Currency Weekly Summary Cards (never mixed across currencies) */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {weekSummaries.map((ws) => {
              const allCancelledZero =
                ws.gross_earnings === 0 &&
                !ws.earnings_incomplete &&
                ws.cancelled_shifts > 0

              return (
                <section
                  key={`${ws.week_start}-${ws.currency ?? 'NONE'}`}
                  className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="inline-flex rounded-md bg-slate-900 px-2 py-0.5 font-mono text-xs font-semibold text-white">
                        {ws.currency ?? 'CURRENCY MISSING'}
                      </span>
                      <p className="mt-1.5 text-xs text-slate-500">
                        Week starting {formatWeekRange(ws.week_start)}
                      </p>
                    </div>
                    <span className="text-xs font-medium text-slate-500">
                      {ws.shifts} shift{ws.shifts === 1 ? '' : 's'}
                    </span>
                  </div>

                  <div className="mt-4">
                    <div className="text-xs font-medium text-slate-500">
                      Estimated gross earnings (before tax or deductions)
                    </div>
                    <div
                      className={`mt-1 text-3xl font-bold tracking-tight tabular-nums ${
                        ws.gross_earnings === null
                          ? 'text-amber-700'
                          : 'text-slate-900'
                      }`}
                    >
                      {formatCurrencyWithCode(ws.gross_earnings, ws.currency)}
                    </div>
                    {allCancelledZero && (
                      <p className="mt-1 text-xs font-medium text-slate-600">
                        Genuine zero total: all shifts in this group were
                        cancelled.
                      </p>
                    )}
                  </div>

                  {ws.earnings_incomplete && (
                    <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                      <div>
                        <span className="font-semibold">
                          Incomplete week total:
                        </span>{' '}
                        {ws.incomplete_shifts} incomplete shift(s) (
                        {formatHours(ws.incomplete_hours)}) and{' '}
                        {ws.pending_shifts} pending/unconfirmed shift(s) (
                        {formatHours(ws.pending_hours)}) are excluded until
                        confirmed and complete.
                      </div>
                    </div>
                  )}

                  <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 text-xs sm:grid-cols-4">
                    <div>
                      <dt className="text-slate-500">Eligible hours</dt>
                      <dd className="mt-0.5 font-bold text-slate-900 tabular-nums">
                        {formatHours(ws.paid_hours)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">Incomplete hrs</dt>
                      <dd className="mt-0.5 font-semibold text-amber-700 tabular-nums">
                        {formatHours(ws.incomplete_hours)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">Pending hrs</dt>
                      <dd className="mt-0.5 font-semibold text-slate-700 tabular-nums">
                        {formatHours(ws.pending_hours)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">Cancelled</dt>
                      <dd className="mt-0.5 font-semibold text-slate-700 tabular-nums">
                        {ws.cancelled_shifts}
                      </dd>
                    </div>
                  </dl>
                </section>
              )
            })}
          </div>

          {/* Calculation & Rounding Transparency */}
          <div className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-slate-100/70 p-4 text-xs text-slate-700">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
            <div className="space-y-1">
              <p className="font-semibold text-slate-900">
                How WorkClarity calculates &amp; rounds gross earnings
              </p>
              <p>
                Paid minutes = Shift duration minus unpaid break minutes.
                Estimated gross = (Paid minutes ÷ 60) × Confirmed hourly rate.
                Calculations use exact minutes without rounding intermediate
                paid hours. Weekly totals combine exact unrounded shift amounts
                and round to 2 decimal places at the final step, separated by
                currency. Overtime, taxes, and deductions are out of scope for
                the MVP.
              </p>
            </div>
          </div>

          {/* Per-Shift Breakdown */}
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs">
            <div className="border-b border-slate-200 px-5 py-3.5">
              <h2 className="text-sm font-semibold text-slate-900">
                Per-Shift Earnings Breakdown ({weekShifts.length} active shifts)
              </h2>
            </div>

            <div className="divide-y divide-slate-100">
              {weekShifts.map((shift) => {
                const calc = shift.calculated
                const cur = shift.current
                return (
                  <div
                    key={shift.shift_id}
                    className="px-5 py-4"
                  >
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">
                            {formatDateDisplay(cur.shift_date)} •{' '}
                            {cur.employer_name || 'Employer not listed'}
                          </span>
                          <EarningsStatusBadge status={calc?.earnings_status} />
                        </div>
                        <div className="text-xs text-slate-600">
                          {cur.start_time}–{cur.end_time} • Break:{' '}
                          {cur.break_minutes.trim() === ''
                            ? 'Not confirmed'
                            : `${cur.break_minutes} min`}{' '}
                          • Rate:{' '}
                          {cur.hourly_rate.trim() === ''
                            ? 'Missing'
                            : `${cur.hourly_rate} ${cur.currency || '(no currency)'}`}
                        </div>
                        {calc?.earnings_reason && (
                          <p className="text-xs font-medium text-amber-800">
                            {calc.earnings_reason}
                          </p>
                        )}
                      </div>

                      <div className="text-left sm:text-right">
                        <div
                          className={`text-base font-bold tabular-nums ${
                            calc?.gross_earnings === null
                              ? 'text-amber-700'
                              : 'text-slate-900'
                          }`}
                        >
                          {formatCurrency(
                            calc?.gross_earnings,
                            calc?.currency ?? cur.currency,
                          )}
                        </div>
                        <div className="text-xs text-slate-500 tabular-nums">
                          Paid: {formatHours(calc?.paid_hours)}
                        </div>
                      </div>
                    </div>
                    <TechnicalDetailsDisclosure shift={shift} />
                  </div>
                )
              })}
            </div>
          </section>

          {rejectedShifts.length > 0 && (
            <p className="text-xs text-slate-500">
              {rejectedShifts.length} rejected shift(s) are excluded from active
              totals and retained in{' '}
              <Link
                to="/review"
                className="font-semibold text-emerald-700 hover:underline"
              >
                Review &amp; Correct
              </Link>{' '}
              for traceability.
            </p>
          )}
        </>
      )}
    </div>
  )
}
