import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueuePage } from '../Queue'

const mockBatchStatus = vi.fn()
const mockProbeStatus = vi.fn()
const mockScannerStatus = vi.fn()
const mockStopBatch = vi.fn()
const mockStopProbe = vi.fn()
const mockCancelTask = vi.fn()

vi.mock('@/hooks/useApi', () => ({
  useWantedBatchStatus: () => ({ data: mockBatchStatus() }),
  useWantedBatchProbeStatus: () => ({ data: mockProbeStatus() }),
  useScannerStatus: () => ({ data: mockScannerStatus() }),
  useStopWantedBatch: () => ({ mutate: mockStopBatch, isPending: false }),
  useStopBatchProbe: () => ({ mutate: mockStopProbe, isPending: false }),
  useCancelTask: () => ({ mutate: mockCancelTask, isPending: false }),
}))
vi.mock('@/hooks/useWebSocket', () => ({ useWebSocket: () => undefined }))
vi.mock('@/components/shared/Toast', () => ({ toast: vi.fn() }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}))

beforeEach(() => {
  mockBatchStatus.mockReturnValue(null)
  mockProbeStatus.mockReturnValue(null)
  mockScannerStatus.mockReturnValue(null)
})

describe('QueuePage stop controls', () => {
  it('shows a stop button on the wanted batch card that stops the batch', () => {
    mockBatchStatus.mockReturnValue({ running: true, total: 5, processed: 2, found: 1, failed: 0, skipped: 0 })
    render(<QueuePage />)
    const button = screen.getByLabelText('queue.stop_search')
    fireEvent.click(button)
    expect(mockStopBatch).toHaveBeenCalledWith(undefined, expect.anything())
  })

  it('shows a stop button on the batch probe card that stops the probe', () => {
    mockProbeStatus.mockReturnValue({ running: true, total: 8, found: 2, extracted: 1, failed: 0 })
    render(<QueuePage />)
    const button = screen.getByLabelText('queue.stop_probe')
    fireEvent.click(button)
    expect(mockStopProbe).toHaveBeenCalledWith(undefined, expect.anything())
  })

  it('shows a stop button on the scanner card that cancels wanted_scan', () => {
    mockScannerStatus.mockReturnValue({
      is_scanning: true,
      is_searching: false,
      progress: { current: 1, total: 3, phase: 'scan', added: 0, updated: 0 },
    })
    render(<QueuePage />)
    const button = screen.getByLabelText('queue.stop_scan')
    fireEvent.click(button)
    expect(mockCancelTask).toHaveBeenCalledWith('wanted_scan', expect.anything())
  })

  it('renders no stop buttons when everything is idle', () => {
    mockBatchStatus.mockReturnValue({ running: false, total: 5, processed: 5, found: 3, failed: 0, skipped: 2 })
    mockProbeStatus.mockReturnValue({ running: false, total: 0, found: 0, extracted: 0, failed: 0 })
    mockScannerStatus.mockReturnValue({ is_scanning: false, is_searching: false, progress: { current: 0, total: 0, phase: null, added: 0, updated: 0 } })
    render(<QueuePage />)
    expect(screen.queryAllByTestId('queue-stop')).toHaveLength(0)
  })
})
