import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useHealth, useUpdateInfo } from '@/hooks/useApi'
import { useProviderHealth } from '@/hooks/useProvidersApi'
import {
  useScannerStatus,
  useWantedBatchStatus,
  useWantedBatchProbeStatus,
} from '@/hooks/useWantedApi'
import { useSchedulerJobs } from '@/hooks/useSchedulerJobs'

// Minimal i18next stand-in: defaults win, and {{placeholders}} are filled from
// the options object so hover-text assertions can compare exact strings.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      if (typeof opts === 'string') return opts
      const values = opts as Record<string, unknown> | undefined
      const fallback = values?.defaultValue ?? key.split('.').pop() ?? key
      return String(fallback).replace(/\{\{(\w+)\}\}/g, (_, name) => String(values?.[name] ?? ''))
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

const HEALTHY_STATES = {
  backend: 'alive',
  database: 'ok',
  sonarr: 'ok',
  radarr: 'ok',
  jellyfin: 'ok',
}

vi.mock('@/hooks/useApi', () => ({
  useHealth: vi.fn(() => ({
    data: { status: 'healthy', version: '0.41.8', states: HEALTHY_STATES },
  })),
  useUpdateInfo: vi.fn(() => ({ data: null })),
}))

vi.mock('@/hooks/useWantedApi', () => ({
  useScannerStatus: vi.fn(() => ({ data: { is_scanning: false, is_searching: false } })),
  useWantedBatchStatus: vi.fn(() => ({ data: { running: false } })),
  useWantedBatchProbeStatus: vi.fn(() => ({ data: { running: false } })),
}))

vi.mock('@/hooks/useSchedulerJobs', () => ({
  useSchedulerJobs: vi.fn(() => ({
    data: {
      jobs: [
        { id: 'wanted_scanner', paused: false },
        { id: 'wanted_search', paused: false },
      ],
    },
  })),
}))

vi.mock('@/hooks/useProvidersApi', () => ({
  useProviderHealth: vi.fn(() => ({ data: { providers: [] } })),
}))

import { StatusBar } from '../StatusBar'

/** The footer is made of <Link>s, so every render needs a router. */
const renderBar = () => render(<MemoryRouter><StatusBar /></MemoryRouter>)

const provider = (name: string, over: Partial<Record<string, unknown>> = {}) => ({
  name,
  healthy: true,
  enabled: true,
  initialized: true,
  success_rate: 1,
  avg_response_time_ms: 100,
  last_response_time_ms: 100,
  auto_disabled: false,
  disabled_until: '',
  consecutive_failures: 0,
  total_searches: 20,
  circuit_breaker_state: 'closed',
  throttled_until: null,
  throttle_reason: null,
  ...over,
})

describe('StatusBar', () => {
  beforeEach(() => {
    vi.mocked(useUpdateInfo).mockReturnValue({ data: null })
    vi.mocked(useHealth).mockReturnValue({
      data: { status: 'healthy', version: '0.41.8', states: HEALTHY_STATES },
    })
    vi.mocked(useScannerStatus).mockReturnValue({ data: { is_scanning: false, is_searching: false } })
    vi.mocked(useWantedBatchStatus).mockReturnValue({ data: { running: false } })
    vi.mocked(useWantedBatchProbeStatus).mockReturnValue({ data: { running: false } })
    vi.mocked(useSchedulerJobs).mockReturnValue({
      data: {
        jobs: [
          { id: 'wanted_scanner', paused: false },
          { id: 'wanted_search', paused: false },
        ],
      },
    })
    vi.mocked(useProviderHealth).mockReturnValue({ data: { providers: [] } })
  })

  // ─── Version / update popover ───────────────────────────────────────────────

  it('renders version as plain span when no update available', () => {
    renderBar()
    const version = screen.getByTestId('status-bar-version')
    expect(version.tagName).toBe('SPAN')
    expect(version).toHaveTextContent('0.41.8')
    expect(version).toHaveAttribute('title', 'Running v0.41.8')
  })

  it('renders version as button when update available', () => {
    vi.mocked(useUpdateInfo).mockReturnValue({
      data: { available: true, latest: '0.42.0', current: '0.41.8', url: 'https://github.com/Nreel/sublarr/releases/tag/v0.42.0' },
    })
    renderBar()
    const version = screen.getByTestId('status-bar-version')
    expect(version.tagName).toBe('BUTTON')
    expect(version).toHaveAttribute('title', 'Running v0.41.8 — update to v0.42.0 available, click for release notes')
  })

  it('shows update dot when update available', () => {
    vi.mocked(useUpdateInfo).mockReturnValue({
      data: { available: true, latest: '0.42.0', current: '0.41.8', url: 'https://github.com/Nreel/sublarr/releases/tag/v0.42.0' },
    })
    renderBar()
    expect(screen.getByTestId('status-bar-update-dot')).toBeInTheDocument()
  })

  it('does not show update dot when no update available', () => {
    renderBar()
    expect(screen.queryByTestId('status-bar-update-dot')).not.toBeInTheDocument()
  })

  it('opens popover when version button is clicked', () => {
    vi.mocked(useUpdateInfo).mockReturnValue({
      data: { available: true, latest: '0.42.0', current: '0.41.8', url: 'https://github.com/Nreel/sublarr/releases/tag/v0.42.0' },
    })
    renderBar()
    expect(screen.queryByTestId('status-bar-update-popover')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('status-bar-version'))
    expect(screen.getByTestId('status-bar-update-popover')).toBeInTheDocument()
    expect(screen.getByTestId('status-bar-update-popover')).toHaveTextContent('0.42.0')
  })

  it('popover contains GitHub link', () => {
    vi.mocked(useUpdateInfo).mockReturnValue({
      data: { available: true, latest: '0.42.0', current: '0.41.8', url: 'https://github.com/Nreel/sublarr/releases/tag/v0.42.0' },
    })
    renderBar()
    fireEvent.click(screen.getByTestId('status-bar-version'))
    const link = screen.getByRole('link', { name: 'view_release' })
    expect(link).toHaveAttribute('href', 'https://github.com/Nreel/sublarr/releases/tag/v0.42.0')
    expect(link).toHaveAttribute('target', '_blank')
  })

  // ─── Block 1: crucial states ────────────────────────────────────────────────

  it('shows the five crucial states as dots with the mapped colours', () => {
    vi.mocked(useHealth).mockReturnValue({
      data: {
        status: 'healthy',
        version: '0.41.8',
        states: {
          backend: 'alive',
          database: 'ok',
          sonarr: 'down',
          radarr: 'not_configured',
          jellyfin: 'timeout',
        },
      },
    })
    renderBar()
    expect(screen.getByTestId('status-bar-state-backend')).toHaveAttribute('data-state', 'alive')
    expect(screen.getByTestId('status-bar-state-backend')).toHaveStyle({ backgroundColor: 'var(--success)' })
    expect(screen.getByTestId('status-bar-state-database')).toHaveStyle({ backgroundColor: 'var(--success)' })
    expect(screen.getByTestId('status-bar-state-sonarr')).toHaveAttribute('data-state', 'down')
    expect(screen.getByTestId('status-bar-state-sonarr')).toHaveStyle({ backgroundColor: 'var(--error)' })
    expect(screen.getByTestId('status-bar-state-radarr')).toHaveAttribute('data-state', 'not_configured')
    expect(screen.getByTestId('status-bar-state-radarr')).toHaveStyle({ backgroundColor: 'var(--text-muted)' })
    expect(screen.getByTestId('status-bar-state-jellyfin')).toHaveAttribute('data-state', 'timeout')
    expect(screen.getByTestId('status-bar-state-jellyfin')).toHaveStyle({ backgroundColor: 'var(--warning)' })
    expect(screen.getByTestId('status-bar-health')).toHaveTextContent('backend')
    expect(screen.getByTestId('status-bar-health')).toHaveTextContent('db')
    expect(screen.getByTestId('status-bar-health')).toHaveTextContent('Sonarr')
    expect(screen.getByTestId('status-bar-health')).toHaveTextContent('Radarr')
    expect(screen.getByTestId('status-bar-health')).toHaveTextContent('Jellyfin')
  })

  it('links the state row to /health and describes every state', () => {
    vi.mocked(useHealth).mockReturnValue({
      data: {
        status: 'unhealthy',
        version: '0.41.8',
        states: {
          backend: 'alive',
          database: 'problem',
          sonarr: 'down',
          radarr: 'not_configured',
          jellyfin: 'ok',
        },
      },
    })
    renderBar()
    const health = screen.getByTestId('status-bar-health')
    expect(health.tagName).toBe('A')
    expect(health).toHaveAttribute('href', '/health')
    expect(health).toHaveAttribute(
      'title',
      'Backend: alive · DB: problem · Sonarr: down · Radarr: not configured · Jellyfin: ok — open health overview',
    )
  })

  it('falls back to a single Online dot when states are absent', () => {
    vi.mocked(useHealth).mockReturnValue({ data: { status: 'healthy', version: '0.41.8' } })
    renderBar()
    expect(screen.queryByTestId('status-bar-state-sonarr')).not.toBeInTheDocument()
    const health = screen.getByTestId('status-bar-health')
    expect(health).toHaveTextContent('Online')
    expect(health).toHaveAttribute('href', '/health')
    expect(health).toHaveAttribute('title', 'Backend Online — open health overview')
  })

  it('falls back to Offline when the backend reports unhealthy without states', () => {
    vi.mocked(useHealth).mockReturnValue({ data: { status: 'unhealthy' } })
    renderBar()
    const health = screen.getByTestId('status-bar-health')
    expect(health).toHaveTextContent('Offline')
    expect(health).toHaveAttribute('title', 'Backend Offline — open health overview')
  })

  // ─── Block 2: automation ────────────────────────────────────────────────────

  it('labels automation running when a scan is in flight', () => {
    vi.mocked(useScannerStatus).mockReturnValue({ data: { is_scanning: true, is_searching: false } })
    renderBar()
    const automation = screen.getByTestId('status-bar-automation')
    expect(automation).toHaveTextContent('Automation: running')
    expect(automation).toHaveAttribute('href', '/settings/automation')
    expect(automation).toHaveAttribute('title', 'A scan, search or batch run is in flight — open automation settings')
  })

  it('labels automation event-driven when nothing runs and nothing is paused', () => {
    renderBar()
    const automation = screen.getByTestId('status-bar-automation')
    expect(automation).toHaveTextContent('Automation: event-driven')
    expect(automation).toHaveAttribute('title', 'Nothing running; the scheduler fires on its next scheduled run')
  })

  it('labels automation paused when both pipeline jobs are paused', () => {
    vi.mocked(useSchedulerJobs).mockReturnValue({
      data: {
        jobs: [
          { id: 'wanted_scanner', paused: true },
          { id: 'wanted_search', paused: true },
        ],
      },
    })
    renderBar()
    const automation = screen.getByTestId('status-bar-automation')
    expect(automation).toHaveTextContent('Automation: paused')
    expect(automation).toHaveAttribute(
      'title',
      'Both pipeline jobs are paused (wanted_scanner, wanted_search) — nothing runs until resumed',
    )
  })

  it('names the scanner when only the scanner is paused', () => {
    vi.mocked(useSchedulerJobs).mockReturnValue({
      data: {
        jobs: [
          { id: 'wanted_scanner', paused: true },
          { id: 'wanted_search', paused: false },
        ],
      },
    })
    renderBar()
    const automation = screen.getByTestId('status-bar-automation')
    expect(automation).toHaveTextContent('Automation: scanner paused')
    expect(automation).toHaveAttribute('title', 'Scanner paused (wanted_scanner), search still scheduled')
  })

  it('names the search when only the search job is paused', () => {
    vi.mocked(useSchedulerJobs).mockReturnValue({
      data: {
        jobs: [
          { id: 'wanted_scanner', paused: false },
          { id: 'wanted_search', paused: true },
        ],
      },
    })
    renderBar()
    const automation = screen.getByTestId('status-bar-automation')
    expect(automation).toHaveTextContent('Automation: search paused')
    expect(automation).toHaveAttribute('title', 'Search paused (wanted_search), scanner still scheduled')
  })

  // ─── Block 5: throttled providers ───────────────────────────────────────────

  it('shows a green no-throttled segment when nothing is throttled', () => {
    renderBar()
    const throttled = screen.getByTestId('status-bar-throttled')
    expect(throttled).toBeInTheDocument()
    expect(throttled).toHaveTextContent('No throttled providers')
    expect(throttled).toHaveAttribute('href', '/providers')
    expect(throttled).toHaveAttribute(
      'title',
      'No provider is circuit-open, rate-limited or auto-disabled — open providers',
    )
    expect(throttled.firstElementChild).toHaveStyle({ backgroundColor: 'var(--success)' })
  })

  it('shows throttled providers warning', () => {
    vi.mocked(useProviderHealth).mockReturnValue({
      data: {
        providers: [
          provider('opensubtitles', { healthy: false, circuit_breaker_state: 'open', success_rate: 0 }),
          provider('addic7ed', {
            healthy: false,
            throttled_until: '2099-01-01T00:00:00Z',
            throttle_reason: 'rate_limited',
            success_rate: 0,
            consecutive_failures: 5,
          }),
          provider('jimaku'),
        ],
      },
    })
    renderBar()
    const throttled = screen.getByTestId('status-bar-throttled')
    expect(throttled).toBeInTheDocument()
    expect(throttled).toHaveTextContent('2 provider(s) throttled')
    expect(throttled).toHaveAttribute('title', 'opensubtitles, addic7ed — open providers')
    expect(throttled.firstElementChild).toHaveStyle({ backgroundColor: 'var(--warning)' })
  })

  it('treats auto_disabled providers as throttled', () => {
    vi.mocked(useProviderHealth).mockReturnValue({
      data: {
        providers: [
          provider('opensubtitles', {
            healthy: false,
            auto_disabled: true,
            disabled_until: '2099-01-01T00:00:00Z',
            consecutive_failures: 10,
            success_rate: 0,
          }),
        ],
      },
    })
    renderBar()
    const throttled = screen.getByTestId('status-bar-throttled')
    expect(throttled).toBeInTheDocument()
    expect(throttled).toHaveAttribute('title', 'opensubtitles — open providers')
  })

  // ─── Block 6: activity ──────────────────────────────────────────────────────

  it('shows No activity when nothing is running', () => {
    renderBar()
    const activity = screen.getByTestId('status-bar-scanning')
    expect(activity).toBeInTheDocument()
    expect(activity).toHaveTextContent('No activity')
    expect(activity).toHaveAttribute('href', '/activity')
    expect(activity).toHaveAttribute('title', 'No scan or batch activity running')
    expect(activity.firstElementChild).toHaveStyle({ backgroundColor: 'var(--text-muted)' })
    expect(activity.firstElementChild).not.toHaveStyle({ animation: 'dotGlow 1.5s ease-in-out infinite' })
  })

  it('shows the latest-started activity when several runs overlap', () => {
    vi.mocked(useWantedBatchProbeStatus).mockReturnValue({
      data: { running: true, started_at: '2026-11-24T10:00:00Z' },
    })
    vi.mocked(useWantedBatchStatus).mockReturnValue({
      data: { running: true, started_at: '2026-11-24T09:00:00Z' },
    })
    vi.mocked(useScannerStatus).mockReturnValue({
      data: {
        is_scanning: true,
        is_searching: true,
        scan_started_at: '2026-11-24T11:30:00Z',
        search_started_at: '2026-11-24T11:00:00Z',
      },
    })
    renderBar()
    const activity = screen.getByTestId('status-bar-scanning')
    expect(activity).toHaveTextContent('Scanning')
    expect(activity.firstElementChild).toHaveStyle({ animation: 'dotGlow 1.5s ease-in-out infinite' })
    const title = activity.getAttribute('title') ?? ''
    expect(title.startsWith('Last activity: Scanning, started ')).toBe(true)
    expect(title).not.toContain('Extracting')
  })

  it('labels a batch search run and reports its start time', () => {
    vi.mocked(useWantedBatchStatus).mockReturnValue({
      data: { running: true, started_at: '2026-11-24T12:05:00Z' },
    })
    renderBar()
    const activity = screen.getByTestId('status-bar-scanning')
    expect(activity).toHaveTextContent('Batch search')
    const title = activity.getAttribute('title') ?? ''
    expect(title.startsWith('Last activity: Batch search, started ')).toBe(true)
    expect(title).not.toContain('—')
  })

  it('labels a scanner search run', () => {
    vi.mocked(useScannerStatus).mockReturnValue({
      data: { is_scanning: false, is_searching: true, search_started_at: '2026-11-24T12:00:00Z' },
    })
    renderBar()
    const activity = screen.getByTestId('status-bar-scanning')
    expect(activity).toHaveTextContent('Searching')
  })

  it('labels an embedded-sub extraction run', () => {
    vi.mocked(useWantedBatchProbeStatus).mockReturnValue({
      data: { running: true, started_at: '2026-11-24T12:00:00Z' },
    })
    renderBar()
    const activity = screen.getByTestId('status-bar-scanning')
    expect(activity).toHaveTextContent('Extracting')
  })

  it('every footer block carries a hover description', () => {
    renderBar()
    for (const testId of [
      'status-bar-health',
      'status-bar-automation',
      'status-bar-version',
      'status-bar-throttled',
      'status-bar-scanning',
    ]) {
      const el = screen.getByTestId(testId)
      expect(el.getAttribute('title')).toBeTruthy()
    }
  })
})
