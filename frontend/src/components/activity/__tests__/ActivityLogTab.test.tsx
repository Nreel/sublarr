import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import React from 'react'
import { ActivityLogTab } from '../ActivityLogTab'

const mockUseActivity = vi.fn()
const mockStopRemux = vi.fn()
const mockStopSync = vi.fn()
const mockStopWhisper = vi.fn()
const mockStopCleanupScan = vi.fn()
const mockStopScheduledJob = vi.fn()
const mockStopRepair = vi.fn()

vi.mock('@/hooks/useSystemApi', () => ({
  useActivity: (...args: unknown[]) => mockUseActivity(...args),
  useStopRemuxJob: () => ({ mutate: mockStopRemux, isPending: false }),
  useStopVideoSyncJob: () => ({ mutate: mockStopSync, isPending: false }),
  useCancelWhisperJob: () => ({ mutate: mockStopWhisper, isPending: false }),
  useStopCleanupScan: () => ({ mutate: mockStopCleanupScan, isPending: false }),
  useStopScheduledJob: () => ({ mutate: mockStopScheduledJob, isPending: false }),
  useStopRepair: () => ({ mutate: mockStopRepair, isPending: false }),
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}))

const SAMPLE_DATA = {
  data: {
    data: [
      { id: 1, event_type: 'download', file_path: '/media/One Piece - S01E01.mkv',
        status: 'success', details: { provider: 'jimaku', score: 90 },
        created_at: '2026-04-05T10:00:00Z' },
      { id: 2, event_type: 'extract', file_path: '/media/Attack on Titan - S02E01.mkv',
        status: 'success', details: null, created_at: '2026-04-05T09:50:00Z' },
      { id: 3, event_type: 'delete', file_path: '/media/Demon Slayer.de.ass',
        status: 'success', details: null, created_at: '2026-04-05T09:40:00Z' },
      { id: 4, event_type: 'scan', file_path: null,
        status: 'success', details: { found: 3, total: 10 },
        created_at: '2026-04-05T09:30:00Z' },
    ],
    total: 4,
    page: 1,
    per_page: 50,
    total_pages: 1,
  },
  isLoading: false,
}

beforeEach(() => {
  mockUseActivity.mockClear()
  mockUseActivity.mockReturnValue(SAMPLE_DATA)
})

function wrap(ui: React.ReactElement) {
  return render(<BrowserRouter>{ui}</BrowserRouter>)
}

describe('ActivityLogTab', () => {
  it('renders the tab container', () => {
    wrap(<ActivityLogTab />)
    expect(screen.getByTestId('activity-log-tab')).toBeInTheDocument()
  })

  it('renders a row for each activity entry', () => {
    wrap(<ActivityLogTab />)
    expect(screen.getByTestId('activity-row-1')).toBeInTheDocument()
    expect(screen.getByTestId('activity-row-2')).toBeInTheDocument()
    expect(screen.getByTestId('activity-row-3')).toBeInTheDocument()
    expect(screen.getByTestId('activity-row-4')).toBeInTheDocument()
  })

  it('shows event type badge for each row', () => {
    wrap(<ActivityLogTab />)
    expect(screen.getByTestId('activity-type-1')).toHaveAttribute('data-type', 'download')
    expect(screen.getByTestId('activity-type-2')).toHaveAttribute('data-type', 'extract')
    expect(screen.getByTestId('activity-type-3')).toHaveAttribute('data-type', 'delete')
    expect(screen.getByTestId('activity-type-4')).toHaveAttribute('data-type', 'scan')
  })

  it('renders a status badge for each entry', () => {
    mockUseActivity.mockReturnValue(SAMPLE_DATA)
    render(<BrowserRouter><ActivityLogTab /></BrowserRouter>)
    expect(screen.getAllByText('success')).toHaveLength(SAMPLE_DATA.data.data.length)
  })

  it('renders a stop button on running rows wired by event type', () => {
    mockUseActivity.mockReturnValue({
      data: {
        data: [
          { id: 10, event_type: 'remux', status: 'running', file_path: '/media/Film.mkv',
            details: { job_id: 'rm-7' }, created_at: '2026-11-17T12:00:00Z' },
          { id: 11, event_type: 'sync', status: 'running', file_path: '/media/Film.mkv',
            details: { job_id: 'sy-2' }, created_at: '2026-11-17T12:01:00Z' },
          { id: 12, event_type: 'whisper', status: 'running', file_path: '/media/Film.mkv',
            details: { job_id: 'wh-9' }, created_at: '2026-11-17T12:02:00Z' },
          { id: 13, event_type: 'cleanup', status: 'running', file_path: null,
            details: { kind: 'dedup_scan' }, created_at: '2026-11-17T12:03:00Z' },
          { id: 14, event_type: 'automation', status: 'running', file_path: null,
            details: {}, created_at: '2026-11-17T12:04:00Z' },
          { id: 15, event_type: 'repair', status: 'running', file_path: null,
            details: {}, created_at: '2026-11-17T12:05:00Z' },
          { id: 16, event_type: 'anidb', status: 'running', file_path: null,
            details: {}, created_at: '2026-11-17T12:06:00Z' },
        ],
        total: 7, page: 1, per_page: 50, total_pages: 1,
      },
      isLoading: false,
    })
    render(<BrowserRouter><ActivityLogTab /></BrowserRouter>)
    expect(screen.getAllByLabelText('history.stop_running')).toHaveLength(7)
    fireEvent.click(screen.getByTestId('activity-stop-10'))
    expect(mockStopRemux).toHaveBeenCalledWith('rm-7', expect.anything())
    fireEvent.click(screen.getByTestId('activity-stop-11'))
    expect(mockStopSync).toHaveBeenCalledWith('sy-2', expect.anything())
    fireEvent.click(screen.getByTestId('activity-stop-12'))
    expect(mockStopWhisper).toHaveBeenCalledWith('wh-9', expect.anything())
    fireEvent.click(screen.getByTestId('activity-stop-13'))
    expect(mockStopCleanupScan).toHaveBeenCalledWith(undefined, expect.anything())
    fireEvent.click(screen.getByTestId('activity-stop-14'))
    expect(mockStopScheduledJob).toHaveBeenCalledWith('subtitle_automation', expect.anything())
    fireEvent.click(screen.getByTestId('activity-stop-15'))
    expect(mockStopRepair).toHaveBeenCalledWith(undefined, expect.anything())
    fireEvent.click(screen.getByTestId('activity-stop-16'))
    expect(mockStopScheduledJob).toHaveBeenCalledWith('anidb_sync', expect.anything())
  })

  it('renders no stop buttons on terminal rows', () => {
    mockUseActivity.mockReturnValue(SAMPLE_DATA)
    render(<BrowserRouter><ActivityLogTab /></BrowserRouter>)
    expect(screen.queryByLabelText('history.stop_running')).not.toBeInTheDocument()
    expect(screen.queryAllByTestId(/^activity-stop-/)).toHaveLength(0)
  })

  it('shows empty state when no entries', () => {
    mockUseActivity.mockReturnValue({
      data: { data: [], total: 0, page: 1, per_page: 50, total_pages: 1 },
      isLoading: false,
    })
    wrap(<ActivityLogTab />)
    expect(screen.getByTestId('activity-empty')).toBeInTheDocument()
  })

  it('shows loading state while fetching', () => {
    mockUseActivity.mockReturnValue({ data: undefined, isLoading: true })
    wrap(<ActivityLogTab />)
    expect(screen.getByTestId('activity-loading')).toBeInTheDocument()
  })

  it('renders media title from file_path for non-scan events', () => {
    wrap(<ActivityLogTab />)
    expect(screen.getByTestId('activity-row-1')).toHaveTextContent('One Piece')
  })

  it('renders scan label for scan events without file_path', () => {
    wrap(<ActivityLogTab />)
    expect(screen.getByTestId('activity-row-4')).toHaveTextContent('Wanted scan')
  })

  it('renders a translate filter pill alongside download/extract/delete/scan', () => {
    wrap(<ActivityLogTab />)
    // Mocked t(key, fallback) => fallback -- the pill's fallback is the raw type name.
    expect(screen.getByText('translate')).toBeInTheDocument()
  })
})
