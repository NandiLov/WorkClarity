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
      expect(screen.getAllByText(/Not counted yet/i).length).toBeGreaterThan(0)
    })

    // Confirm all 3 ready shifts (including the 22:00-06:00 overnight shift)
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
    )

    await user.click(screen.getAllByRole('link', { name: /Earnings/i })[0])
    await waitFor(() => {
      expect(screen.getAllByText(/\$3\.33 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getAllByText('$1.67')).toHaveLength(2)
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
    )

    await waitFor(() => {
      expect(screen.getAllByText(/\$371\.25 \(USD\)/).length).toBeGreaterThan(0)
      expect(screen.getByText('22.5 hrs')).toBeInTheDocument()
    })

    // Test a genuine zero week where every shift is cancelled
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
    const allCancelledCsv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency,shift_status',
      '2026-11-09,07:00,15:00,30,Central Cafe Group,Cafe Central,16.50,USD,cancelled',
    ].join('\n')
    await uploadCsvFileInUi(user, 'all_cancelled.csv', allCancelledCsv)
    await waitFor(() => {
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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

    // Now upload a shift missing currency -> must show "Not counted yet" and no total
    await user.click(screen.getAllByRole('link', { name: /Upload/i })[0])
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
      expect(screen.getByText(/Review & Correct Shifts/i)).toBeInTheDocument()
    })
    await user.click(
      screen.getByRole('button', { name: /Confirm Ready Shifts/i }),
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
})
