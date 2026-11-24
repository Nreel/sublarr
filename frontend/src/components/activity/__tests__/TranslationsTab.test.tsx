import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'
import { TranslationsTab } from '../TranslationsTab'

const mockUseJobs = vi.fn()
const mockUseBatchStatus = vi.fn()
const mockCancelMutate = vi.fn()
const mockClearMutate = vi.fn()
const mockCancelRunningMutate = vi.fn()
const mockStopBatchMutate = vi.fn()

vi.mock('@/hooks/useApi', () => ({
  useJobs: (...args: unknown[]) => mockUseJobs(...args),
  useBatchStatus: () => mockUseBatchStatus(),
  useCancelJob: () => ({ mutate: mockCancelMutate, isPending: false }),
  useClearQueuedJobs: () => ({ mutate: mockClearMutate, isPending: false }),
  useCancelRunningTranslation: () => ({ mutate: mockCancelRunningMutate, isPending: false }),
  useStopBatchTranslate: () => ({ mutate: mockStopBatchMutate, isPending: false }),
}))
vi.mock('@/components/shared/Toast', () => ({ toast: vi.fn() }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, arg?: unknown) => {
      if (typeof arg === 'string') return arg
      const templates: Record<string, string> = {
        'translations.lines': '{{done}}/{{total}} lines',
        'translations.eta': '{{seconds}}s remaining',
      }
      const template = templates[key] ?? key
      return template.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
        String((arg as Record<string, unknown> | undefined)?.[name]),
      )
    },
  }),
}))

const RUNNING_JOBS = {
  data: [{ id: 'run-1', file_path: '/media/Show - S01E01.en.srt', status: 'running' }],
}
const RUNNING_JOBS_WITH_PROGRESS = {
  data: [
    {
      id: 'run-1',
      file_path: '/media/Show - S01E01.en.srt',
      status: 'running',
      progress: {
        done: 120,
        total: 300,
        pct: 40,
        eta_seconds: 60,
        backend: 'llama.cpp',
        cost_so_far_micro_usd: 4200,
      },
    },
  ],
}
const QUEUED_JOBS = {
  data: [
    { id: 'q-1', file_path: '/media/Show - S01E02.en.srt', status: 'queued' },
    { id: 'q-2', file_path: '/media/Show - S01E03.en.srt', status: 'queued' },
  ],
}

function mockJobs(queued = QUEUED_JOBS, running = RUNNING_JOBS) {
  mockUseJobs.mockImplementation((_page, _perPage, status) =>
    status === 'queued' ? { data: queued } : { data: running },
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockJobs()
  mockUseBatchStatus.mockReturnValue({ data: undefined })
})

describe('TranslationsTab', () => {
  it('renders a cancel button for each queued row', () => {
    render(<TranslationsTab />)
    const cancelButtons = screen.getAllByLabelText('translations.cancel_job')
    expect(cancelButtons).toHaveLength(2)
  })

  it('renders a stop control on running rows that cancels through the live queue', () => {
    mockJobs({ data: [] }, RUNNING_JOBS)
    render(<TranslationsTab />)
    const stopButton = screen.getByLabelText('translations.stop_running')
    fireEvent.click(stopButton)
    // Cooperative queue cancel (POST /translation/queue/<id>/cancel), not
    // the queued-job DELETE mutation.
    expect(mockCancelRunningMutate).toHaveBeenCalledWith('run-1', expect.anything())
    expect(mockCancelMutate).not.toHaveBeenCalled()
  })

  it('renders a batch STOP control while a batch run is in flight', () => {
    mockUseBatchStatus.mockReturnValue({
      data: { running: true, total: 10, processed: 3, succeeded: 2, failed: 1, skipped: 0 },
    })
    render(<TranslationsTab />)
    const stopButton = screen.getByLabelText('translations.stop_batch')
    fireEvent.click(stopButton)
    expect(mockStopBatchMutate).toHaveBeenCalledTimes(1)
  })

  it('does not render the batch STOP control when no batch is running', () => {
    render(<TranslationsTab />)
    expect(screen.queryByLabelText('translations.stop_batch')).not.toBeInTheDocument()
  })

  it('calls the cancel mutation with the job id when clicked', () => {
    render(<TranslationsTab />)
    const [firstCancel] = screen.getAllByLabelText('translations.cancel_job')
    fireEvent.click(firstCancel)
    expect(mockCancelMutate).toHaveBeenCalledTimes(1)
    expect(mockCancelMutate.mock.calls[0][0]).toBe('q-1')
  })

  it('renders a progress bar and per-line stats for running jobs with progress', () => {
    mockJobs({ data: [] }, RUNNING_JOBS_WITH_PROGRESS)
    render(<TranslationsTab />)
    expect(screen.getByText('120/300 lines')).toBeInTheDocument()
    expect(screen.getByText('60s remaining')).toBeInTheDocument()
    expect(screen.getByText('llama.cpp')).toBeInTheDocument()
    expect(screen.getByText('40%')).toBeInTheDocument()
  })

  it('renders no per-line stats for running jobs without progress', () => {
    mockJobs({ data: [] }, RUNNING_JOBS)
    render(<TranslationsTab />)
    expect(screen.queryByText('translations.lines')).not.toBeInTheDocument()
    expect(screen.queryByText('40%')).not.toBeInTheDocument()
  })

  it('renders the clear-queued button and calls the mutation', () => {
    render(<TranslationsTab />)
    const clearButton = screen.getByRole('button', { name: 'translations.clear_queued' })
    expect(clearButton).toBeEnabled()
    fireEvent.click(clearButton)
    expect(mockClearMutate).toHaveBeenCalledTimes(1)
  })

  it('disables the clear-queued button when no jobs are queued', () => {
    mockJobs({ data: [] })
    render(<TranslationsTab />)
    const clearButton = screen.getByRole('button', { name: 'translations.clear_queued' })
    expect(clearButton).toBeDisabled()
    fireEvent.click(clearButton)
    expect(mockClearMutate).not.toHaveBeenCalled()
  })
})
