import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Image as ImageIcon,
  Layers,
  Loader2,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useSchedule } from '../context/scheduleContextStore'
import { SCHEDULE_PRESETS } from '../data/syntheticSchedules'
import type { UploadMode } from '../types/shift'
import { CSV_TEMPLATE_CONTENT } from '../utils/csvParser'

export function UploadPage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const {
    workerId,
    shifts,
    uploadedFiles,
    uploadCsvText,
    extractAndUploadFile,
    loadPresetSchedule,
    clearWorkerSchedule,
  } = useSchedule()

  const [isDragging, setIsDragging] = useState(false)
  const [isExtracting, setIsExtracting] = useState(false)
  const [uploadMode, setUploadMode] = useState<UploadMode>('append')
  const [replaceConfirmed, setReplaceConfirmed] = useState(false)
  const [confirmClearOpen, setConfirmClearOpen] = useState(false)
  const [uploadErrors, setUploadErrors] = useState<string[]>([])
  const [uploadWarnings, setUploadWarnings] = useState<string[]>([])
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const hasExistingShifts = shifts.length > 0
  const effectiveMode: UploadMode = hasExistingShifts ? uploadMode : 'replace'
  const replaceBlocked =
    hasExistingShifts && effectiveMode === 'replace' && !replaceConfirmed

  const processFile = async (file: File) => {
    setUploadErrors([])
    setUploadWarnings([])
    setSuccessMessage(null)

    if (replaceBlocked) {
      setUploadErrors([
        'Please check the replacement confirmation box before replacing your existing schedule.',
      ])
      return
    }

    const lowerName = file.name.toLowerCase()
    const isPdfOrImage =
      lowerName.endsWith('.pdf') ||
      file.type === 'application/pdf' ||
      /\.(png|jpe?g|webp)$/i.test(lowerName) ||
      ['image/png', 'image/jpeg', 'image/webp'].includes(file.type)

    if (isPdfOrImage) {
      setIsExtracting(true)
      try {
        const result = await extractAndUploadFile(file, {
          mode: effectiveMode,
        })
        if (!result.ok) {
          setUploadErrors(
            result.errors.length > 0
              ? result.errors
              : ['Failed to extract shifts from this document.'],
          )
          setUploadWarnings(result.warnings)
          return
        }
        setUploadWarnings(result.warnings)
        setReplaceConfirmed(false)
        const providerName = result.extraction?.active_provider
        const providerText = providerName ? ` via ${providerName}` : ''
        setSuccessMessage(
          effectiveMode === 'append' && hasExistingShifts
            ? `Extracted ${result.shifts.length} shift(s) from "${file.name}"${providerText} and added to your schedule. All AI-extracted shifts are marked "Needs Review" and require individual worker confirmation.`
            : `Extracted ${result.shifts.length} shift(s) from "${file.name}"${providerText}. All AI-extracted shifts are marked "Needs Review" and require individual worker confirmation.`,
        )
        navigate('/review')
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : 'Unexpected extraction error.'
        setUploadErrors([`Failed to process "${file.name}": ${msg}`])
      } finally {
        setIsExtracting(false)
      }
      return
    }

    if (!lowerName.endsWith('.csv') && file.type !== 'text/csv') {
      setUploadErrors([
        `Unsupported file format "${file.name}". Please upload a CSV schedule (.csv), PDF roster (.pdf), or schedule photo (.png, .jpg, .webp).`,
      ])
      return
    }

    try {
      const text =
        typeof file.text === 'function'
          ? await file.text()
          : await new Promise<string>((resolve, reject) => {
              const reader = new FileReader()
              reader.onload = () => resolve(String(reader.result ?? ''))
              reader.onerror = () => reject(reader.error)
              reader.readAsText(file)
            })
      const result = uploadCsvText(text, file.name, { mode: effectiveMode })
      if (!result.ok) {
        setUploadErrors(result.errors)
        return
      }
      setUploadWarnings(result.warnings)
      setReplaceConfirmed(false)
      setSuccessMessage(
        effectiveMode === 'append' && hasExistingShifts
          ? `Added ${result.shifts.length} shift(s) from "${file.name}" to your existing schedule. New shifts start as unconfirmed for review.`
          : `Imported ${result.shifts.length} shift(s) from "${file.name}". All newly uploaded shifts start as unconfirmed for your review.`,
      )
      navigate('/review')
    } catch {
      setUploadErrors([
        `Unable to read "${file.name}". Ensure it is a readable UTF-8 CSV file.`,
      ])
    }
  }

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      void processFile(file)
    }
    e.target.value = ''
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) {
      void processFile(file)
    }
  }

  const handleDownloadTemplate = () => {
    const blob = new Blob([CSV_TEMPLATE_CONTENT], {
      type: 'text/csv;charset=utf-8;',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', 'workclarity_schedule_template.csv')
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const handlePresetClick = (presetId: string) => {
    setUploadErrors([])
    setUploadWarnings([])
    setReplaceConfirmed(false)
    const result = loadPresetSchedule(presetId)
    if (result?.ok) {
      navigate('/review')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Upload Schedule
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Upload one or more CSV schedules (including separate files from
            different employers) for{' '}
            <span className="font-mono font-semibold text-slate-800">
              {workerId}
            </span>
            . Newly imported shifts stay unconfirmed until you review them.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleDownloadTemplate}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-xs hover:bg-slate-50"
          >
            <Download className="h-4 w-4 text-slate-500" />
            Download CSV Template
          </button>
          {hasExistingShifts && !confirmClearOpen && (
            <button
              type="button"
              onClick={() => setConfirmClearOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3.5 py-2 text-xs font-semibold text-rose-700 shadow-xs hover:bg-rose-50"
            >
              <Trash2 className="h-4 w-4" />
              Clear Schedule
            </button>
          )}
        </div>
      </div>

      {confirmClearOpen && hasExistingShifts && (
        <div
          role="alert"
          className="flex flex-col justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-900 sm:flex-row sm:items-center"
        >
          <span>
            Clear all <strong>{shifts.length}</strong> shift(s) and edits for{' '}
            <strong>{workerId}</strong>? This cannot be undone.
          </span>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={() => setConfirmClearOpen(false)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                clearWorkerSchedule()
                setConfirmClearOpen(false)
                setReplaceConfirmed(false)
                setUploadMode('append')
              }}
              className="rounded-lg bg-rose-700 px-3 py-1.5 font-semibold text-white hover:bg-rose-800"
            >
              Confirm Clear
            </button>
          </div>
        </div>
      )}

      {/* Multi-Employer Upload Mode Controls */}
      {hasExistingShifts && (
        <section
          aria-label="Import mode"
          className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Layers className="h-4 w-4 text-teal-600" />
            <span>
              You already have {shifts.length} active shift(s) loaded
            </span>
          </div>
          {uploadedFiles.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              Loaded schedules:{' '}
              <span className="font-medium text-slate-700">
                {uploadedFiles.join(', ')}
              </span>
            </p>
          )}

          <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <label
              className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 text-xs transition ${
                uploadMode === 'append'
                  ? 'border-emerald-500 bg-emerald-50/50 text-slate-900'
                  : 'border-slate-200 bg-slate-50/50 text-slate-600 hover:border-slate-300'
              }`}
            >
              <input
                type="radio"
                name="upload-mode"
                value="append"
                checked={uploadMode === 'append'}
                onChange={() => {
                  setUploadMode('append')
                  setReplaceConfirmed(false)
                  setUploadErrors([])
                }}
                className="mt-0.5 accent-emerald-600"
              />
              <div>
                <div className="font-semibold text-slate-900">
                  Add to existing schedule (recommended)
                </div>
                <div className="mt-0.5 text-slate-600">
                  Keep your {shifts.length} existing shift(s) and combine shifts
                  from another employer or week. Duplicate shifts are held
                  automatically.
                </div>
              </div>
            </label>

            <label
              className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 text-xs transition ${
                uploadMode === 'replace'
                  ? 'border-amber-500 bg-amber-50/60 text-slate-900'
                  : 'border-slate-200 bg-slate-50/50 text-slate-600 hover:border-slate-300'
              }`}
            >
              <input
                type="radio"
                name="upload-mode"
                value="replace"
                checked={uploadMode === 'replace'}
                onChange={() => {
                  setUploadMode('replace')
                  setReplaceConfirmed(false)
                  setUploadErrors([])
                }}
                className="mt-0.5 accent-amber-600"
              />
              <div>
                <div className="font-semibold text-slate-900">
                  Replace existing schedule
                </div>
                <div className="mt-0.5 text-slate-600">
                  Discard all current shifts and worker edits for {workerId} and
                  start fresh with the new CSV file.
                </div>
              </div>
            </label>
          </div>

          {uploadMode === 'replace' && (
            <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <div className="space-y-2">
                  <p className="font-semibold">
                    Warning: Replacing will permanently remove {shifts.length}{' '}
                    existing shift(s) and any corrections you made.
                  </p>
                  <label className="flex cursor-pointer items-center gap-2 font-medium">
                    <input
                      type="checkbox"
                      checked={replaceConfirmed}
                      onChange={(e) => {
                        setReplaceConfirmed(e.target.checked)
                        if (e.target.checked) setUploadErrors([])
                      }}
                      className="h-4 w-4 rounded border-amber-400 accent-amber-600"
                    />
                    <span>
                      Confirm: replace all existing shifts for {workerId}
                    </span>
                  </label>
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Upload Dropzone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!isExtracting) setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={isExtracting ? undefined : handleDrop}
        className={`rounded-2xl border-2 border-dashed p-8 text-center transition ${
          isExtracting
            ? 'border-indigo-300 bg-indigo-50/40'
            : isDragging
              ? 'border-emerald-500 bg-emerald-50/70'
              : 'border-slate-300 bg-white hover:border-slate-400'
        }`}
      >
        {isExtracting ? (
          <div className="space-y-3 py-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-100 text-indigo-700">
              <Loader2 className="h-7 w-7 animate-spin" />
            </div>
            <h2 className="text-base font-semibold text-slate-900">
              Extracting shifts with multimodal AI…
            </h2>
            <p className="mx-auto max-w-md text-xs text-slate-500">
              Processing document structure, extracting shift times and breaks,
              and verifying worker attribution safeguards.
            </p>
          </div>
        ) : (
          <>
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-slate-900 text-emerald-400">
              <Upload className="h-6 w-6" />
            </div>
            <h2 className="mt-4 text-base font-semibold text-slate-900">
              {hasExistingShifts && effectiveMode === 'append'
                ? 'Drop schedule file (CSV, PDF, or photo) to add shifts'
                : 'Drop your schedule file (CSV, PDF, or photo) here'}
            </h2>
            <p className="mx-auto mt-1 max-w-md text-xs text-slate-500">
              Supports CSV schedule files, PDF rosters, and PNG/JPEG/WebP photos.
              All extracted shifts require individual review and confirmation.
            </p>

            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv,application/pdf,.pdf,image/png,.png,image/jpeg,.jpg,.jpeg,image/webp,.webp"
              onChange={handleFileChange}
              disabled={replaceBlocked || isExtracting}
              className="sr-only"
              aria-label="Choose CSV schedule file"
            />

            <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                disabled={replaceBlocked || isExtracting}
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-600"
              >
                <FileSpreadsheet className="h-4 w-4" />
                {hasExistingShifts && effectiveMode === 'append'
                  ? 'Select CSV File to Add'
                  : 'Select CSV File'}
              </button>
            </div>

            {replaceBlocked && (
              <p className="mt-3 text-xs font-medium text-amber-800">
                Check the replacement confirmation box above to enable upload.
              </p>
            )}
          </>
        )}
      </div>

      {/* Feedback Alerts */}
      {uploadErrors.length > 0 && (
        <div
          role="alert"
          className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"
        >
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
            <div className="space-y-1">
              <p className="font-semibold">Unable to process schedule file</p>
              <ul className="list-disc pl-4 text-xs text-rose-800">
                {uploadErrors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {uploadWarnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
          <p className="font-semibold">CSV import notes</p>
          <ul className="mt-1 list-disc pl-4">
            {uploadWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {successMessage && (
        <div className="flex items-center gap-2.5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Synthetic Demo Schedules */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-teal-600" />
              <h2 className="text-base font-semibold text-slate-900">
                Synthetic Demonstration Schedules
              </h2>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Load curated synthetic test schedules from the WorkClarity dataset
              to verify every MVP business rule with the calculation service.
            </p>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {SCHEDULE_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => handlePresetClick(preset.id)}
              className="group flex flex-col justify-between rounded-xl border border-slate-200 bg-slate-50/60 p-4 text-left transition hover:border-emerald-400 hover:bg-emerald-50/30"
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-slate-900 group-hover:text-emerald-900">
                    {preset.title}
                  </span>
                  <span className="shrink-0 rounded-md bg-slate-200/80 px-2 py-0.5 font-mono text-[11px] font-medium text-slate-700">
                    {preset.workerId}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-600">{preset.subtitle}</p>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="rounded-md bg-teal-50 px-2 py-0.5 text-[11px] font-medium text-teal-800 ring-1 ring-teal-600/20">
                  {preset.scenarioTag}
                </span>
                <span className="text-xs font-semibold text-emerald-700 group-hover:underline">
                  Load &amp; Review →
                </span>
              </div>
            </button>
          ))}
        </div>
      </section>

      {/* Multimodal AI Extraction Feature Card */}
      <section className="rounded-2xl border border-indigo-200 bg-indigo-50/50 p-4 text-xs text-slate-700">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-indigo-700">
            <ImageIcon className="h-4 w-4" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-900">
                Multimodal AI Schedule Extraction Active
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-800">
                <CheckCircle2 className="h-3 w-3" />
                Connected
              </span>
            </div>
            <p className="mt-1 leading-relaxed text-slate-600">
              WorkClarity extracts shifts directly from PDF rosters and schedule
              photos using multimodal AI with automatic provider failover. To
              protect worker earnings, all AI-extracted shifts are held for
              individual review and excluded from earnings calculations until
              confirmed.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
