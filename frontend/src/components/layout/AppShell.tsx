import type { ReactNode } from 'react'
import {
  AlertTriangle,
  Calendar,
  CheckSquare,
  Database,
  ShieldCheck,
  Upload,
  Wallet,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useSchedule } from '../../context/scheduleContextStore'
import { OverviewBar } from './OverviewBar'

interface NavItem {
  to: string
  label: string
  shortLabel: string
  icon: typeof Upload
  badge?: number
  badgeTone?: 'amber' | 'rose'
}

export function AppShell({ children }: { children: ReactNode }) {
  const {
    workerId,
    workers,
    selectWorker,
    backendStatus,
    reviewQueueCount,
    warningsCount,
    activeFileName,
  } = useSchedule()

  const navItems: NavItem[] = [
    {
      to: '/upload',
      label: 'Upload Schedule',
      shortLabel: 'Upload',
      icon: Upload,
    },
    {
      to: '/review',
      label: 'Review & Correct',
      shortLabel: 'Review',
      icon: CheckSquare,
      badge: reviewQueueCount > 0 ? reviewQueueCount : undefined,
      badgeTone: 'amber',
    },
    {
      to: '/warnings',
      label: 'Warnings & Conflicts',
      shortLabel: 'Warnings',
      icon: AlertTriangle,
      badge: warningsCount > 0 ? warningsCount : undefined,
      badgeTone: 'rose',
    },
    {
      to: '/schedule',
      label: 'Weekly Schedule',
      shortLabel: 'Schedule',
      icon: Calendar,
    },
    {
      to: '/earnings',
      label: 'Weekly Earnings',
      shortLabel: 'Earnings',
      icon: Wallet,
    },
  ]

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 lg:flex-row">
      {/* Desktop Left Sidebar */}
      <aside className="hidden w-72 shrink-0 flex-col justify-between bg-slate-900 text-slate-100 lg:flex">
        <div>
          <div className="border-b border-slate-800 px-5 py-5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500 text-slate-950 shadow-xs">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <span className="text-base font-bold tracking-tight text-white">
                  WorkClarity
                </span>
                <p className="text-[11px] text-slate-400">
                  Schedule-to-Earnings Assistant
                </p>
              </div>
            </div>
          </div>

          {/* Worker Selector */}
          <div className="border-b border-slate-800 px-5 py-4">
            <label
              htmlFor="desktop-worker-select"
              className="block text-[11px] font-semibold uppercase tracking-wider text-slate-400"
            >
              Worker Profile
            </label>
            <select
              id="desktop-worker-select"
              value={workerId}
              onChange={(e) => selectWorker(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-medium text-white focus:border-emerald-400 focus:outline-none"
            >
              {workers.map((w) => (
                <option key={w.worker_id} value={w.worker_id}>
                  {w.worker_name} ({w.worker_id})
                </option>
              ))}
            </select>
            {activeFileName && (
              <p className="mt-2 truncate text-[11px] text-slate-400">
                Schedule:{' '}
                <span className="text-slate-200">{activeFileName}</span>
              </p>
            )}
          </div>

          {/* Primary Navigation */}
          <nav aria-label="Primary navigation" className="space-y-1 px-3 py-4">
            {navItems.map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `flex items-center justify-between rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                      isActive
                        ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-400/30'
                        : 'text-slate-300 hover:bg-slate-800/80 hover:text-white'
                    }`
                  }
                >
                  <span className="flex items-center gap-3">
                    <Icon className="h-4 w-4 shrink-0" />
                    <span>{item.label}</span>
                  </span>
                  {item.badge !== undefined && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-bold tabular-nums ${
                        item.badgeTone === 'rose'
                          ? 'bg-rose-500/20 text-rose-200'
                          : 'bg-amber-500/20 text-amber-200'
                      }`}
                    >
                      {item.badge}
                    </span>
                  )}
                </NavLink>
              )
            })}
          </nav>
        </div>

        {/* Footer: API Status & Temporary Local Persistence Notice */}
        <div className="space-y-3 border-t border-slate-800 p-4 text-xs">
          <div className="flex items-center justify-between rounded-lg bg-slate-800/70 px-3 py-2">
            <span className="text-slate-300">Calculation Service</span>
            {backendStatus === 'online' ? (
              <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-400">
                <Wifi className="h-3.5 w-3.5" />
                Connected
              </span>
            ) : backendStatus === 'checking' ? (
              <span className="text-slate-400">Checking…</span>
            ) : (
              <span className="inline-flex items-center gap-1.5 font-semibold text-rose-400">
                <WifiOff className="h-3.5 w-3.5" />
                Offline
              </span>
            )}
          </div>

          <details className="rounded-lg border border-slate-800 bg-slate-950/40 p-2.5 text-[11px] leading-relaxed text-slate-400">
            <summary className="flex cursor-pointer items-center gap-2 font-medium text-slate-300 select-none">
              <Database className="h-3.5 w-3.5 shrink-0 text-teal-400" />
              <span>Saved on this device (dev storage)</span>
            </summary>
            <p className="mt-1.5 text-[11px] text-slate-400">
              Temporary development persistence: edits are isolated per worker
              in browser localStorage until cloud sync is enabled.
            </p>
          </details>
        </div>
      </aside>

      {/* Mobile Top Bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-800 bg-slate-900 px-4 py-3 text-white lg:hidden">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500 text-slate-950">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <span className="text-sm font-bold tracking-tight">WorkClarity</span>
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="mobile-worker-select" className="sr-only">
            Demo Worker Profile
          </label>
          <select
            id="mobile-worker-select"
            value={workerId}
            onChange={(e) => selectWorker(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-xs font-medium text-white"
          >
            {workers.map((w) => (
              <option key={w.worker_id} value={w.worker_id}>
                {w.worker_id} ({w.worker_name.split(' ')[0]})
              </option>
            ))}
          </select>

          <span
            title={
              backendStatus === 'online'
                ? 'Calculation service connected'
                : 'Calculation service offline'
            }
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
              backendStatus === 'online'
                ? 'bg-emerald-500/20 text-emerald-300'
                : 'bg-rose-500/20 text-rose-300'
            }`}
          >
            {backendStatus === 'online' ? (
              <Wifi className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {backendStatus === 'online' ? 'API' : 'Offline'}
          </span>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex min-w-0 flex-1 flex-col pb-20 lg:pb-0">
        <OverviewBar />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
          {children}
        </main>
      </div>

      {/* Mobile Bottom Navigation */}
      <nav
        aria-label="Mobile navigation"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-slate-200 bg-white/95 backdrop-blur-xs lg:hidden"
      >
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `relative flex flex-col items-center justify-center gap-1 py-2.5 text-[11px] font-medium ${
                  isActive
                    ? 'text-emerald-700'
                    : 'text-slate-500 hover:text-slate-800'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <div className="relative">
                    <Icon
                      className={`h-5 w-5 ${
                        isActive ? 'text-emerald-600' : 'text-slate-500'
                      }`}
                    />
                    {item.badge !== undefined && (
                      <span
                        className={`absolute -top-1.5 -right-2.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold text-white ${
                          item.badgeTone === 'rose'
                            ? 'bg-rose-600'
                            : 'bg-amber-600'
                        }`}
                      >
                        {item.badge}
                      </span>
                    )}
                  </div>
                  <span>{item.shortLabel}</span>
                </>
              )}
            </NavLink>
          )
        })}
      </nav>
    </div>
  )
}
