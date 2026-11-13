// Runs schedules through a copy of Newly's own rules (logic.ts) the way the app does it:
// parse the csv, import the rows that are not errors, let the worker confirm what the app allows,
// then total each Monday week. Usage: tsx newly_runner.mts <path to logic.ts> <input.json> <output.json>
import { readFileSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const [logicPath, inPath, outPath] = process.argv.slice(2)
if (!logicPath || !inPath || !outPath) {
  console.error('Usage: tsx newly_runner.mts <logic.ts> <input.json> <output.json>')
  process.exit(2)
}

const L: any = await import(pathToFileURL(logicPath).href)
const input = JSON.parse(readFileSync(inPath, 'utf8')) as Record<string, { csv: string; actions?: Record<string, string> }>

function mondayOf(date: string): string {
  const d = new Date(date + 'T00:00:00Z').getUTCDay() // 0 = Sunday
  return L.addDays(date, -((d + 6) % 7))
}

const out: Record<string, any> = {}
for (const [sid, spec] of Object.entries(input)) {
  let rows: any[]
  try {
    rows = L.parseScheduleCsv(spec.csv)
  } catch (e: any) {
    out[sid] = { csv_error: String(e?.message ?? e) }
    continue
  }
  const stored: any[] = []
  const skipped: any[] = []
  rows.forEach((r) => {
    if (r.state === 'error') {
      skipped.push({ line: r.line, issues: r.issues.map((i: any) => i.code) })
      return
    }
    stored.push({
      id: `${sid}-${String(r.line - 1).padStart(2, '0')}`,
      line: r.line,
      status: r.state === 'ready' ? 'unconfirmed' : 'needs_review',
      employer: r.employer, role: r.role, date: r.date, start_time: r.start_time, end_time: r.end_time,
      break_minutes: r.break_minutes, rate_cents: r.rate_cents, currency: r.currency, location: r.location,
      import_issues: r.issues.map((i: any) => i.code),
    })
  })
  // what the worker does in the app: reject or confirm each shift (the app refuses to confirm without date, times and break)
  const refused: string[] = []
  for (const s of stored) {
    const wanted = spec.actions?.[String(s.line - 1)] ?? 'confirmed'
    if (wanted === 'rejected') s.status = 'rejected'
    else if (!s.date || !s.start_time || !s.end_time || s.break_minutes === null) refused.push(s.id)
    else s.status = 'confirmed'
  }
  const conflicts = L.detectConflicts(stored)
  const computed = stored.map((s: any) => ({
    ...L.computeShift(s), line: s.line, import_issues: s.import_issues,
    conflict_ids: conflicts.filter((c: any) => c.shift_ids.includes(s.id)).map((c: any) => c.id),
  }))
  const weeks = [...new Set(computed.filter((s: any) => s.date).map((s: any) => mondayOf(s.date)))].sort() as string[]
  const weekly = weeks.map((ws) => {
    const inWeek = computed.filter((s: any) => s.date && s.date >= ws && s.date <= L.addDays(ws, 6))
    const ids = new Set(inWeek.map((s: any) => s.id))
    const wc = conflicts.filter((c: any) => ids.has(c.shift_ids[0]) || ids.has(c.shift_ids[1]))
    const sum = L.summarizeWeek(inWeek, wc)
    return {
      week_start: ws,
      gross: Object.fromEntries(sum.gross_by_currency.map((g: any) => [g.currency, g.gross_cents / 100])),
      counted: Object.fromEntries(sum.gross_by_currency.map((g: any) => [g.currency, g.shifts])),
      incomplete: sum.incomplete_earnings,
    }
  })
  out[sid] = {
    skipped, refused, weekly,
    shifts: computed.map((s: any) => ({
      id: s.id, line: s.line, date: s.date, status: s.status, earnings: s.earnings,
      gross: s.gross_cents === null ? null : s.gross_cents / 100,
      import_issues: s.import_issues, conflict_ids: s.conflict_ids,
    })),
    conflicts: conflicts.map((c: any) => ({ id: c.id, type: c.type, shift_ids: c.shift_ids, minutes: c.minutes })),
  }
}
writeFileSync(outPath, JSON.stringify(out, null, 1))
console.log(`Ran ${Object.keys(out).length} schedules`)
