import type { SchedulePreset, WorkerProfile } from '../types/shift'

/**
 * Synthetic demonstration workers only (no real worker data).
 */
export const DEMO_WORKERS: WorkerProfile[] = [
  {
    worker_id: 'W001',
    worker_name: 'Ada Okoye',
    role_summary: 'Retail & Logistics (Multi-employer)',
  },
  {
    worker_id: 'W004',
    worker_name: 'Chidi Mensah',
    role_summary: 'Retail & Food Service',
  },
  {
    worker_id: 'W005',
    worker_name: 'Zanele Dlamini',
    role_summary: 'Healthcare & Cafe',
  },
  {
    worker_id: 'W008',
    worker_name: 'Tariq Bello',
    role_summary: 'Multi-currency (USD + EUR)',
  },
  {
    worker_id: 'W009',
    worker_name: 'Kemi Adebayo',
    role_summary: 'Manufacturing & Logistics',
  },
  {
    worker_id: 'W011',
    worker_name: 'Lindiwe Phiri',
    role_summary: 'Hospitality & Counter',
  },
]

export const SCHEDULE_PRESETS: SchedulePreset[] = [
  {
    id: 'spec-acceptance',
    title: 'MVP Spec Acceptance Example (§6.1)',
    subtitle:
      'Mon & Tue confirmed ($232.00, 14.5 hrs); Wed held with unknown break.',
    workerId: 'W001',
    fileName: 'spec_acceptance_example.csv',
    scenarioTag: '14.5 hrs • $232.00 + 1 incomplete',
    initialConfirmations: ['confirmed', 'confirmed', 'needs_review'],
    csvText: [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status',
      '2026-11-09,09:00,17:00,30,BrightMart,Store A,sales floor,16.00,USD,scheduled',
      '2026-11-10,10:00,18:00,60,BrightMart,Store A,sales floor,16.00,USD,scheduled',
      '2026-11-11,09:00,17:00,,BrightMart,Store A,sales floor,16.00,USD,scheduled',
    ].join('\n'),
  },
  {
    id: 's001-overnight',
    title: 'S001 — Reference Overnight Schedule',
    subtitle:
      'Includes an overnight shift (22:00–06:00). Starts unconfirmed for review.',
    workerId: 'W001',
    fileName: 'S001_schedule.csv',
    scenarioTag: 'Overnight • $384.00 when confirmed',
    csvText: [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status,stated_hours',
      '2026-11-03,08:00,16:00,0,BrightMart,Store A,sales floor,15.00,USD,scheduled,8.0',
      '2026-11-04,09:00,17:00,0,BrightMart,Store A,sales floor,15.00,USD,scheduled,8.0',
      '2026-11-05,22:00,06:00,0,SwiftLogistics,Warehouse B,dispatch,18.00,USD,scheduled,8.0',
    ].join('\n'),
  },
  {
    id: 's005-commute-minutes',
    title: 'S005 — Commute Gap & Exact Minutes',
    subtitle:
      '10-minute gap between Hospital Annex & Cafe Downtown, plus 4h 50m shift.',
    workerId: 'W005',
    fileName: 'S005_schedule.csv',
    scenarioTag: 'Commute <30m • Exact minutes',
    initialConfirmations: ['confirmed', 'confirmed', 'confirmed'],
    csvText: [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status,stated_hours',
      '2026-11-04,07:00,12:00,0,CityCare Hospital,Hospital Annex,patient support,15.00,USD,scheduled,5.0',
      '2026-11-04,12:10,17:00,0,Central Cafe Group,Cafe Downtown,counter,13.00,USD,scheduled,4.83',
      '2026-11-06,08:00,16:00,30,CityCare Hospital,Hospital Annex,patient support,15.00,USD,scheduled,8.0',
    ].join('\n'),
  },
  {
    id: 's004-overlap',
    title: 'S004 — Overlapping Shifts Conflict',
    subtitle: 'Two shifts overlap on Tuesday (08:00–14:00 & 12:00–18:00).',
    workerId: 'W004',
    fileName: 'S004_schedule.csv',
    scenarioTag: 'Overlap Error (FL01)',
    initialConfirmations: ['confirmed', 'confirmed', 'confirmed'],
    csvText: [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status,stated_hours',
      '2026-11-03,08:00,14:00,0,BrightMart,Retail X,sales floor,14.00,USD,scheduled,6.0',
      '2026-11-03,12:00,18:00,0,Diner Y Co,Diner Y,kitchen,15.00,USD,scheduled,6.0',
      '2026-11-05,09:00,13:00,0,BrightMart,Retail X,sales floor,14.00,USD,scheduled,4.0',
    ].join('\n'),
  },
  {
    id: 's009-duplicate',
    title: 'Duplicate & Cancelled Mix (Scenario A + S015)',
    subtitle:
      'Contains a duplicate shift held for review and a cancelled shift ($0.00).',
    workerId: 'W009',
    fileName: 'duplicate_and_cancelled_demo.csv',
    scenarioTag: 'Duplicate (FL04) • Cancelled (FL05)',
    initialConfirmations: ['confirmed', 'confirmed', 'confirmed', 'confirmed'],
    csvText: [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status',
      '2026-11-09,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,scheduled',
      '2026-11-09,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,scheduled',
      '2026-11-10,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,scheduled',
      '2026-11-11,08:00,16:00,30,SwiftLogistics,Depot,loading,14.00,USD,cancelled',
    ].join('\n'),
  },
  {
    id: 's028-multicurrency',
    title: 'S028 — Multi-Currency Week (USD + EUR)',
    subtitle:
      'Shifts in USD and EUR in the same week; totals must never be mixed.',
    workerId: 'W008',
    fileName: 'S028_schedule.csv',
    scenarioTag: 'Separate USD & EUR totals',
    initialConfirmations: ['confirmed', 'confirmed', 'confirmed', 'confirmed'],
    csvText: [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status,stated_hours',
      '2026-11-16,10:00,18:00,30,Kiosk Co,Mall Kiosk,sales floor,13.50,USD,scheduled,8.0',
      '2026-11-17,10:00,18:00,30,Kiosk Co,Mall Kiosk,sales floor,13.50,USD,scheduled,8.0',
      '2026-11-18,10:00,18:00,30,Kiosk Co,Mall Kiosk,sales floor,12.00,EUR,scheduled,8.0',
      '2026-11-19,10:00,18:00,30,Kiosk Co,Mall Kiosk,sales floor,12.00,EUR,scheduled,8.0',
    ].join('\n'),
  },
  {
    id: 's029-missing-rate',
    title: 'S029 & Missing Info — Incomplete Earnings',
    subtitle:
      'Confirmed shifts with missing rate and unknown location (commute not assessed).',
    workerId: 'W011',
    fileName: 'missing_info_demo.csv',
    scenarioTag: 'Missing rate • Not assessed',
    initialConfirmations: ['confirmed', 'confirmed', 'confirmed'],
    csvText: [
      'shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status',
      '2026-11-16,08:00,16:00,30,PackRight,Packing Plant,packing,15.00,USD,scheduled',
      '2026-11-17,08:00,16:00,30,PackRight,Packing Plant,packing,,USD,scheduled',
      '2026-11-17,16:15,20:00,0,PackRight,Unlisted Pop-up Site,packing,15.00,USD,scheduled',
    ].join('\n'),
  },
]
