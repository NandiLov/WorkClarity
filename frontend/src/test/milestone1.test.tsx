import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toBackendShiftInput } from '../api/shiftsApi'
import { App } from '../App'
import { parseScheduleCsv } from '../utils/csvParser'
import {
  formatCurrency,
  formatCurrencyWithCode,
  getChangedFields,
  isOvernightShift,
} from '../utils/formatters'

describe('CSV parsing and contract preservation', () => {
  it('preserves missing break, rate, and currency as empty strings and sets shifts unconfirmed', () => {
    const csv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-09,09:00,17:00,,BrightMart,Store A,,',
      '2026-11-10,10:00,18:00,0,BrightMart,Store A,16.00,USD',
    ].join('\n')

    const parsed = parseScheduleCsv(csv, {
      workerId: 'W001',
      fileName: 'sample.csv',
    })

    expect(parsed.ok).toBe(true)
    expect(parsed.shifts).toHaveLength(2)

    const [first, second] = parsed.shifts
    expect(first.confirmation_status).toBe('unconfirmed')
    expect(first.extracted.break_minutes).toBe('')
    expect(first.extracted.hourly_rate).toBe('')
    expect(first.extracted.currency).toBe('')
    expect(first.shift_id).not.toBe(second.shift_id)

    expect(second.extracted.break_minutes).toBe('0')
    expect(second.source_line).toBe(
      '2026-11-10,10:00,18:00,0,BrightMart,Store A,16.00,USD',
    )
  })

  it('rejects empty or non-schedule CSV files with clear error messages', () => {
    const emptyRes = parseScheduleCsv('   ', {
      workerId: 'W001',
      fileName: 'empty.csv',
    })
    expect(emptyRes.ok).toBe(false)
    expect(emptyRes.errors[0]).toMatch(/empty/i)

    const badHeaders = parseScheduleCsv('name,age\nAlice,30', {
      workerId: 'W001',
      fileName: 'wrong.csv',
    })
    expect(badHeaders.ok).toBe(false)
    expect(badHeaders.errors[0]).toMatch(/shift_date/)
  })
})

describe('Backend payload serialization', () => {
  it('converts blank break/rate/currency to null and keeps explicit 0 break as 0 without rules', () => {
    const csv = [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,hourly_rate,currency',
      '2026-11-11,09:00,17:00,,BrightMart,Store A,,',
      '2026-11-12,09:00,17:00,0,BrightMart,Store A,16.00,USD',
    ].join('\n')

    const parsed = parseScheduleCsv(csv, {
      workerId: 'W001',
      fileName: 'test.csv',
    })

    const payloadMissing = toBackendShiftInput(parsed.shifts[0])
    expect(payloadMissing.break_minutes).toBeNull()
    expect(payloadMissing.hourly_rate).toBeNull()
    expect(payloadMissing.currency).toBeNull()
    expect(payloadMissing).not.toHaveProperty('rules')
    expect(payloadMissing).not.toHaveProperty('known_locations')

    const payloadZero = toBackendShiftInput(parsed.shifts[1])
    expect(payloadZero.break_minutes).toBe(0)
    expect(payloadZero.hourly_rate).toBe('16.00')
    expect(payloadZero.currency).toBe('USD')
  })
})

describe('Display formatters', () => {
  it('shows Not counted yet for null gross earnings and distinguishes genuine 0.00', () => {
    expect(formatCurrency(null, 'USD')).toBe('Not counted yet')
    expect(formatCurrencyWithCode(null, 'EUR')).toBe('Not counted yet')
    expect(formatCurrency(0, 'USD')).toBe('$0.00')
    expect(formatCurrencyWithCode(202.5, 'USD')).toBe('$202.50 (USD)')
    expect(formatCurrencyWithCode(180, 'EUR')).toBe('€180.00 (EUR)')
  })

  it('detects overnight shifts and computes field diffs without altering extracted data', () => {
    expect(isOvernightShift('22:00', '06:00', '2026-11-05')).toBe(true)
    expect(isOvernightShift('09:00', '17:00', '2026-11-05')).toBe(false)

    const parsed = parseScheduleCsv(
      'shift_date,start_time,end_time,break_minutes,hourly_rate,currency\n2026-11-09,09:00,17:00,,16,USD',
      { workerId: 'W001', fileName: 'diff.csv' },
    )
    const rec = parsed.shifts[0]
    const updated = { ...rec.current, break_minutes: '30' }
    const diffs = getChangedFields(rec.extracted, updated)
    expect(diffs).toHaveLength(1)
    expect(diffs[0]).toMatchObject({
      field: 'break_minutes',
      originalValue: '(empty)',
      currentValue: '30',
    })
  })
})

describe('Application shell, routing, and stale-response / offline safety', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/upload')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('renders navigation across core routes and handles offline backend without showing stale totals', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(
      new TypeError('Failed to fetch'),
    )

    const user = userEvent.setup()
    render(<App />)

    expect(
      screen.getByRole('heading', { name: /Upload Schedule/i }),
    ).toBeInTheDocument()

    // Load a preset schedule while backend is offline
    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )

    await waitFor(() => {
      expect(
        screen.getByText(/Calculation service unavailable/i),
      ).toBeInTheDocument()
    })

    // Navigate to Earnings and confirm stale earnings are blocked rather than shown as valid
    const earningsLinks = screen.getAllByRole('link', { name: /Earnings/i })
    await user.click(earningsLinks[0])

    expect(
      screen.getByText(
        /Earnings cannot be displayed while the calculation service is unavailable/i,
      ),
    ).toBeInTheDocument()
  })

  it('ignores out-of-order stale API responses when a newer edit has already fired', async () => {
    let resolveFirstCalc!: (value: Response) => void
    let callCount = 0

    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.endsWith('/health')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: 'healthy',
              service: 'WorkClarity API',
              version: '0.1.0',
            }),
            { status: 200 },
          ),
        )
      }

      callCount += 1
      if (callCount === 1) {
        // Delayed response for initial load (would return $100.00 if erroneously applied)
        return new Promise<Response>((resolve) => {
          resolveFirstCalc = resolve
        })
      }

      // Latest response returns $232.00
      return Promise.resolve(
        new Response(
          JSON.stringify({
            worker_id: 'W001',
            shifts: [
              {
                shift_id: 'spec_acceptance_exam-S01',
                date: '2026-11-09',
                week_start: '2026-11-09',
                paid_hours: 7.5,
                hourly_rate: 16,
                currency: 'USD',
                gross_earnings: 120,
                validation_status: 'valid',
                earnings_status: 'counted',
                eligible_for_earnings: true,
                earnings_reason: null,
                flags: [],
              },
            ],
            weekly_summary: [
              {
                week_start: '2026-11-09',
                currency: 'USD',
                shifts: 1,
                paid_hours: 14.5,
                incomplete_hours: 0,
                pending_hours: 0,
                gross_earnings: 232.0,
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
    })

    const user = userEvent.setup()
    render(<App />)

    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )

    // Immediately trigger a second edit before the first calculation resolves
    const confirmButtons = await screen.findAllByRole('button', {
      name: /Confirm Shift/i,
    })
    await user.click(confirmButtons[0])

    await waitFor(() => {
      expect(screen.getAllByText(/\$232\.00/).length).toBeGreaterThan(0)
    })

    // Now resolve the stale first request with an outdated amount ($100.00)
    await act(async () => {
      resolveFirstCalc(
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
      await new Promise((r) => setTimeout(r, 20))
    })

    // Verify stale $100.00 did NOT overwrite $232.00
    expect(screen.queryByText(/\$100\.00/)).not.toBeInTheDocument()
    expect(screen.getAllByText(/\$232\.00/).length).toBeGreaterThan(0)
  })
})
