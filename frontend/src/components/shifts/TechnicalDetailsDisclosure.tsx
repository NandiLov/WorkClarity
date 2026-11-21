import { ChevronDown } from 'lucide-react'
import type { ShiftRecord } from '../../types/shift'

export function TechnicalDetailsDisclosure({
  shift,
}: {
  shift: ShiftRecord
}) {
  const flags = shift.calculated?.flags ?? []

  return (
    <details className="group mt-2 min-w-0 max-w-full overflow-hidden rounded-lg border border-slate-200/80 bg-slate-50/70 px-3 py-1.5 text-xs text-slate-600">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 font-medium text-slate-500 select-none hover:text-slate-800">
        <span>Technical details</span>
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 space-y-1.5 border-t border-slate-200/70 pt-2 text-[11px]">
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <span>
            <strong className="text-slate-700">Shift ID:</strong>{' '}
            <code className="font-mono text-slate-700">{shift.shift_id}</code>
          </span>
          <span>
            <strong className="text-slate-700">Schedule batch:</strong>{' '}
            <code className="font-mono text-slate-700">
              {shift.schedule_id}
            </code>
          </span>
          <span>
            <strong className="text-slate-700">Row:</strong> #{shift.line_no}
          </span>
        </div>

        {flags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <strong className="text-slate-700">Rule codes:</strong>
            {flags.map((f, idx) => (
              <code
                key={`${f.code}-${idx}`}
                className="rounded bg-slate-200/70 px-1.5 py-0.5 font-mono text-[10px] text-slate-700"
              >
                {f.flag_type_id}:{f.code}
              </code>
            ))}
          </div>
        )}

        {shift.is_ai_extracted && shift.ai_metadata && (
          <div className="space-y-1 rounded bg-indigo-50/60 p-2 text-indigo-950">
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <span>
                <strong>AI Provider:</strong>{' '}
                {shift.ai_metadata.provider || 'AI'}{' '}
                {shift.ai_metadata.model_id ? `(${shift.ai_metadata.model_id})` : ''}
              </span>
              <span>
                <strong>Confidence:</strong>{' '}
                <span className="capitalize">{shift.ai_metadata.confidence}</span>
              </span>
              {shift.ai_metadata.source_page && (
                <span>
                  <strong>Page:</strong> #{shift.ai_metadata.source_page}
                </span>
              )}
            </div>
            {shift.ai_metadata.uncertain_fields.length > 0 && (
              <div>
                <strong>Uncertain Fields:</strong>{' '}
                {shift.ai_metadata.uncertain_fields.join(', ')}
              </div>
            )}
            {shift.ai_metadata.review_reasons.length > 0 && (
              <div>
                <strong>Review Reasons:</strong>{' '}
                {shift.ai_metadata.review_reasons.join('; ')}
              </div>
            )}
          </div>
        )}

        <div>
          <strong className="text-slate-700">
            {shift.is_ai_extracted ? 'Original Extracted Data:' : 'Original CSV row:'}
          </strong>
          <code className="mt-0.5 block overflow-x-auto rounded bg-white px-2 py-1 font-mono text-[10px] whitespace-nowrap text-slate-700 ring-1 ring-slate-200">
            {shift.source_line}
          </code>
        </div>
      </div>
    </details>
  )
}
