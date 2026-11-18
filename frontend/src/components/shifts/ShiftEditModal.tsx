import { useState, type FormEvent } from 'react'
import { AlertTriangle, RotateCcw, X } from 'lucide-react'
import type {
  ConfirmationStatus,
  EditableShiftValues,
  ShiftRecord,
  ShiftStatus,
} from '../../types/shift'
import { createBlankEditableShiftValues } from '../../utils/csvParser'
import { getChangedFields } from '../../utils/formatters'

interface ShiftEditModalProps {
  shift: ShiftRecord | null
  mode: 'edit' | 'add'
  onClose: () => void
  onSaveEdit: (
    shiftId: string,
    values: EditableShiftValues,
    confirmationStatus: ConfirmationStatus,
  ) => void
  onAddManual: (values: EditableShiftValues) => void
  onResetToExtracted?: (shiftId: string) => void
}

export function ShiftEditModal({
  shift,
  mode,
  onClose,
  onSaveEdit,
  onAddManual,
  onResetToExtracted,
}: ShiftEditModalProps) {
  const [form, setForm] = useState<EditableShiftValues>(() =>
    shift ? { ...shift.current } : createBlankEditableShiftValues(),
  )
  const [confirmationStatus, setConfirmationStatus] =
    useState<ConfirmationStatus>(shift?.confirmation_status ?? 'unconfirmed')
  const [confirmationManuallySet, setConfirmationManuallySet] = useState(false)

  if (mode === 'edit' && !shift) {
    return null
  }

  const diffsFromExtracted = shift ? getChangedFields(shift.extracted, form) : []
  const editsFromCurrent = shift ? getChangedFields(shift.current, form) : []
  const requiresRenewedConfirmation =
    mode === 'edit' &&
    shift?.confirmation_status === 'confirmed' &&
    editsFromCurrent.length > 0

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'add') {
      onAddManual(form)
      onClose()
      return
    }
    if (shift) {
      onSaveEdit(shift.shift_id, form, confirmationStatus)
      onClose()
    }
  }

  const setField = <K extends keyof EditableShiftValues>(
    field: K,
    value: EditableShiftValues[K],
  ) => {
    setForm((prev) => {
      const next = { ...prev, [field]: value }
      if (
        mode === 'edit' &&
        shift?.confirmation_status === 'confirmed' &&
        !confirmationManuallySet
      ) {
        const hasEdits = getChangedFields(shift.current, next).length > 0
        setConfirmationStatus(hasEdits ? 'unconfirmed' : 'confirmed')
      }
      return next
    })
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/60 p-0 backdrop-blur-[1px] sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shift-modal-title"
    >
      <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
          <div>
            <h2
              id="shift-modal-title"
              className="text-lg font-semibold text-slate-900"
            >
              {mode === 'add' ? 'Add Shift Manually' : 'Review & Edit Shift'}
            </h2>
            {shift && (
              <p className="text-xs text-slate-500">
                Original uploaded values are preserved separately for comparison
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close shift editor"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 p-5">
          {requiresRenewedConfirmation && (
            <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <span>
                You edited a previously confirmed shift. Saving without
                re-confirming resets its status to <strong>Unconfirmed</strong>{' '}
                until you review and confirm the updated pay and hours, or click{' '}
                <strong>Save &amp; Confirm</strong> to confirm immediately.
              </span>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="edit-shift-date"
                className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                Shift start date (YYYY-MM-DD)
              </label>
              <input
                id="edit-shift-date"
                type="date"
                value={form.shift_date}
                onChange={(e) => setField('shift_date', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              />
              {shift && shift.extracted.shift_date !== form.shift_date && (
                <p className="mt-1 text-[11px] text-teal-700">
                  Original: {shift.extracted.shift_date || '(empty)'}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="edit-end-date"
                className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                End date (optional, overnight)
              </label>
              <input
                id="edit-end-date"
                type="date"
                value={form.end_date}
                onChange={(e) => setField('end_date', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              />
              <p className="mt-1 text-[11px] text-slate-500">
                Leave blank unless explicit next-day date is needed.
              </p>
            </div>

            <div>
              <label
                htmlFor="edit-start-time"
                className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                Start time (24h HH:MM)
              </label>
              <input
                id="edit-start-time"
                type="text"
                placeholder="09:00"
                value={form.start_time}
                onChange={(e) => setField('start_time', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              />
              {shift && shift.extracted.start_time !== form.start_time && (
                <p className="mt-1 text-[11px] text-teal-700">
                  Original: {shift.extracted.start_time || '(empty)'}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="edit-end-time"
                className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                End time (24h HH:MM)
              </label>
              <input
                id="edit-end-time"
                type="text"
                placeholder="17:00"
                value={form.end_time}
                onChange={(e) => setField('end_time', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              />
              {shift && shift.extracted.end_time !== form.end_time && (
                <p className="mt-1 text-[11px] text-teal-700">
                  Original: {shift.extracted.end_time || '(empty)'}
                </p>
              )}
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label
                  htmlFor="edit-break-minutes"
                  className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
                >
                  Unpaid break (minutes)
                </label>
                <button
                  type="button"
                  onClick={() => setField('break_minutes', '0')}
                  className="text-[11px] font-semibold text-emerald-700 hover:text-emerald-800 hover:underline"
                >
                  Set 0 min (no break)
                </button>
              </div>
              <input
                id="edit-break-minutes"
                type="text"
                inputMode="numeric"
                placeholder="Leave blank if unknown"
                value={form.break_minutes}
                onChange={(e) => setField('break_minutes', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              />
              <p className="mt-1 text-[11px] text-slate-500">
                Blank break is never treated as 0; enter 0 to confirm no break.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label
                  htmlFor="edit-hourly-rate"
                  className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
                >
                  Hourly rate
                </label>
                <input
                  id="edit-hourly-rate"
                  type="text"
                  inputMode="decimal"
                  placeholder="e.g. 16.00"
                  value={form.hourly_rate}
                  onChange={(e) => setField('hourly_rate', e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
                />
              </div>
              <div>
                <label
                  htmlFor="edit-currency"
                  className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
                >
                  Currency
                </label>
                <input
                  id="edit-currency"
                  type="text"
                  placeholder="USD"
                  value={form.currency}
                  onChange={(e) =>
                    setField('currency', e.target.value.toUpperCase())
                  }
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 uppercase text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="edit-employer"
                className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                Employer
              </label>
              <input
                id="edit-employer"
                type="text"
                placeholder="Employer name"
                value={form.employer_name}
                onChange={(e) => setField('employer_name', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              />
            </div>

            <div>
              <label
                htmlFor="edit-location"
                className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                Work location
              </label>
              <input
                id="edit-location"
                type="text"
                placeholder="e.g. Store A"
                value={form.location}
                onChange={(e) => setField('location', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              />
            </div>

            <div>
              <label
                htmlFor="edit-shift-status"
                className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                Shift status
              </label>
              <select
                id="edit-shift-status"
                value={form.shift_status}
                onChange={(e) =>
                  setField('shift_status', e.target.value as ShiftStatus)
                }
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
              >
                <option value="scheduled">Scheduled</option>
                <option value="changed">Changed</option>
                <option value="cancelled">Cancelled (unworked)</option>
              </select>
            </div>

            {mode === 'edit' && (
              <div>
                <label
                  htmlFor="edit-confirmation-status"
                  className="block text-xs font-semibold uppercase tracking-wide text-slate-600"
                >
                  Confirmation decision
                </label>
                <select
                  id="edit-confirmation-status"
                  value={confirmationStatus}
                  onChange={(e) => {
                    setConfirmationManuallySet(true)
                    setConfirmationStatus(e.target.value as ConfirmationStatus)
                  }}
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 focus:outline-none"
                >
                  <option value="confirmed">Confirmed</option>
                  <option value="unconfirmed">Unconfirmed</option>
                  <option value="needs_review">Needs review</option>
                  <option value="rejected">Rejected</option>
                </select>
              </div>
            )}
          </div>

          {shift && (
            <details className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              <summary className="cursor-pointer font-semibold text-slate-700 select-none">
                Technical details (shift identifier &amp; original CSV row)
              </summary>
              <div className="mt-2 space-y-1.5 border-t border-slate-200 pt-2">
                <div className="text-[11px]">
                  <span className="font-semibold text-slate-700">Shift ID:</span>{' '}
                  <span className="font-mono">{shift.shift_id}</span>
                </div>
                <code className="block overflow-x-auto whitespace-nowrap font-mono text-[11px] text-slate-700">
                  {shift.source_line}
                </code>
                {diffsFromExtracted.length > 0 && (
                  <p className="text-teal-800">
                    {diffsFromExtracted.length} modification(s) from original
                    uploaded values.
                  </p>
                )}
              </div>
            </details>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
            <div>
              {mode === 'edit' && shift && onResetToExtracted && (
                <button
                  type="button"
                  onClick={() => {
                    onResetToExtracted(shift.shift_id)
                    onClose()
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  <RotateCcw className="h-4 w-4" />
                  Restore original values
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              {mode === 'edit' ? (
                <>
                  <button
                    type="submit"
                    className="rounded-lg border border-slate-300 bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
                  >
                    Save Changes
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (shift) {
                        onSaveEdit(shift.shift_id, form, 'confirmed')
                        onClose()
                      }
                    }}
                    className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
                  >
                    Save &amp; Confirm
                  </button>
                </>
              ) : (
                <button
                  type="submit"
                  className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
                >
                  Add Shift
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
