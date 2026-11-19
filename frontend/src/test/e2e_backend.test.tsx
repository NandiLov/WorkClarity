import fs from 'node:fs'
import path from 'node:path'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import { calculateShifts, checkHealth } from '../api/shiftsApi'
import { App } from '../App'
import type { ShiftRecord } from '../types/shift'
import { parseCsvLine, parseScheduleCsv } from '../utils/csvParser'

const BACKEND_URL = 'http://127.0.0.1:8000'
const REPO_ROOT = path.resolve(process.cwd(), '..')
const TEST_DATA_DIR = path.join(REPO_ROOT, 'data_validation', 'test_data')

function readRepoFile(relativePath: string): string {
  return fs.readFileSync(path.join(TEST_DATA_DIR, relativePath), 'utf8')
}

function readCsvObjects(relativePath: string): Record<string, string>[] {
  const raw = readRepoFile(relativePath).trim()
  const lines = raw.split(/\r?\n/)
  const headers = parseCsvLine(lines[0]).map((h) => h.trim())
  return lines.slice(1).map((line) => {
    const cells = parseCsvLine(line)
    const row: Record<string, string> = {}
    headers.forEach((h, idx) => {
      row[h] = (cells[idx] ?? '').trim()
    })
    return row
  })
}

async function uploadCsvFileInUi(
  user: ReturnType<typeof userEvent.setup>,
  fileName: string,
  csvText: string,
) {
  const input = screen.getByLabelText(
    /Choose CSV schedule file/i,
  ) as HTMLInputElement
  const file = new File([csvText], fileName, { type: 'text/csv' })
  await user.upload(input, file)
}

describe('WorkClarity E2E integration against live FastAPI backend', () => {
  beforeAll(async () => {
    vi.stubEnv('VITE_API_BASE_URL', BACKEND_URL)
    const health = await checkHealth()
    expect(health.status).toBe('healthy')
  })

  beforeEach(() => {
    localStorage.clear()
    window.history.pushState({}, '', '/upload')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  afterAll(() => {
    vi.unstubAllEnvs()
  })

  it('0. Matches all 32 expected weekly rows and 5 expected conflicts from repository answer keys', async () => {
    const employers = Object.fromEntries(
      readCsvObjects('employers.csv').map((e) => [
        e.employer_id,
        e.employer_name,
      ]),
    )
    const locations = Object.fromEntries(
      readCsvObjects('locations.csv').map((l) => [
        l.location_id,
        l.location_name,
      ]),
    )
    const truthRows = readCsvObjects('truth_shifts.csv')
    const expectedWeekly = readCsvObjects('expected_weekly_earnings.csv')
    const expectedConflicts = readCsvObjects('expected_conflicts.csv')

    const byWorker = new Map<string, ShiftRecord[]>()
    for (const r of truthRows) {
      // Per test_validator.py: S029-02 has missing hourly_rate in the expected answer key
      const rate = r.shift_id === 'S029-02' ? '' : r.hourly_rate
      const record: ShiftRecord = {
        shift_id: r.shift_id,
        worker_id: r.worker_id,
        schedule_id: r.schedule_id,
        line_no: Number(r.line_no),
        source_line: r.shift_id,
        extracted: {
          shift_date: r.shift_date,
          start_time: r.start_time,
          end_time: r.end_time,
          end_date: '',
          break_minutes: r.break_minutes,
          employer_name: employers[r.employer_id] ?? '',
          location: locations[r.location_id] ?? '',
          department: r.department,
          hourly_rate: rate,
          currency: r.currency,
          shift_status: r.shift_status as 'scheduled' | 'changed' | 'cancelled',
          stated_hours: '',
        },
        current: {
          shift_date: r.shift_date,
          start_time: r.start_time,
          end_time: r.end_time,
          end_date: '',
          break_minutes: r.break_minutes,
          employer_name: employers[r.employer_id] ?? '',
          location: locations[r.location_id] ?? '',
          department: r.department,
          hourly_rate: rate,
          currency: r.currency,
          shift_status: r.shift_status as 'scheduled' | 'changed' | 'cancelled',
          stated_hours: '',
        },
        confirmation_status: 'confirmed',
        calculated: null,
        updated_at: '2026-11-16T00:00:00Z',
      }
      const list = byWorker.get(r.worker_id) ?? []
      list.push(record)
      byWorker.set(r.worker_id, list)
    }

    const weeklyLookup = new Map<
      string,
      Awaited<ReturnType<typeof calculateShifts>>['weekly_summary'][number]
    >()
    const foundConflicts = new Set<string>()

    for (const [wId, workerShifts] of byWorker.entries()) {
      const res = await calculateShifts(wId, workerShifts, true)
      for (const w of res.weekly_summary) {
        weeklyLookup.set(`${wId}|${w.week_start}|${w.currency}`, w)
      }
      for (const c of res.conflicts) {
        foundConflicts.add(
          `${c.shift_a_id}|${c.shift_b_id}|${c.conflict_type}|${c.gap_minutes ?? ''}`,
        )
      }
    }

    expect(expectedWeekly).toHaveLength(32)
    for (const exp of expectedWeekly) {
      const got = weeklyLookup.get(
        `${exp.worker_id}|${exp.pay_week_start}|${exp.currency}`,
      )
      expect(got, `Missing weekly row ${exp.weekly_id}`).toBeDefined()
      expect(got!.shifts).toBe(Number(exp.shifts))
      expect(got!.cancelled_shifts).toBe(Number(exp.cancelled_shifts))
      expect(got!.incomplete_shifts).toBe(Number(exp.incomplete_shifts))
      expect(got!.paid_hours).toBeCloseTo(Number(exp.paid_hours), 2)
      expect(got!.gross_earnings).toBeCloseTo(
        Number(exp.expected_gross_mvp),
        2,
      )
    }

    expect(expectedConflicts).toHaveLength(5)
    for (const expC of expectedConflicts) {
      expect(
        foundConflicts.has(
          `${expC.shift_a_id}|${expC.shift_b_id}|${expC.conflict_type}|${expC.gap_minutes}`,
        ),
      ).toBe(true)
    }
  })

  it('1, 6, 12. CSV file upload (S001_schedule.csv), unconfirmed exclusion, and overnight shift ($384.00 / 24 hrs)', async () => {
    const user = userEvent.setup()
    const s001Csv = readRepoFile('schedule_inputs/S001_schedule.csv')
    render(<App />)

    await uploadCsvFileInUi(user, 'S001_schedule.csv', s001Csv)

    // Unconfirmed shifts must never be counted in earnings -> "Not counted yet"
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Review & Correct Shifts/i }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
      ).toBeEnabled()
      expect(screen.getAllByText(/Not counted yet/i).length).toBeGreaterThan(0)
    })

    // Confirm all 3 ready shifts (including the 22:00-06:00 overnight shift)
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$384\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('24 hrs')).toBeInTheDocument()
    })

    // Verify overnight badge on Confirmed & Counted tab and Weekly Schedule grouping (Monday week 2026-11-02)
    await user.click(
      screen.getByRole('button', { name: /Confirmed & Counted/i }),
    )
    expect(screen.getByText(/Overnight/i)).toBeInTheDocument()
    await user.click(screen.getAllByRole('link', { name: /Weekly Schedule/i })[0])
    expect(screen.getByText(/Nov 2 – Nov 8, 2026/i)).toBeInTheDocument()
    expect(screen.getByText(/SwiftLogistics/i)).toBeInTheDocument()
  })

  it('2. Duplicate detection and rejection (S009 duplicate_row -> releases retained shift on reject)', async () => {
    const user = userEvent.setup()
    // Build S009 raw rows (R025..R028 where R027 duplicates R026 on 2026-11-03)
    const rawCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status',
      '2026-11-02,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,scheduled',
      '2026-11-03,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,scheduled',
      '2026-11-03,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,scheduled',
      '2026-11-05,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,scheduled',
    ].join('\n')

    render(<App />)
    await uploadCsvFileInUi(user, 'S009_raw_duplicate.csv', rawCsv)

    // Confirm non-duplicate shifts; the duplicate copy remains flagged
    await waitFor(() => {
      expect(
        screen.getAllByText(/Possible duplicate shift/i).length,
      ).toBeGreaterThan(0)
    })

    // Confirm the 3 non-duplicate shifts
    const confirmBtns = screen.getAllByRole('button', {
      name: /^Confirm Shift$/i,
    })
    for (const btn of confirmBtns) {
      await user.click(btn)
    }

    // Even if all 4 are confirmed, backend holds duplicate out of earnings -> $315.00 (WK-S009)
    await waitFor(() => {
      expect(screen.getAllByText(/\$315\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    // Navigate to Warnings & reject the duplicate copy
    await user.click(screen.getAllByRole('link', { name: /Warnings/i })[0])
    const rejectDupBtn = await screen.findByRole('button', {
      name: /Reject Duplicate/i,
    })
    await user.click(rejectDupBtn)

    await waitFor(() => {
      expect(
        screen.queryByRole('button', { name: /Reject Duplicate/i }),
      ).not.toBeInTheDocument()
      expect(screen.getAllByText(/\$315\.00 \(USD\)/).length).toBeGreaterThan(0)
    })
  })

  it('3. Overlapping shifts (S004_schedule.csv -> overlap FL01 shown without hiding valid earnings)', async () => {
    const user = userEvent.setup()
    const s004Csv = readRepoFile('schedule_inputs/S004_schedule.csv')
    render(<App />)

    await uploadCsvFileInUi(user, 'S004_schedule.csv', s004Csv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$230\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('16 hrs')).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('link', { name: /Warnings/i })[0])
    expect(
      screen.getByRole('heading', { name: /Overlapping Shifts \(1\)/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/These shifts happen at the same time/i),
    ).toBeInTheDocument()
  })

  it('4, 10. Insufficient commute gap and exact-minute rounding (S005_schedule.csv -> 10m gap, 17.33 hrs, $250.33)', async () => {
    const user = userEvent.setup()
    const s005Csv = readRepoFile('schedule_inputs/S005_schedule.csv')
    render(<App />)

    await uploadCsvFileInUi(user, 'S005_schedule.csv', s005Csv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )

    // Matches WK-S005 in expected_weekly_earnings.csv: 17.33 hrs, $250.33, and 4.83 hrs -> $62.83
    await waitFor(() => {
      expect(screen.getAllByText(/\$250\.33 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('17.33 hrs')).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    expect(screen.getByText('$62.83')).toBeInTheDocument()

    // Check Warnings screen for 10 min commute heuristic
    await user.click(screen.getAllByRole('link', { name: /Warnings/i })[0])
    expect(
      screen.getByRole('heading', {
        name: /Short Travel Gaps Between Locations \(1\)/i,
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('10 min gap')).toBeInTheDocument()
    expect(
      screen.getByText(/scheduling heuristic, not a verified travel-time/i),
    ).toBeInTheDocument()
  })

  it('10b. Weekly rounding sums exact unrounded shift earnings ($1.67 + $1.67 -> $3.33)', async () => {
    const user = userEvent.setup()
    const roundingCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-09,09:00,09:01,0,BrightMart,Store A,100.00,USD',
      '2026-11-10,10:00,10:01,0,BrightMart,Store A,100.00,USD',
    ].join('\n')

    render(<App />)
    await uploadCsvFileInUi(user, 'rounding_test.csv', roundingCsv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    await waitFor(() => {
      expect(screen.getAllByText(/\$3\.33 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText('$1.67')).toHaveLength(2)
      expect(
        screen.getByText(
          /Weekly earnings are calculated from exact unrounded shift amounts\. The weekly total may therefore differ slightly from the sum of the displayed individual shift amounts\./i,
        ),
      ).toBeInTheDocument()
    })
  })

  it('5. Missing location (S014) and unknown location (S030) mark commute Not assessed while counting valid earnings', async () => {
    const user = userEvent.setup()
    const mixedLocationsCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-16,07:00,12:00,0,CityCare Hospital,Hospital Annex,15.00,USD',
      '2026-11-16,12:15,17:00,0,CityCare Hospital,Riverside Annex,15.00,USD',
      '2026-11-17,07:00,15:00,30,CityCare Hospital,,15.00,USD',
    ].join('\n')

    render(<App />)
    await uploadCsvFileInUi(user, 'locations_test.csv', mixedLocationsCsv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )

    // Matches WK-S030 ($258.75, 17.25 hrs) even with unknown & missing locations
    await waitFor(() => {
      expect(screen.getAllByText(/\$258\.75 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('17.25 hrs')).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('link', { name: /Warnings/i })[0])
    expect(
      screen.getByRole('heading', {
        name: /Commute Feasibility Not Assessed \(1\)/i,
      }),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/Unrecognized location/i).length).toBeGreaterThan(
      0,
    )
    expect(screen.getAllByText(/Location not listed/i).length).toBeGreaterThan(0)
  })

  it('6b. Overnight Sunday shift belongs to the Monday week in which it starts (S011_schedule.csv -> $279.00)', async () => {
    const user = userEvent.setup()
    const s011Csv = readRepoFile('schedule_inputs/S011_schedule.csv')
    render(<App />)

    await uploadCsvFileInUi(user, 'S011_schedule.csv', s011Csv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$279\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('15.5 hrs')).toBeInTheDocument()
      expect(screen.getByText(/Nov 2 – Nov 8, 2026/i)).toBeInTheDocument()
    })
  })

  it('7. Cancelled shifts (S015_schedule.csv -> $371.25, 2 cancelled at $0.00; all-cancelled genuine zero)', async () => {
    const user = userEvent.setup()
    const s015Csv = readRepoFile('schedule_inputs/S015_schedule.csv')
    render(<App />)

    await uploadCsvFileInUi(user, 'S015_schedule.csv', s015Csv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$371\.25 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('22.5 hrs')).toBeInTheDocument()
    })

    // Test a genuine zero week where every shift is cancelled (using explicit Replace mode)
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    await user.click(
      screen.getByRole('radio', { name: /Replace existing schedule/i }),
    )
    await user.click(
      screen.getByRole('checkbox', {
        name: /Confirm: replace all existing shifts/i,
      }),
    )
    const allCancelledCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency,shift_status',
      '2026-11-09,07:00,15:00,30,Central Cafe Group,Cafe Central,16.50,USD,cancelled',
    ].join('\n')
    await uploadCsvFileInUi(user, 'all_cancelled.csv', allCancelledCsv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )
    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])

    await waitFor(() => {
      expect(screen.getAllByText(/\$0\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(
        screen.getByText(/Genuine zero total: all shifts in this group were cancelled/i),
      ).toBeInTheDocument()
    })
  })

  it('8. Missing hourly rates (S029 -> $337.50 + 1 incomplete) and missing currencies (Not counted yet)', async () => {
    const user = userEvent.setup()
    const s029RawCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-16,08:00,16:00,30,PackRight,Packing Plant,15.00,USD',
      '2026-11-17,08:00,16:00,30,PackRight,Packing Plant,,USD',
      '2026-11-18,08:00,16:00,30,PackRight,Packing Plant,15.00,USD',
      '2026-11-19,08:00,16:00,30,PackRight,Packing Plant,15.00,USD',
    ].join('\n')

    render(<App />)
    await uploadCsvFileInUi(user, 'S029_missing_rate.csv', s029RawCsv)

    // Confirm all 4 shifts individually (including the one missing a rate)
    await waitFor(() => {
      expect(
        screen.getAllByRole('button', { name: /^Confirm Shift$/i }),
      ).toHaveLength(4)
    })
    for (const btn of screen.getAllByRole('button', {
      name: /^Confirm Shift$/i,
    })) {
      await user.click(btn)
    }

    // Matches WK-S029: $337.50, 22.5 hrs eligible, 1 incomplete shift (7.5 hrs)
    await waitFor(() => {
      expect(screen.getAllByText(/\$337\.50 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('22.5 hrs')).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    expect(
      screen.getByText(/1 incomplete shift\(s\) \(7\.5 hrs\)/i),
    ).toBeInTheDocument()

    // Now replace schedule with a shift missing currency -> must show "Not counted yet" and no total
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    await user.click(
      screen.getByRole('radio', { name: /Replace existing schedule/i }),
    )
    await user.click(
      screen.getByRole('checkbox', {
        name: /Confirm: replace all existing shifts/i,
      }),
    )
    const noCurrencyCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-16,08:00,16:00,30,PackRight,Packing Plant,15.00,',
    ].join('\n')
    await uploadCsvFileInUi(user, 'missing_currency.csv', noCurrencyCsv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /^Confirm Shift$/i }),
      ).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /^Confirm Shift$/i }))
    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])

    await waitFor(() => {
      expect(screen.getByText('CURRENCY MISSING')).toBeInTheDocument()
      expect(screen.getAllByText(/Not counted yet/i).length).toBeGreaterThan(0)
    })
  })

  it('9. Multiple currencies remain separate per currency (S028_schedule.csv -> $202.50 USD & €180.00 EUR)', async () => {
    const user = userEvent.setup()
    const s028Csv = readRepoFile('schedule_inputs/S028_schedule.csv')
    render(<App />)

    await uploadCsvFileInUi(user, 'S028_schedule.csv', s028Csv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    await waitFor(() => {
      expect(screen.getAllByText(/\$202\.50 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText(/€180\.00 \(EUR\)/).length).toBeGreaterThan(0)
    })
  })

  it('11, 17. Explicit zero-minute break vs missing break, original value preservation, and reset to original', async () => {
    const user = userEvent.setup()
    render(<App />)

    // Load MVP Spec Acceptance Example (§6.1): Mon 120 + Tue 112 = $232.00 (14.5 hrs), Wed blank break
    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('14.5 hrs')).toBeInTheDocument()
    })

    // Edit Wednesday shift to 30-min break & Save & Confirm -> $352.00 & 22 hrs
    const editButtons = screen.getAllByRole('button', { name: /Edit Details/i })
    await user.click(editButtons[0])
    const breakInput = screen.getByLabelText(/Unpaid break \(minutes\)/i)
    await user.clear(breakInput)
    await user.type(breakInput, '30')
    await user.click(screen.getByRole('button', { name: /Save & Confirm/i }))

    await waitFor(() => {
      expect(screen.getAllByText(/\$352\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('22 hrs')).toBeInTheDocument()
    })

    // Switch to Confirmed & Counted tab to verify diff preservation and reset to original
    await user.click(
      screen.getByRole('button', { name: /Confirmed & Counted/i }),
    )
    expect(
      screen.getAllByText(/Worker edits preserved separately from extracted CSV/i)
        .length,
    ).toBeGreaterThan(0)

    // Reset to original -> restores blank break, unconfirmed status, and $232.00
    await user.click(
      screen.getByRole('button', { name: /Reset to original/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('14.5 hrs')).toBeInTheDocument()
    })

    // Switch back to Needs Attention tab -> test explicit "Confirm 0 min break" + confirm ($360.00)
    await user.click(screen.getByRole('button', { name: /Needs Attention/i }))
    await user.click(
      screen.getByRole('button', { name: /Confirm 0 min break/i }),
    )
    await user.click(screen.getByRole('button', { name: /^Confirm Shift$/i }))
    await waitFor(() => {
      expect(screen.getAllByText(/\$360\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('22.5 hrs')).toBeInTheDocument()
    })
  })

  it('11b. Incomplete week total banner clarifies unconfirmed missing-break shifts, excludes explicit 0-min/rejected/cancelled shifts, and scopes by week & currency', async () => {
    const user = userEvent.setup()
    render(<App />)

    // 1. MVP Spec Acceptance Example (§6.1) on /earnings:
    // Preserves 14.5 hrs, $232.00 (USD), Wednesday excluded, and clarifies Wednesday needs break info & confirmation
    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('14.5 hrs')).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText('14.5 hrs').length).toBeGreaterThan(0)
      expect(screen.getByText(/Incomplete week total:/i)).toBeInTheDocument()
      expect(
        screen.getByText(
          /0 incomplete shift\(s\) \(0 hrs\) and 1 pending\/unconfirmed shift\(s\) \(0 hrs\)/i,
        ),
      ).toBeInTheDocument()
      expect(
        screen.getByText(/Missing break & confirmation required:/i),
      ).toBeInTheDocument()
      expect(
        screen.getByText(
          /1 unconfirmed shift \(Wednesday \(Nov 11\)\) also has a missing break and is excluded from earnings: this shift requires break information and confirmation before its earnings can be counted/i,
        ),
      ).toBeInTheDocument()
    })

    const wedBreakdownRow = screen
      .getByText(/Wed, Nov 11, 2026/i)
      .closest<HTMLElement>('div.px-5')!
    expect(within(wedBreakdownRow).getByText('Not counted yet')).toBeInTheDocument()

    // 2. Explicit zero-minute break must NOT trigger the missing-break explanation
    await user.click(screen.getAllByRole('link', { name: /Review & Correct/i })[0])
    await user.click(
      await screen.findByRole('button', { name: /Confirm 0 min break/i }),
    )
    await waitFor(() => {
      expect(screen.getByText('0 min break')).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText('14.5 hrs').length).toBeGreaterThan(0)
      expect(screen.getByText(/Incomplete week total:/i)).toBeInTheDocument()
      expect(
        screen.getByText(
          /0 incomplete shift\(s\) \(0 hrs\) and 1 pending\/unconfirmed shift\(s\) \(8 hrs\)/i,
        ),
      ).toBeInTheDocument()
    })
    expect(
      screen.queryByText(
        /requires break information and confirmation before its earnings can be counted/i,
      ),
    ).not.toBeInTheDocument()

    // 3. Rejected shift with missing break must NOT trigger the missing-break explanation
    await user.click(screen.getAllByRole('link', { name: /Review & Correct/i })[0])
    await user.click(
      await screen.findByRole('button', { name: /Reset to original/i }),
    )
    await waitFor(() => {
      expect(screen.getByText(/Break not confirmed/i)).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /^Reject$/i }))

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText('14.5 hrs').length).toBeGreaterThan(0)
    })
    expect(
      screen.queryByText(
        /requires break information and confirmation before its earnings can be counted/i,
      ),
    ).not.toBeInTheDocument()

    // 4. Cancelled & rejected shifts with missing breaks + week & currency scoping
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    await user.click(
      screen.getByRole('radio', { name: /Replace existing schedule/i }),
    )
    await user.click(
      screen.getByRole('checkbox', {
        name: /Confirm: replace all existing shifts/i,
      }),
    )

    const scopedCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency,shift_status',
      '2026-11-09,09:00,17:00,30,BrightMart,Store A,16.00,USD,scheduled',
      '2026-11-11,09:00,17:00,,BrightMart,Store A,16.00,USD,scheduled',
      '2026-11-13,09:00,17:00,,BrightMart,Store A,16.00,USD,scheduled',
      '2026-11-10,09:00,17:00,0,EuroMart,Store B,15.00,EUR,scheduled',
      '2026-11-12,09:00,17:00,,EuroMart,Store B,15.00,EUR,cancelled',
      '2026-11-16,09:00,17:00,,BrightMart,Store A,16.00,USD,scheduled',
    ].join('\n')

    await uploadCsvFileInUi(user, 'missing_break_scoping.csv', scopedCsv)

    const monCard = (await screen.findByText(/Mon, Nov 9, 2026/i)).closest(
      'article',
    )!
    await user.click(
      within(monCard).getByRole('button', { name: /^Confirm Shift$/i }),
    )

    const friCard = screen.getByText(/Fri, Nov 13, 2026/i).closest('article')!
    await user.click(
      within(friCard).getByRole('button', { name: /^Reject$/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$120\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    await waitFor(() => {
      expect(screen.getByText('USD')).toBeInTheDocument()
      expect(screen.getByText('EUR')).toBeInTheDocument()
    })

    const usdCard = screen.getByText('USD').closest('section')!
    const eurCard = screen.getByText('EUR').closest('section')!

    expect(within(usdCard).getByText(/Incomplete week total:/i)).toBeInTheDocument()
    expect(
      within(usdCard).getByText(
        /1 unconfirmed shift \(Wednesday \(Nov 11\)\) also has a missing break and is excluded from earnings: this shift requires break information and confirmation before its earnings can be counted/i,
      ),
    ).toBeInTheDocument()
    expect(
      within(usdCard).queryByText(/Fri|Nov 13|Nov 16/i),
    ).not.toBeInTheDocument()

    expect(within(eurCard).getByText(/Incomplete week total:/i)).toBeInTheDocument()
    expect(
      within(eurCard).queryByText(
        /requires break information and confirmation before its earnings can be counted/i,
      ),
    ).not.toBeInTheDocument()
    expect(
      screen.getByText(/1 rejected shift\(s\) are excluded from active totals/i),
    ).toBeInTheDocument()

    // Switch pay week to 2026-11-16 and verify missing-break clarification is scoped to that week only
    await user.selectOptions(
      screen.getByLabelText(/Select pay week/i),
      '2026-11-16',
    )
    await waitFor(() => {
      expect(
        screen.getByText(
          /1 unconfirmed shift \(Monday \(Nov 16\)\) also has a missing break and is excluded from earnings: this shift requires break information and confirmation before its earnings can be counted/i,
        ),
      ).toBeInTheDocument()
    })
    expect(screen.queryByText(/Wednesday \(Nov 11\)/i)).not.toBeInTheDocument()
  })

  it('13, 14. Persistence after browser refresh and worker workspace isolation', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<App />)

    // Load S001 for W001 and confirm
    await uploadCsvFileInUi(
      user,
      'S001_schedule.csv',
      readRepoFile('schedule_inputs/S001_schedule.csv'),
    )
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$384\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    // Switch to worker W008 and upload S028
    const workerSelect = screen.getAllByLabelText(/Worker Profile/i)[0]
    await user.selectOptions(workerSelect, 'W008')
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    await uploadCsvFileInUi(
      user,
      'S028_schedule.csv',
      readRepoFile('schedule_inputs/S028_schedule.csv'),
    )
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$202\.50 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText(/€180\.00 \(EUR\)/).length).toBeGreaterThan(0)
    })

    // Verify localStorage keys are strictly isolated per worker
    expect(localStorage.getItem('workclarity_dev_state_v1_W001')).toContain(
      'S001_schedule',
    )
    expect(localStorage.getItem('workclarity_dev_state_v1_W008')).toContain(
      'S028_schedule',
    )

    // Simulate browser refresh by unmounting and mounting fresh <App />
    unmount()
    render(<App />)

    await waitFor(() => {
      expect(screen.getAllByText(/\$202\.50 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText(/€180\.00 \(EUR\)/).length).toBeGreaterThan(0)
    })

    // Switch back to W001 and verify $384.00 is intact
    await user.selectOptions(
      screen.getAllByLabelText(/Worker Profile/i)[0],
      'W001',
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$384\.00 \(USD\)/).length).toBeGreaterThan(0)
    })
  })

  it('15. Backend disconnection hides stale earnings and recovers cleanly on retry', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    // Disconnect backend for next edit
    const originalFetch = globalThis.fetch.bind(globalThis)
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValue(new TypeError('Network disconnected'))

    await user.click(
      screen.getByRole('button', { name: /Confirm 0 min break/i }),
    )

    await waitFor(() => {
      expect(
        screen.getByText(/Calculation service unavailable/i),
      ).toBeInTheDocument()
      expect(screen.queryByText(/\$232\.00 \(USD\)/)).not.toBeInTheDocument()
    })

    // Restore live FastAPI fetch and click Retry recalculation
    fetchSpy.mockImplementation(originalFetch)
    await user.click(
      screen.getByRole('button', { name: /Retry recalculation/i }),
    )

    await waitFor(() => {
      expect(
        screen.queryByText(/Calculation service unavailable/i),
      ).not.toBeInTheDocument()
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
    })
  })

  it('16. Stale API response protection ignores delayed earlier response', async () => {
    const user = userEvent.setup()
    const realFetch = globalThis.fetch.bind(globalThis)
    let releaseFirstCalc!: () => void
    let calcCalls = 0

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/shifts/calculate')) {
        calcCalls += 1
        if (calcCalls === 1) {
          return new Promise<Response>((resolve) => {
            releaseFirstCalc = () => {
              // Return artificially stale/old response ($100.00) after second real edit completes
              resolve(
                new Response(
                  JSON.stringify({
                    worker_id: 'W001',
                    shifts: [],
                    weekly_summary: [
                      {
                        week_start: '2026-11-09',
                        currency: 'USD',
                        shifts: 1,
                        paid_hours: 6.25,
                        incomplete_hours: 0,
                        pending_hours: 0,
                        gross_earnings: 100.0,
                        incomplete_shifts: 0,
                        pending_shifts: 0,
                        earnings_incomplete: false,
                        cancelled_shifts: 0,
                      },
                    ],
                    conflicts: [],
                    commute_not_assessed: [],
                  }),
                  { status: 200 },
                ),
              )
            }
          })
        }
      }
      return realFetch(input, init)
    })

    render(<App />)
    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )

    const confirmZeroBtn = await screen.findByRole('button', {
      name: /Confirm 0 min break/i,
    })
    await user.click(confirmZeroBtn)
    await user.click(screen.getByRole('button', { name: /^Confirm Shift$/i }))

    await waitFor(() => {
      expect(screen.getAllByText(/\$360\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    await act(async () => {
      releaseFirstCalc()
      await new Promise((r) => setTimeout(r, 25))
    })

    expect(screen.queryByText(/\$100\.00/)).not.toBeInTheDocument()
    expect(screen.getAllByText(/\$360\.00 \(USD\)/).length).toBeGreaterThan(0)
  })

  it('18. Mobile & tablet responsive shell renders bottom nav, sidebar classes, and hides technical IDs under expandable details', async () => {
    const viewports = [375, 390, 768, 1280]
    for (const width of viewports) {
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        configurable: true,
        value: width,
      })
      window.dispatchEvent(new Event('resize'))
    }

    const user = userEvent.setup()
    const { container } = render(<App />)
    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    const mobileNav = screen.getByRole('navigation', {
      name: /Mobile navigation/i,
    })
    expect(mobileNav).toHaveClass('lg:hidden')
    expect(within(mobileNav).getAllByRole('link')).toHaveLength(5)

    const sidebar = container.querySelector('aside')
    expect(sidebar).toHaveClass('hidden', 'lg:flex')

    // Technical IDs must remain tucked inside collapsed <details> ("Technical details")
    const disclosures = screen.getAllByText(/Technical details/i)
    expect(disclosures.length).toBeGreaterThan(0)
    for (const summary of disclosures) {
      const detailsEl = summary.closest('details')
      expect(detailsEl).not.toHaveAttribute('open')
    }
  })

  it('1b. Direct parseScheduleCsv check on S026 & S027 invalid edge cases matches backend flags', async () => {
    // S026: >16h shift (09:00-02:00) & zero-duration shift (09:00-09:00); S027: negative & >=shift breaks
    const invalidCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-17,09:00,02:00,30,BrightMart,Store A,15.00,USD',
      '2026-11-18,09:00,09:00,30,BrightMart,Store A,15.00,USD',
      '2026-11-17,09:00,17:00,-15,BrightMart,Store A,15.00,USD',
      '2026-11-18,09:00,17:00,600,BrightMart,Store A,15.00,USD',
    ].join('\n')

    const parsed = parseScheduleCsv(invalidCsv, {
      workerId: 'W006',
      fileName: 'invalid_cases.csv',
      initialConfirmations: [
        'confirmed',
        'confirmed',
        'confirmed',
        'confirmed',
      ],
    })
    expect(parsed.ok).toBe(true)

    const res = await calculateShifts('W006', parsed.shifts, true)
    expect(res.shifts[0].flags.map((f) => f.code)).toContain('INVALID_DURATION')
    expect(res.shifts[1].flags.map((f) => f.code)).toContain('INVALID_DURATION')
    expect(res.shifts[2].flags.map((f) => f.code)).toContain('INVALID_BREAK')
    expect(res.shifts[3].flags.map((f) => f.code)).toContain('INVALID_BREAK')
    expect(res.shifts.every((s) => s.earnings_status === 'excluded')).toBe(true)
    expect(res.weekly_summary[0].gross_earnings).toBeNull()
  })

  it('19. Multi-employer schedule append keeps prior shifts, preserves unique IDs, detects cross-employer conflicts, and totals combined earnings', async () => {
    const user = userEvent.setup()
    const employerACsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-09,08:00,12:00,0,BrightMart,Retail X,14.00,USD',
      '2026-11-10,07:00,12:00,0,CityCare Hospital,Hospital Annex,15.00,USD',
    ].join('\n')

    const employerBCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-09,11:00,15:00,0,Diner Y Co,Diner Y,15.00,USD',
      '2026-11-10,12:15,16:00,0,Central Cafe Group,Cafe Downtown,13.00,USD',
    ].join('\n')

    render(<App />)

    // Upload Employer A schedule and confirm
    await uploadCsvFileInUi(user, 'employer_a.csv', employerACsv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(2\)/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(2\)/i }),
    )
    await waitFor(() => {
      // 4*14 + 5*15 = 56 + 75 = $131.00
      expect(screen.getAllByText(/\$131\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    // Return to Upload Schedule -> verify Add to existing schedule (append) is selected by default
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    expect(
      screen.getByRole('radio', { name: /Add to existing schedule/i }),
    ).toBeChecked()

    await uploadCsvFileInUi(user, 'employer_b.csv', employerBCsv)

    // Verify all 4 shifts exist across both employers and unique IDs were preserved
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /All Shifts\s*4/i }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(2\)/i }),
      ).toBeEnabled()
    })

    const savedRaw = localStorage.getItem('workclarity_dev_state_v1_W001')!
    const savedState = JSON.parse(savedRaw) as { shifts: ShiftRecord[] }
    expect(savedState.shifts).toHaveLength(4)
    expect(new Set(savedState.shifts.map((s) => s.shift_id)).size).toBe(4)
    expect(new Set(savedState.shifts.map((s) => s.schedule_id)).size).toBe(2)

    // Confirm Employer B shifts -> combined earnings: 131.00 + 4*15 + 3.75*13 = 131 + 60 + 48.75 = $239.75
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(2\)/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$239\.75 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('16.75 hrs')).toBeInTheDocument()
    })

    // Verify cross-employer Overlap (Mon 08:00-12:00 vs 11:00-15:00) AND 15m Commute gap (Tue 12:00 vs 12:15)
    await user.click(screen.getAllByRole('link', { name: /Warnings/i })[0])
    expect(
      screen.getByRole('heading', { name: /Overlapping Shifts \(1\)/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', {
        name: /Short Travel Gaps Between Locations \(1\)/i,
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('15 min gap')).toBeInTheDocument()
  })

  it('20. Duplicate schedule re-import preserves unique IDs and never double-counts earnings', async () => {
    const user = userEvent.setup()
    const s001Csv = readRepoFile('schedule_inputs/S001_schedule.csv')
    render(<App />)

    // First import & confirm -> $384.00
    await uploadCsvFileInUi(user, 'S001_schedule.csv', s001Csv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
    )
    await waitFor(() => {
      expect(screen.getAllByText(/\$384\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    // Re-import the exact same file in default Append mode
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    await uploadCsvFileInUi(user, 'S001_schedule.csv', s001Csv)

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /All Shifts\s*6/i }),
      ).toBeInTheDocument()
      expect(
        screen.getAllByText(/Possible duplicate shift/i).length,
      ).toBeGreaterThan(0)
    })

    // Duplicate shifts must be blocked from bulk confirmation and held out of earnings ($384.00, NOT $768.00)
    expect(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(0\)/i }),
    ).toBeDisabled()
    expect(screen.getAllByText(/\$384\.00 \(USD\)/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/\$768\.00/)).not.toBeInTheDocument()

    // Even if worker clicks individual Confirm Shift on duplicate rows, backend holds them in needs_review
    const singleConfirmBtns = screen.getAllByRole('button', {
      name: /^Confirm Shift$/i,
    })
    for (const btn of singleConfirmBtns) {
      await user.click(btn)
    }

    await waitFor(() => {
      expect(screen.getAllByText(/\$384\.00 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.queryByText(/\$768\.00/)).not.toBeInTheDocument()
    })

    const savedRaw = localStorage.getItem('workclarity_dev_state_v1_W001')!
    const savedState = JSON.parse(savedRaw) as { shifts: ShiftRecord[] }
    expect(savedState.shifts).toHaveLength(6)
    expect(new Set(savedState.shifts.map((s) => s.shift_id)).size).toBe(6)
  })

  it('21. Explicit Replace mode requires confirmation warning before replacing existing shifts', async () => {
    const user = userEvent.setup()
    const s001Csv = readRepoFile('schedule_inputs/S001_schedule.csv')
    const s004Csv = readRepoFile('schedule_inputs/S004_schedule.csv')
    render(<App />)

    await uploadCsvFileInUi(user, 'S001_schedule.csv', s001Csv)
    await waitFor(() => {
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    await user.click(
      screen.getByRole('radio', { name: /Replace existing schedule/i }),
    )

    // Warning is displayed and Select CSV File is disabled until checkbox is confirmed
    expect(
      screen.getByText(/Warning: Replacing will permanently remove 3 existing shift/i),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Select CSV File/i }),
    ).toBeDisabled()

    await user.click(
      screen.getByRole('checkbox', {
        name: /Confirm: replace all existing shifts/i,
      }),
    )
    expect(
      screen.getByRole('button', { name: /Select CSV File/i }),
    ).toBeEnabled()

    await uploadCsvFileInUi(user, 'S004_schedule.csv', s004Csv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /All Shifts\s*3/i }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
      ).toBeEnabled()
    })
  })

  it('22. Confirmation integrity resets status to unconfirmed when confirmed shift details are edited without Save & Confirm', async () => {
    const user = userEvent.setup()
    const singleShiftCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-09,09:00,17:00,0,BrightMart,Store A,16.00,USD',
    ].join('\n')

    render(<App />)
    await uploadCsvFileInUi(user, 'single.csv', singleShiftCsv)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(1\)/i }),
      ).toBeEnabled()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(1\)/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$128\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    // Edit the confirmed shift's break via Save Changes (NOT Save & Confirm)
    await user.click(
      screen.getByRole('button', { name: /Confirmed & Counted/i }),
    )
    await user.click(screen.getByRole('button', { name: /Edit Details/i }))

    const breakInput = screen.getByLabelText(/Unpaid break \(minutes\)/i)
    await user.clear(breakInput)
    await user.type(breakInput, '30')

    // Modal warns that renewed confirmation is required and sets decision select to unconfirmed
    expect(
      screen.getByText(/You edited a previously confirmed shift/i),
    ).toBeInTheDocument()
    expect(
      (
        screen.getByLabelText(
          /Confirmation decision/i,
        ) as HTMLSelectElement
      ).value,
    ).toBe('unconfirmed')

    await user.click(screen.getByRole('button', { name: /^Save Changes$/i }))

    // Shift moves back to Needs Attention as unconfirmed and earnings drop from $128.00 to Not counted yet
    await waitFor(() => {
      expect(screen.queryByText(/\$128\.00 \(USD\)/)).not.toBeInTheDocument()
      expect(screen.getAllByText(/Not counted yet/i).length).toBeGreaterThan(0)
    })

    await user.click(screen.getByRole('button', { name: /Needs Attention/i }))
    expect(screen.getByText('Unconfirmed')).toBeInTheDocument()

    // Now edit break to 60 and click explicit Save & Confirm -> retains original (0), previous (30), and current (60)
    await user.click(screen.getByRole('button', { name: /Edit Details/i }))
    const breakInput2 = screen.getByLabelText(/Unpaid break \(minutes\)/i)
    await user.clear(breakInput2)
    await user.type(breakInput2, '60')
    await user.click(screen.getByRole('button', { name: /Save & Confirm/i }))

    await waitFor(() => {
      // 7 paid hours * $16.00 = $112.00
      expect(screen.getAllByText(/\$112\.00 \(USD\)/).length).toBeGreaterThan(0)
    })

    await user.click(
      screen.getByRole('button', { name: /Confirmed & Counted/i }),
    )
    const savedRaw = localStorage.getItem('workclarity_dev_state_v1_W001')!
    const savedState = JSON.parse(savedRaw) as { shifts: ShiftRecord[] }
    expect(savedState.shifts[0].extracted.break_minutes).toBe('0')
    expect(savedState.shifts[0].previous_current?.break_minutes).toBe('30')
    expect(savedState.shifts[0].current.break_minutes).toBe('60')
  })

  it('23. Bulk confirmation is disabled while validation is pending or backend is offline and reports exact count when enabled', async () => {
    const user = userEvent.setup()
    const s001Csv = readRepoFile('schedule_inputs/S001_schedule.csv')
    const realFetch = globalThis.fetch.bind(globalThis)
    let releaseValidation!: () => void
    let holdFirstCalc = true

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/shifts/calculate') && holdFirstCalc) {
        holdFirstCalc = false
        return new Promise<Response>((resolve) => {
          releaseValidation = () => {
            void realFetch(input, init).then(resolve)
          }
        })
      }
      return realFetch(input, init)
    })

    render(<App />)
    await uploadCsvFileInUi(user, 'S001_schedule.csv', s001Csv)

    // While backend calculation is pending, Confirm All Valid Shifts must be disabled with count 0
    const pendingBtn = await screen.findByRole('button', {
      name: /Confirm All Valid Shifts/i,
    })
    expect(pendingBtn).toBeDisabled()

    // Release backend validation -> button becomes enabled with exact count (3)
    await act(async () => {
      releaseValidation()
    })

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
      ).toBeEnabled()
    })

    // Simulate backend disconnection -> button must disable again
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(
      new TypeError('Backend unreachable'),
    )
    await user.click(screen.getAllByRole('button', { name: /Edit Details/i })[0])
    await user.type(screen.getByLabelText(/Employer/i), ' Updated')
    await user.click(screen.getByRole('button', { name: /^Save Changes$/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/Calculation service unavailable/i),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts/i }),
      ).toBeDisabled()
    })

    // Restore backend, retry calculation, and confirm accurate count feedback
    vi.spyOn(globalThis, 'fetch').mockImplementation(realFetch)
    await user.click(
      screen.getByRole('button', { name: /Retry recalculation/i }),
    )
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
      ).toBeEnabled()
    })

    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
    )
    await waitFor(() => {
      expect(
        screen.getByText(/Confirmed 3 validated shift\(s\) and updated earnings\./i),
      ).toBeInTheDocument()
      expect(screen.getAllByText(/\$384\.00 \(USD\)/).length).toBeGreaterThan(0)
    })
  })

  it('24. Schedule Overview distinguishes scheduling/commute alerts (1) and shifts requiring attention (3) with 4 total attention items matching sidebar badge and hides stale counts', async () => {
    const user = userEvent.setup()
    const s005Csv = readRepoFile('schedule_inputs/S005_schedule.csv')
    const realFetch = globalThis.fetch.bind(globalThis)

    render(<App />)

    // S005 has 1 commute gap (Hospital Annex -> Cafe Downtown, 10 min) and 3 unconfirmed shifts (FL06 warning)
    await uploadCsvFileInUi(user, 'S005_schedule.csv', s005Csv)

    const overviewRegion = await screen.findByRole('region', {
      name: /Worker schedule overview/i,
    })
    const overviewWarningsLink = within(overviewRegion).getByRole('link', {
      name: /Warnings & Conflicts/i,
    })

    await waitFor(() => {
      expect(overviewWarningsLink).toHaveTextContent(/4\s+total attention items/i)
      expect(overviewWarningsLink).toHaveTextContent(
        /1\s+scheduling & commute alert(?!s)/i,
      )
      expect(overviewWarningsLink).toHaveTextContent(
        /3\s+shifts requiring attention/i,
      )
    })

    // Sidebar badge and mobile nav badge both match total attention items (4)
    const primaryNav = screen.getByRole('navigation', {
      name: /Primary navigation/i,
    })
    const sidebarWarningsLink = within(primaryNav).getByRole('link', {
      name: /Warnings & Conflicts/i,
    })
    expect(within(sidebarWarningsLink).getByText('4')).toBeInTheDocument()

    const mobileNav = screen.getByRole('navigation', {
      name: /Mobile navigation/i,
    })
    const mobileWarningsLink = within(mobileNav).getByRole('link', {
      name: /Warnings/i,
    })
    expect(within(mobileWarningsLink).getByText('4')).toBeInTheDocument()

    // While a recalculation is in-flight (stale), stale counts must not appear as current
    let releaseRecalc!: () => void
    let holdRecalc = true
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/shifts/calculate') && holdRecalc) {
        holdRecalc = false
        return new Promise<Response>((resolve) => {
          releaseRecalc = () => {
            void realFetch(input, init).then(resolve)
          }
        })
      }
      return realFetch(input, init)
    })

    await user.click(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(3\)/i }),
    )

    await waitFor(() => {
      expect(overviewWarningsLink).toHaveTextContent(/—\s+total attention items/i)
      expect(overviewWarningsLink).toHaveTextContent(
        /—\s+scheduling & commute alerts/i,
      )
      expect(overviewWarningsLink).toHaveTextContent(
        /—\s+shifts requiring attention/i,
      )
      expect(within(sidebarWarningsLink).queryByText('4')).not.toBeInTheDocument()
      expect(within(mobileWarningsLink).queryByText('4')).not.toBeInTheDocument()
    })

    await act(async () => {
      releaseRecalc()
    })

    // After confirmation recalculates, 0 shifts require attention while 1 commute alert stays -> 1 total item
    await waitFor(() => {
      expect(overviewWarningsLink).toHaveTextContent(
        /1\s+total attention item(?!s)/i,
      )
      expect(overviewWarningsLink).toHaveTextContent(
        /1\s+scheduling & commute alert(?!s)/i,
      )
      expect(overviewWarningsLink).toHaveTextContent(
        /0\s+shifts requiring attention/i,
      )
      expect(within(sidebarWarningsLink).getByText('1')).toBeInTheDocument()
      expect(within(mobileWarningsLink).getByText('1')).toBeInTheDocument()
    })

    // If backend becomes unavailable after an edit, Overview cards hide and sidebar badge does not show stale count
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(
      new TypeError('Backend unreachable'),
    )
    await user.click(
      screen.getByRole('button', { name: /Confirmed & Counted/i }),
    )
    await user.click(screen.getAllByRole('button', { name: /Edit Details/i })[0])
    await user.type(screen.getByLabelText(/Employer/i), ' Edited')
    await user.click(screen.getByRole('button', { name: /^Save Changes$/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/Calculation service unavailable/i),
      ).toBeInTheDocument()
      expect(within(sidebarWarningsLink).queryByText('1')).not.toBeInTheDocument()
    })
  })
})
