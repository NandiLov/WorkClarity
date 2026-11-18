import { PencilLine, RotateCcw } from 'lucide-react'
import type { EditableShiftValues } from '../../types/shift'
import { getChangedFields } from '../../utils/formatters'

interface DiffPillProps {
  extracted: EditableShiftValues
  previousCurrent?: EditableShiftValues
  current: EditableShiftValues
  onReset?: () => void
  compact?: boolean
}

export function DiffPill({
  extracted,
  previousCurrent,
  current,
  onReset,
  compact = false,
}: DiffPillProps) {
  const diffs = getChangedFields(extracted, current)
  if (diffs.length === 0) {
    return null
  }

  if (compact) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md border border-teal-200 bg-teal-50 px-2 py-0.5 text-xs font-medium text-teal-800"
        title={diffs
          .map((d) => `${d.label}: ${d.originalValue} → ${d.currentValue}`)
          .join('\n')}
      >
        <PencilLine className="h-3 w-3" />
        Edited ({diffs.length})
      </span>
    )
  }

  return (
    <div className="mt-2 rounded-lg border border-teal-200/80 bg-teal-50/60 p-2.5 text-xs text-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-semibold text-teal-900">
          <PencilLine className="h-3.5 w-3.5 text-teal-700" />
          Worker edits preserved separately from extracted CSV
        </span>
        {onReset && (
          <button
            type="button"
            onClick={onReset}
            className="inline-flex items-center gap-1 rounded border border-teal-300 bg-white px-2 py-0.5 text-[11px] font-medium text-teal-800 hover:bg-teal-50"
          >
            <RotateCcw className="h-3 w-3" />
            Reset to original
          </button>
        )}
      </div>
      <ul className="mt-1.5 space-y-1">
        {diffs.map((diff) => {
          const prevRaw = previousCurrent
            ? (previousCurrent[diff.field] ?? '').trim() || '(empty)'
            : null
          const showPreviousStep =
            prevRaw !== null &&
            prevRaw !== diff.originalValue &&
            prevRaw !== diff.currentValue

          return (
            <li
              key={diff.field}
              className="flex flex-wrap items-center gap-1.5"
            >
              <span className="font-medium text-slate-600">{diff.label}:</span>
              <span className="rounded bg-slate-200/70 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 line-through">
                {diff.originalValue}
              </span>
              {showPreviousStep && (
                <>
                  <span className="text-slate-400">→</span>
                  <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[11px] text-amber-900 line-through">
                    {prevRaw}
                  </span>
                </>
              )}
              <span className="text-slate-400">→</span>
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-emerald-900">
                {diff.currentValue}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
