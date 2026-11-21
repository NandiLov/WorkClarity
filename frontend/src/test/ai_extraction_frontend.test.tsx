import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { extractScheduleFile } from '../api/shiftsApi'
import { App } from '../App'
import type { ShiftExtractionResponse } from '../types/shift'

const MOCK_SUCCESSFUL_EXTRACTION: ShiftExtractionResponse = {
  file_name: 'roster_nov2026.pdf',
  target_worker: 'W001',
  page_count: 1,
  extraction_status: 'succeeded',
  succeeded: true,
  is_complete: true,
  is_partial: false,
  is_failed: false,
  is_empty_schedule: false,
  manual_entry_required: false,
  manual_entry_reason: null,
  active_provider: 'gemini',
  active_model_id: 'gemini-2.5-flash',
  fallback_triggered: false,
  processing_time_seconds: 1.25,
  total_shifts_extracted: 2,
  shifts: [
    {
      normalised: {
        shift_date: '2026-11-09',
        start_time: '09:00',
        end_time: '17:00',
        break_minutes: 30,
        employer_name: 'BrightMart',
        location: 'Store A',
        department: 'Sales',
        hourly_rate: 16.0,
        currency: 'USD',
        shift_status: 'scheduled',
      },
      worker_name: 'Ada Okoye',
      worker_attribution_status: 'verified_target_worker',
      confidence: 'high',
      uncertain_fields: [],
      validation_warnings: [],
      review_reasons: [],
      partially_recovered: false,
      confirmation_status: 'needs_review',
      requires_worker_confirmation: true,
      requires_individual_review: true,
      eligible_for_bulk_confirmation: false,
    },
    {
      normalised: {
        shift_date: '2026-11-10',
        start_time: '10:00',
        end_time: '18:00',
        break_minutes: null, // missing break
        employer_name: 'BrightMart',
        location: 'Store A',
        department: 'Sales',
        hourly_rate: null, // missing rate
        currency: 'USD',
        shift_status: 'scheduled',
      },
      worker_name: 'Ada Okoye',
      worker_attribution_status: 'ambiguous_or_unverified',
      confidence: 'medium',
      uncertain_fields: ['break_minutes', 'hourly_rate'],
      validation_warnings: ['Missing unpaid break duration'],
      review_reasons: ['Uncertain rate and break'],
      partially_recovered: true,
      confirmation_status: 'needs_review',
      requires_worker_confirmation: true,
      requires_individual_review: true,
      eligible_for_bulk_confirmation: false,
    },
  ],
}

describe('AI Extraction API Client', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('sends multipart/form-data to POST /api/v1/shifts/extract', async () => {
    let capturedUrl = ''
    let capturedMethod = ''
    let capturedBody: FormData | null = null

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      capturedUrl = String(input)
      capturedMethod = init?.method ?? 'GET'
      capturedBody = (init?.body as FormData) ?? null
      return Promise.resolve(
        new Response(JSON.stringify(MOCK_SUCCESSFUL_EXTRACTION), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })

    const dummyFile = new File(['%PDF-1.4 test'], 'schedule.pdf', {
      type: 'application/pdf',
    })
    const res = await extractScheduleFile(dummyFile, { targetWorker: 'W001' })

    expect(capturedUrl).toContain('/api/v1/shifts/extract')
    expect(capturedMethod).toBe('POST')
    expect(capturedBody).toBeInstanceOf(FormData)
    expect(res.succeeded).toBe(true)
    expect(res.shifts).toHaveLength(2)
  })

  it('surfaces backend 400 validation error message cleanly', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: 'Unsupported file type (.txt). Supported: .pdf, .png, .jpg, .jpeg, .webp',
        }),
        {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )

    const txtFile = new File(['shifts'], 'schedule.txt', {
      type: 'text/plain',
    })
    await expect(extractScheduleFile(txtFile)).rejects.toThrow(
      /Unsupported file type/i,
    )
  })
})

describe('AI Extraction Frontend Integration & Safeguards', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/upload')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('processes PDF upload, defaults shifts to needs_review, blocks bulk confirmation, and renders attribution badges', async () => {
    let capturedTargetWorker: FormDataEntryValue | null = null

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
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
      if (url.includes('/extract')) {
        const body = init?.body
        if (body instanceof FormData) {
          capturedTargetWorker = body.get('target_worker')
        }
        return Promise.resolve(
          new Response(JSON.stringify(MOCK_SUCCESSFUL_EXTRACTION), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (url.includes('/calculate')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              worker_id: 'W001',
              shifts: [
                {
                  shift_id: 'test-AI01',
                  date: '2026-11-09',
                  week_start: '2026-11-09',
                  paid_hours: 7.5,
                  hourly_rate: 16.0,
                  currency: 'USD',
                  gross_earnings: null,
                  validation_status: 'valid',
                  earnings_status: 'needs_review',
                  eligible_for_earnings: false,
                  earnings_reason:
                    'Shift is pending worker confirmation and excluded from earnings.',
                  flags: [],
                },
                {
                  shift_id: 'test-AI02',
                  date: '2026-11-10',
                  week_start: '2026-11-09',
                  paid_hours: null,
                  hourly_rate: null,
                  currency: 'USD',
                  gross_earnings: null,
                  validation_status: 'invalid',
                  earnings_status: 'incomplete',
                  eligible_for_earnings: false,
                  earnings_reason: 'Missing unpaid break and hourly rate.',
                  flags: [
                    {
                      code: 'BREAK_MISSING',
                      flag_type_id: 'FL02',
                      flag_name: 'Missing Break',
                      severity: 'warning',
                      reason: 'Unpaid break duration not recorded.',
                      message: 'Unpaid break duration is missing.',
                    },
                  ],
                },
              ],
              weekly_summary: [],
              conflicts: [],
              commute_not_assessed: [],
              calculated_at: new Date().toISOString(),
            }),
            { status: 200 },
          ),
        )
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    const user = userEvent.setup()
    render(<App />)

    // Verify upload dropzone is present
    const fileInput = screen.getByLabelText(
      /Choose CSV schedule file/i,
    ) as HTMLInputElement

    const pdfFile = new File(['%PDF-1.4 binary content'], 'roster_nov2026.pdf', {
      type: 'application/pdf',
    })

    // Simulate PDF file selection
    await act(async () => {
      await user.upload(fileInput, pdfFile)
    })

    // Should navigate to /review after extraction
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Review & Correct Shifts/i }),
      ).toBeInTheDocument()
    })

    // Target worker must be worker display name, never internal worker ID
    expect(capturedTargetWorker).toBe('Ada Okoye')

    // Invariant 1: Bulk confirmation must be disabled because AI shifts require individual confirmation
    const bulkConfirmBtn = screen.getByRole('button', {
      name: /Confirm All Valid Shifts \(0\)/i,
    })
    expect(bulkConfirmBtn).toBeDisabled()

    // Invariant 2: AI extraction badges and worker attribution badges must be visible
    expect(screen.getByText(/AI \(gemini\): High confidence/i)).toBeInTheDocument()
    expect(screen.getByText(/AI \(gemini\): Medium confidence/i)).toBeInTheDocument()
    expect(screen.getByText(/Target worker: Ada Okoye/i)).toBeInTheDocument()
    expect(screen.getByText(/Worker match uncertain: Ada Okoye/i)).toBeInTheDocument()

    // Invariant 3: Missing break quick action is available for shift with missing break
    expect(
      screen.getByRole('button', { name: /Confirm 0 min break/i }),
    ).toBeInTheDocument()

    // Invariant 4: Confirming individually works
    const confirmButtons = screen.getAllByRole('button', {
      name: /Confirm Shift/i,
    })
    expect(confirmButtons.length).toBeGreaterThan(0)
  })

  it('handles failed extraction requiring manual entry by presenting clear error feedback', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
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
      if (url.includes('/extract')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              file_name: 'blurry_photo.png',
              target_worker: 'W001',
              page_count: 1,
              extraction_status: 'failed',
              succeeded: false,
              is_complete: false,
              is_partial: false,
              is_failed: true,
              is_empty_schedule: false,
              manual_entry_required: true,
              manual_entry_reason:
                'Image is too blurry or low-resolution for automated text extraction.',
              active_provider: null,
              active_model_id: null,
              fallback_triggered: true,
              processing_time_seconds: 0.8,
              total_shifts_extracted: 0,
              shifts: [],
            }),
            { status: 200 },
          ),
        )
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    const user = userEvent.setup()
    render(<App />)

    const fileInput = screen.getByLabelText(
      /Choose CSV schedule file/i,
    ) as HTMLInputElement
    const blurryImage = new File(['fake image bytes'], 'blurry_photo.png', {
      type: 'image/png',
    })

    await act(async () => {
      await user.upload(fileInput, blurryImage)
    })

    await waitFor(() => {
      expect(
        screen.getByText(/Image is too blurry or low-resolution/i),
      ).toBeInTheDocument()
    })
  })

  it('imports partial extraction shifts as needs_review with bulk confirmation disabled', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
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
      if (url.includes('/extract')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...MOCK_SUCCESSFUL_EXTRACTION,
              file_name: 'partial_roster.pdf',
              extraction_status: 'partial',
              succeeded: false,
              is_complete: false,
              is_partial: true,
              manual_entry_required: true,
              manual_entry_reason: 'Truncated second page; recovered 1 shift.',
              total_shifts_extracted: 1,
              shifts: [MOCK_SUCCESSFUL_EXTRACTION.shifts[0]],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (url.includes('/calculate')) {
        const parsed = JSON.parse(String(init?.body ?? '{}')) as {
          shifts?: Array<{ shift_id?: string }>
        }
        const shiftId = parsed.shifts?.[0]?.shift_id ?? 'partial-AI01'
        return Promise.resolve(
          new Response(
            JSON.stringify({
              worker_id: 'W001',
              shifts: [
                {
                  shift_id: shiftId,
                  date: '2026-11-09',
                  week_start: '2026-11-09',
                  paid_hours: 7.5,
                  hourly_rate: 16.0,
                  currency: 'USD',
                  gross_earnings: null,
                  validation_status: 'valid',
                  earnings_status: 'needs_review',
                  eligible_for_earnings: false,
                  earnings_reason: 'Requires worker confirmation.',
                  flags: [],
                },
              ],
              weekly_summary: [],
              conflicts: [],
              commute_not_assessed: [],
              calculated_at: new Date().toISOString(),
            }),
            { status: 200 },
          ),
        )
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    const user = userEvent.setup()
    render(<App />)

    const fileInput = screen.getByLabelText(
      /Choose CSV schedule file/i,
    ) as HTMLInputElement
    const partialPdf = new File(['%PDF-1.4 partial'], 'partial_roster.pdf', {
      type: 'application/pdf',
    })

    await act(async () => {
      await user.upload(fileInput, partialPdf)
    })

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Review & Correct Shifts/i }),
      ).toBeInTheDocument()
      expect(screen.getByText(/Held for review/i)).toBeInTheDocument()
      expect(screen.getByText(/Needs review/i)).toBeInTheDocument()
    })

    expect(
      screen.getByRole('button', { name: /Confirm All Valid Shifts \(0\)/i }),
    ).toBeDisabled()
    expect(screen.getByText(/Target worker: Ada Okoye/i)).toBeInTheDocument()
  })

  it('preserves existing loaded schedule when AI extraction fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
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
      if (url.includes('/calculate')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              worker_id: 'W001',
              shifts: [],
              weekly_summary: [],
              conflicts: [],
              commute_not_assessed: [],
              calculated_at: new Date().toISOString(),
            }),
            { status: 200 },
          ),
        )
      }
      if (url.includes('/extract')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              file_name: 'corrupt_scan.pdf',
              target_worker: 'Ada Okoye',
              page_count: 1,
              extraction_status: 'failed',
              succeeded: false,
              is_complete: false,
              is_partial: false,
              is_failed: true,
              is_empty_schedule: false,
              manual_entry_required: true,
              manual_entry_reason: 'All providers failed to parse schedule.',
              active_provider: null,
              active_model_id: null,
              fallback_triggered: true,
              processing_time_seconds: 0.4,
              total_shifts_extracted: 0,
              shifts: [],
            }),
            { status: 200 },
          ),
        )
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    const user = userEvent.setup()
    render(<App />)

    // First load a preset schedule (3 shifts)
    await user.click(
      screen.getByRole('button', { name: /MVP Spec Acceptance Example/i }),
    )
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Review & Correct Shifts/i }),
      ).toBeInTheDocument()
    })

    // Return to Upload Schedule page and select Replace mode cleanly or Append mode
    const uploadLinks = screen.getAllByRole('link', { name: /Upload Schedule/i })
    await user.click(uploadLinks[0])

    expect(
      screen.getByText(/You already have 3 active shift\(s\) loaded/i),
    ).toBeInTheDocument()

    // Select Replace mode and confirm checkbox, then upload a failing PDF
    await user.click(screen.getByLabelText(/Replace existing schedule/i))
    await user.click(
      screen.getByLabelText(/Confirm: replace all existing shifts for W001/i),
    )

    const fileInput = screen.getByLabelText(
      /Choose CSV schedule file/i,
    ) as HTMLInputElement
    const failingPdf = new File(['%PDF-1.4 broken'], 'corrupt_scan.pdf', {
      type: 'application/pdf',
    })

    await act(async () => {
      await user.upload(fileInput, failingPdf)
    })

    await waitFor(() => {
      expect(
        screen.getByText(/All providers failed to parse schedule/i),
      ).toBeInTheDocument()
    })

    // Existing 3 shifts must STILL be preserved (never wiped by failed upload)
    expect(
      screen.getByText(/You already have 3 active shift\(s\) loaded/i),
    ).toBeInTheDocument()
  })
})
