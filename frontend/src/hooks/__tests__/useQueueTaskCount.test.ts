import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

const mockToast = vi.fn()
vi.mock('@/components/shared/Toast', () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}))

const mockBatchStatus = vi.fn()
const mockProbeStatus = vi.fn()
const mockExtractStatus = vi.fn()
const mockScannerStatus = vi.fn()
const mockSummary = vi.fn()
const mockStandaloneStatus = vi.fn()
const mockRefreshWanted = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getWantedBatchStatus: (...args: unknown[]) => mockBatchStatus(...args),
    getBatchProbeStatus: (...args: unknown[]) => mockProbeStatus(...args),
    getBatchExtractStatus: (...args: unknown[]) => mockExtractStatus(...args),
    getScannerStatus: (...args: unknown[]) => mockScannerStatus(...args),
    getWantedSummary: (...args: unknown[]) => mockSummary(...args),
    getStandaloneStatus: (...args: unknown[]) => mockStandaloneStatus(...args),
    refreshWanted: (...args: unknown[]) => mockRefreshWanted(...args),
  }
})

import { useQueueTaskCount, useRefreshWanted } from '../useWantedApi'

function renderWithClient(hook: () => unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children)
  return { ...renderHook(hook, { wrapper }), qc }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockBatchStatus.mockResolvedValue({ running: false, total: 0, processed: 0 })
  mockProbeStatus.mockResolvedValue({ running: false, total: 0, processed: 0 })
  mockExtractStatus.mockResolvedValue({ running: false, total: 0, processed: 0 })
  mockScannerStatus.mockResolvedValue({
    is_scanning: false, is_searching: false,
    progress: { current: 0, total: 0, phase: '' },
    last_scan_at: null, last_search_at: null, last_summary: null,
  })
  mockSummary.mockResolvedValue({ total: 0, by_status: {}, by_type: {}, scan_running: false })
  mockStandaloneStatus.mockResolvedValue({ scanner_scanning: false })
})

describe('useQueueTaskCount', () => {
  it('is 0 when nothing runs', async () => {
    const { result } = renderWithClient(() => useQueueTaskCount())
    await waitFor(() => expect(result.current).toBe(0))
  })

  it('counts a batch probe run by its remaining items', async () => {
    mockProbeStatus.mockResolvedValue({ running: true, total: 10, processed: 4 })
    const { result } = renderWithClient(() => useQueueTaskCount())
    await waitFor(() => expect(result.current).toBe(6))
  })

  it('counts a wanted scan from scanner-status progress', async () => {
    mockScannerStatus.mockResolvedValue({
      is_scanning: true, is_searching: false,
      progress: { current: 2, total: 5, phase: '' },
      last_scan_at: null, last_search_at: null, last_summary: null,
    })
    const { result } = renderWithClient(() => useQueueTaskCount())
    await waitFor(() => expect(result.current).toBe(3))
  })

  it('counts a scan flagged by wanted-summary even while scanner-status is stale', async () => {
    // Regression: the Wanted header showed "Scanning…" (summary.scan_running)
    // while the Activity badge stayed 0 because the badge never read the summary.
    mockScannerStatus.mockResolvedValue({
      is_scanning: false, is_searching: false,
      progress: { current: 0, total: 0, phase: '' },
      last_scan_at: null, last_search_at: null, last_summary: null,
    })
    mockSummary.mockResolvedValue({
      total: 0, by_status: {}, by_type: {}, scan_running: true,
      scan_progress: { current: 1, total: 4 },
    })
    const { result } = renderWithClient(() => useQueueTaskCount())
    await waitFor(() => expect(result.current).toBe(3))
  })

  it('counts an in-flight standalone folder scan', async () => {
    mockStandaloneStatus.mockResolvedValue({ scanner_scanning: true })
    const { result } = renderWithClient(() => useQueueTaskCount())
    await waitFor(() => expect(result.current).toBe(1))
  })

  it('sums every concurrent run', async () => {
    mockBatchStatus.mockResolvedValue({ running: true, total: 8, processed: 5 })
    mockProbeStatus.mockResolvedValue({ running: true, total: 3, processed: 1 })
    mockScannerStatus.mockResolvedValue({
      is_scanning: true, is_searching: false,
      progress: { current: 0, total: 4, phase: '' },
      last_scan_at: null, last_search_at: null, last_summary: null,
    })
    mockStandaloneStatus.mockResolvedValue({ scanner_scanning: true })
    const { result } = renderWithClient(() => useQueueTaskCount())
    await waitFor(() => expect(result.current).toBe(3 + 2 + 4 + 1))
  })
})

describe('useRefreshWanted', () => {
  it('invalidates scanner-status so the Activity badge flips at scan start', async () => {
    mockRefreshWanted.mockResolvedValue({ status: 'scan_started' })
    const { result, qc } = renderWithClient(() => useRefreshWanted())
    const spy = vi.spyOn(qc, 'invalidateQueries')
    result.current.mutate(undefined)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(spy).toHaveBeenCalledWith({ queryKey: ['scanner-status'] })
    expect(mockToast).not.toHaveBeenCalled()
  })

  it('toasts when the backend rejects the scan (409)', async () => {
    mockRefreshWanted.mockRejectedValue(new Error('Scan already running'))
    const { result } = renderWithClient(() => useRefreshWanted())
    result.current.mutate(undefined)
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(mockToast).toHaveBeenCalledWith('wanted.refresh_failed', 'error')
  })
})
