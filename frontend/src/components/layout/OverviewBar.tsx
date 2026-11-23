import {
  AlertCircle,
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  RefreshCw,
  Wallet,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useSchedule } from '../../context/scheduleContextStore'
import { formatCurrencyWithCode, formatHours, formatWeekRange } from '../../utils/formatters'

export function OverviewBar() {
  const {
    workerId,
    workers,
    shifts,
    weeklySummary,
    availableWeeks,
    selectedWeek,
    setSelectedWeek,
    isRecalculating,
    isCalculationStale,
    calculationError,
    reviewQueueCount,
    scheduleAlertsCount,
    flaggedShiftsCount,
    warningsCount,
    retryCalculation,
  } = useSchedule()

  const activeWorker = workers.find((w) => w.worker_id === workerId)
  const activeWeek = selectedWeek ?? availableWeeks[0] ?? null
  const weekSummaries = activeWeek
    ? weeklySummary.filter((w) => w.week_start === activeWeek)
    : weeklySummary

  const totalEligibleHours = weekSummaries.reduce(
    (sum, w) => sum + w.paid_hours,
    0,
  )

  if (isCalculationStale && calculationError) {
    return (
      <section
        aria-label="Calculation error alert"
        className="border-b border-rose-200 bg-rose-50 px-4 py-3.5 sm:px-6"
      >
        <div className="mx-auto flex max-w-6xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
            <div>
              <h2 className="text-sm font-semibold text-rose-950">
                Calculation service unavailable — earnings have not been
                recalculated
              </h2>
              <p className="mt-0.5 text-xs text-rose-800">
                {calculationError} Previous totals are hidden so outdated
                numbers are never shown as current.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={retryCalculation}
            className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg bg-rose-700 px-3.5 py-2 text-xs font-semibold text-white shadow-xs hover:bg-rose-800"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Retry recalculation
          </button>
        </div>
      </section>
    )
  }

  return (
    <section
      aria-label="Worker schedule overview"
      className="border-b border-slate-200 bg-white px-4 py-4 sm:px-6"
    >
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Schedule Overview
              </span>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-800">
                {activeWorker?.worker_name}
              </span>
              {isRecalculating && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-teal-700">
                  <RefreshCw className="h-3 w-3 animate-spin" />
                  Updating earnings…
                </span>
              )}
            </div>
          </div>

          {availableWeeks.length > 0 && (
            <div className="flex items-center gap-2">
              <label
                htmlFor="overview-week-select"
                className="flex items-center gap-1.5 text-xs font-medium text-slate-600"
              >
                <CalendarDays className="h-3.5 w-3.5 text-slate-400" />
                Pay week (Mon):
              </label>
              <select
                id="overview-week-select"
                value={activeWeek ?? ''}
                onChange={(e) => setSelectedWeek(e.target.value || null)}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-800 focus:border-emerald-600 focus:outline-none"
              >
                {availableWeeks.map((wk) => (
                  <option key={wk} value={wk}>
                    {formatWeekRange(wk)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {shifts.length === 0 ? (
          <div className="mt-3 flex flex-col items-start justify-between gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50/70 p-3.5 sm:flex-row sm:items-center">
            <p className="text-sm text-slate-600">
              No shifts loaded yet for{' '}
              <span className="font-semibold text-slate-900">
                {activeWorker?.worker_name}
              </span>
              . Upload a CSV schedule or load a synthetic demo scenario to start.
            </p>
            <Link
              to="/upload"
              className="inline-flex shrink-0 items-center rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
            >
              Upload Schedule
            </Link>
          </div>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {/* Estimated Gross Earnings per currency */}
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3.5">
              <div className="flex items-center justify-between text-xs font-medium text-slate-500">
                <span>Estimated Gross (Week)</span>
                <Wallet className="h-4 w-4 text-emerald-600" />
              </div>
              {isCalculationStale ? (
                <p className="mt-1.5 text-sm font-semibold text-slate-500">
                  Recalculating…
                </p>
              ) : weekSummaries.length === 0 ? (
                <p className="mt-1.5 text-base font-bold text-slate-700">
                  Not counted yet
                </p>
              ) : (
                <div className="mt-1 space-y-0.5">
                  {weekSummaries.map((ws) => (
                    <div
                      key={`${ws.week_start}-${ws.currency ?? 'NONE'}`}
                      className="flex items-baseline justify-between gap-2"
                    >
                      <span
                        className={`text-lg font-bold tabular-nums ${
                          ws.gross_earnings === null
                            ? 'text-amber-700'
                            : 'text-slate-900'
                        }`}
                      >
                        {formatCurrencyWithCode(ws.gross_earnings, ws.currency)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-1 text-[11px] text-slate-500">
                Before tax &amp; deductions
              </p>
            </div>

            {/* Eligible Paid Hours */}
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3.5">
              <div className="flex items-center justify-between text-xs font-medium text-slate-500">
                <span>Eligible Paid Hours</span>
                <CheckCircle2 className="h-4 w-4 text-teal-600" />
              </div>
              <p className="mt-1.5 text-lg font-bold tabular-nums text-slate-900">
                {isCalculationStale ? '—' : formatHours(totalEligibleHours)}
              </p>
              <p className="mt-1 text-[11px] text-slate-500">
                Confirmed &amp; valid shifts only
              </p>
            </div>

            {/* Review Queue */}
            <Link
              to="/review"
              className="group rounded-xl border border-slate-200 bg-slate-50/60 p-3.5 transition hover:border-emerald-300 hover:bg-emerald-50/30"
            >
              <div className="flex items-center justify-between text-xs font-medium text-slate-500">
                <span>Review Queue</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                    reviewQueueCount > 0
                      ? 'bg-amber-100 text-amber-800'
                      : 'bg-emerald-100 text-emerald-800'
                  }`}
                >
                  {reviewQueueCount > 0 ? 'Action needed' : 'Clear'}
                </span>
              </div>
              <p className="mt-1.5 text-lg font-bold tabular-nums text-slate-900">
                {reviewQueueCount}{' '}
                <span className="text-xs font-normal text-slate-500">
                  shift{reviewQueueCount === 1 ? '' : 's'} awaiting action
                </span>
              </p>
              <p className="mt-1 text-[11px] font-medium text-emerald-700 group-hover:underline">
                Review &amp; confirm shifts →
              </p>
            </Link>

            {/* Warnings & Conflicts */}
            <Link
              to="/warnings"
              className="group rounded-xl border border-slate-200 bg-slate-50/60 p-3.5 transition hover:border-amber-300 hover:bg-amber-50/30"
            >
              <div className="flex items-center justify-between text-xs font-medium text-slate-500">
                <span>Warnings &amp; Conflicts</span>
                <AlertTriangle
                  className={`h-4 w-4 ${
                    !isCalculationStale && warningsCount > 0
                      ? 'text-rose-600'
                      : 'text-slate-400'
                  }`}
                />
              </div>
              <p
                className={`mt-1.5 text-lg font-bold tabular-nums ${
                  !isCalculationStale && warningsCount > 0
                    ? 'text-rose-700'
                    : 'text-slate-900'
                }`}
              >
                {isCalculationStale ? '—' : warningsCount}{' '}
                <span className="text-xs font-normal text-slate-500">
                  total attention item
                  {!isCalculationStale && warningsCount === 1 ? '' : 's'}
                </span>
              </p>
              <div className="mt-1 space-y-0.5 text-[11px] text-slate-600">
                <p>
                  <span className="font-semibold tabular-nums text-slate-800">
                    {isCalculationStale ? '—' : scheduleAlertsCount}
                  </span>{' '}
                  scheduling &amp; commute alert
                  {!isCalculationStale && scheduleAlertsCount === 1 ? '' : 's'}
                </p>
                <p>
                  <span className="font-semibold tabular-nums text-slate-800">
                    {isCalculationStale ? '—' : flaggedShiftsCount}
                  </span>{' '}
                  shift
                  {!isCalculationStale && flaggedShiftsCount === 1 ? '' : 's'}{' '}
                  requiring attention
                </p>
              </div>
              <p className="mt-1 text-[11px] font-medium text-slate-600 group-hover:underline">
                Inspect warnings &amp; conflicts →
              </p>
            </Link>
          </div>
        )}
      </div>
    </section>
  )
}
