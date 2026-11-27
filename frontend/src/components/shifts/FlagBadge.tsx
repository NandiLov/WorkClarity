import {
  AlertCircle,
  AlertTriangle,
  Ban,
  Bot,
  CheckCircle2,
  Clock,
  Copy,
  Info,
  UserCheck,
} from 'lucide-react'
import type {
  ConfirmationStatus,
  EarningsStatus,
  ExtractionConfidence,
  ShiftFlag,
  WorkerAttributionStatus,
} from '../../types/shift'
import { getFriendlyFlagLabel } from '../../utils/formatters'

export function EarningsStatusBadge({
  status,
  stale = false,
}: {
  status: EarningsStatus | undefined
  stale?: boolean
}) {
  if (stale || !status) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
        <Clock className="h-3 w-3" />
        Pending check
      </span>
    )
  }

  switch (status) {
    case 'counted':
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
          Counted in earnings
        </span>
      )
    case 'incomplete':
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
          Missing pay info
        </span>
      )
    case 'excluded':
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2.5 py-0.5 text-xs font-semibold text-rose-800">
          <AlertCircle className="h-3.5 w-3.5 text-rose-600" />
          Needs fix to count
        </span>
      )
    case 'needs_review':
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
          Needs review
        </span>
      )
    case 'unconfirmed':
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
          <Clock className="h-3.5 w-3.5 text-slate-500" />
          Awaiting confirmation
        </span>
      )
    case 'cancelled':
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
          <Ban className="h-3.5 w-3.5 text-slate-500" />
          Cancelled
        </span>
      )
    case 'rejected':
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500 line-through">
          <Ban className="h-3.5 w-3.5 text-slate-400" />
          Removed
        </span>
      )
  }
}

export function ConfirmationBadge({ status }: { status: ConfirmationStatus }) {
  switch (status) {
    case 'confirmed':
      return (
        <span className="inline-flex items-center gap-1 rounded-md bg-teal-50 px-2 py-0.5 text-xs font-medium text-teal-800 ring-1 ring-teal-600/20">
          Confirmed
        </span>
      )
    case 'needs_review':
      return (
        <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-600/20">
          Held for review
        </span>
      )
    case 'rejected':
      return (
        <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-slate-300">
          Rejected
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-300">
          Unconfirmed
        </span>
      )
  }
}

export function FlagBadge({ flag }: { flag: ShiftFlag }) {
  const isDuplicate = flag.code === 'POSSIBLE_DUPLICATE'
  const friendlyLabel = getFriendlyFlagLabel(flag.code)

  if (flag.severity === 'error') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-800">
        <AlertCircle className="h-3 w-3 shrink-0 text-rose-600" />
        <span>{friendlyLabel}</span>
      </span>
    )
  }
  if (flag.severity === 'warning') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
        {isDuplicate ? (
          <Copy className="h-3 w-3 shrink-0 text-amber-600" />
        ) : (
          <AlertTriangle className="h-3 w-3 shrink-0 text-amber-600" />
        )}
        <span>{friendlyLabel}</span>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
      <Info className="h-3 w-3 shrink-0 text-slate-500" />
      <span>{friendlyLabel}</span>
    </span>
  )
}

export function AiExtractionBadge({
  confidence = 'medium',
  provider,
}: {
  confidence?: ExtractionConfidence
  provider?: string | null
}) {
  const providerLabel = provider ? ` (${provider})` : ''
  if (confidence === 'high') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800">
        <Bot className="h-3 w-3 text-emerald-600" />
        <span>AI{providerLabel}: High confidence</span>
      </span>
    )
  }
  if (confidence === 'medium') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
        <Bot className="h-3 w-3 text-amber-600" />
        <span>AI{providerLabel}: Medium confidence</span>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-800">
      <Bot className="h-3 w-3 text-rose-600" />
      <span>AI{providerLabel}: Low confidence — review details</span>
    </span>
  )
}

export function WorkerAttributionBadge({
  status,
  workerName,
}: {
  status: WorkerAttributionStatus
  workerName?: string | null
}) {
  if (status === 'verified_target_worker') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-teal-200 bg-teal-50 px-2 py-0.5 text-xs font-medium text-teal-800">
        <UserCheck className="h-3 w-3 text-teal-600" />
        <span>Target worker: {workerName || 'verified'}</span>
      </span>
    )
  }
  if (status === 'ambiguous_or_unverified') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
        <AlertTriangle className="h-3 w-3 text-amber-600" />
        <span>Worker match uncertain: {workerName || 'unverified'}</span>
      </span>
    )
  }
  return null
}
