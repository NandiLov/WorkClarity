import { useMemo, useState } from 'react'
import { Calendar, Eye, EyeOff, MapPin, Moon } from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  ConfirmationBadge,
  EarningsStatusBadge,
  FlagBadge,
} from '../components/shifts/FlagBadge'
import { useSchedule } from '../context/scheduleContextStore'
import type { ShiftRecord } from '../types/shift'
import {
  formatCurrency,
  formatHours,
  formatShortDay,
  formatWeekRange,
  getWeekDates,
  isOvernightShift,
} from '../utils/formatters'

export function SchedulePage() {
  const {
    shifts,
    availableWeeks,
    selectedWeek,
    setSelectedWeek,
    isCalculationStale,
  } = useSchedule()

  const [showRejected, setShowRejected] = useState(false)

  const activeWeek = selectedWeek ?? availableWeeks[0] ?? null
  const weekDays = useMemo(
    () => (activeWeek ? getWeekDates(activeWeek) : []),
    [activeWeek],
  )

  const weekShifts = useMemo(() => {
    return shifts.filter((s) => {
      if (!showRejected && s.confirmation_status === 'rejected') {
        return false
      }
      if (!activeWeek) return true
      return s.calculated?.week_start === activeWeek
    })
  }, [shifts, showRejected, activeWeek])

  const shiftsByDay = useMemo(() => {
    const map = new Map<string, ShiftRecord[]>()
    for (const d of weekDays) {
      map.set(d, [])
    }
    for (const s of weekShifts) {
      const dateKey = s.calculated?.date ?? s.current.shift_date
      if (dateKey && map.has(dateKey)) {
        map.get(dateKey)?.push(s)
      }
    }
    for (const list of map.values()) {
      list.sort((a, b) =>
        a.current.start_time.localeCompare(b.current.start_time),
      )
    }
    return map
  }, [weekDays, weekShifts])

  const unplacedShifts = useMemo(() => {
    const daySet = new Set(weekDays)
    return shifts.filter((s) => {
      if (!showRejected && s.confirmation_status === 'rejected') return false
      const d = s.calculated?.date ?? s.current.shift_date
      return !d || (activeWeek && s.calculated?.week_start === null) || (weekDays.length > 0 && !daySet.has(d) && s.calculated?.week_start === activeWeek)
    })
  }, [shifts, showRejected, weekDays, activeWeek])

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Weekly Schedule
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Monday-to-Sunday reporting week view. Overnight shifts appear on the
            day and week in which they begin.
          </p>
        </div>

        {shifts.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            {availableWeeks.length > 1 && (
              <select
                value={activeWeek ?? ''}
                onChange={(e) => setSelectedWeek(e.target.value || null)}
                aria-label="Select reporting week"
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800"
              >
                {availableWeeks.map((w) => (
                  <option key={w} value={w}>
                    Week of {formatWeekRange(w)}
                  </option>
                ))}
              </select>
            )}

            <button
              type="button"
              onClick={() => setShowRejected((prev) => !prev)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              {showRejected ? (
                <EyeOff className="h-3.5 w-3.5" />
              ) : (
                <Eye className="h-3.5 w-3.5" />
              )}
              {showRejected ? 'Hide rejected' : 'Show rejected'}
            </button>
          </div>
        )}
      </div>

      {shifts.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <Calendar className="mx-auto h-10 w-10 text-slate-400" />
          <h2 className="mt-3 text-base font-semibold text-slate-900">
            No weekly schedule loaded
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Upload a CSV schedule to view your shifts grouped Monday through
            Sunday.
          </p>
          <Link
            to="/upload"
            className="mt-4 inline-flex rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
          >
            Upload CSV Schedule
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          {unplacedShifts.length > 0 && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50/70 p-4">
              <h2 className="text-sm font-semibold text-rose-900">
                Shifts Missing Valid Date ({unplacedShifts.length})
              </h2>
              <p className="mt-0.5 text-xs text-rose-800">
                These shifts have a blocking date error and cannot be placed on
                the calendar until repaired.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {unplacedShifts.map((s) => (
                  <Link
                    key={s.shift_id}
                    to="/review"
                    className="rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-800 hover:bg-rose-50"
                  >
                    Row #{s.line_no} •{' '}
                    {s.current.employer_name || 'Employer not listed'} (Fix in
                    Review →)
                  </Link>
                ))}
              </div>
            </div>
          )}

          {weekDays.map((isoDay) => {
            const { weekday, dayMonth } = formatShortDay(isoDay)
            const dayShifts = shiftsByDay.get(isoDay) ?? []

            return (
              <section
                key={isoDay}
                className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs"
              >
                <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/80 px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-slate-900">
                      {weekday}
                    </span>
                    <span className="text-xs font-medium text-slate-500">
                      {dayMonth}
                    </span>
                  </div>
                  <span className="text-xs font-medium text-slate-500">
                    {dayShifts.length === 0
                      ? 'Off'
                      : `${dayShifts.length} shift${dayShifts.length === 1 ? '' : 's'}`}
                  </span>
                </div>

                {dayShifts.length === 0 ? (
                  <div className="px-4 py-3 text-xs text-slate-400">
                    No shifts scheduled
                  </div>
                ) : (
                  <div className="divide-y divide-slate-100">
                    {dayShifts.map((shift) => {
                      const calc = shift.calculated
                      const cur = shift.current
                      const overnight = isOvernightShift(
                        cur.start_time,
                        cur.end_time,
                        cur.shift_date,
                        cur.end_date,
                      )
                      return (
                        <div
                          key={shift.shift_id}
                          className="flex flex-col justify-between gap-3 px-4 py-3.5 sm:flex-row sm:items-center"
                        >
                          <div className="space-y-1.5">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-sm font-bold text-slate-900">
                                {cur.start_time || '??:??'} –{' '}
                                {cur.end_time || '??:??'}
                              </span>
                              {overnight && (
                                <span className="inline-flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-800">
                                  <Moon className="h-3 w-3" />
                                  Overnight
                                  {cur.end_date
                                    ? ` (ends ${cur.end_date})`
                                    : ' (ends next day)'}
                                </span>
                              )}
                              <ConfirmationBadge
                                status={shift.confirmation_status}
                              />
                              <EarningsStatusBadge
                                status={calc?.earnings_status}
                                stale={isCalculationStale}
                              />
                            </div>

                            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
                              <span className="font-semibold text-slate-800">
                                {cur.employer_name || 'Unknown employer'}
                              </span>
                              <span className="inline-flex items-center gap-1">
                                <MapPin className="h-3.5 w-3.5 text-slate-400" />
                                {cur.location || 'Location missing'}
                              </span>
                              <span>
                                Break:{' '}
                                {cur.break_minutes.trim() === ''
                                  ? 'Unknown'
                                  : `${cur.break_minutes} min`}
                              </span>
                            </div>

                            {calc && calc.flags.length > 0 && (
                              <div className="flex flex-wrap gap-1 pt-0.5">
                                {calc.flags.map((f, i) => (
                                  <FlagBadge key={`${f.code}-${i}`} flag={f} />
                                ))}
                              </div>
                            )}
                          </div>

                          <div className="text-left sm:text-right">
                            <div
                              className={`text-sm font-bold tabular-nums ${
                                calc?.gross_earnings === null
                                  ? 'text-amber-700'
                                  : 'text-slate-900'
                              }`}
                            >
                              {isCalculationStale
                                ? 'Pending update'
                                : formatCurrency(
                                    calc?.gross_earnings,
                                    calc?.currency ?? cur.currency,
                                  )}
                            </div>
                            <div className="text-xs text-slate-500 tabular-nums">
                              {isCalculationStale
                                ? '—'
                                : formatHours(calc?.paid_hours)}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
