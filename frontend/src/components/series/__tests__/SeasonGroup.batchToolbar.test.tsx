import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockBatchTranslate = vi.fn()
const mockBatchSearch = vi.fn()

vi.mock('@/hooks/useTranslationApi', () => ({
  useTranscribeEpisode: () => ({ mutate: vi.fn(), isPending: false }),
  useDetectOpeningEnding: () => ({ mutate: vi.fn(), isPending: false }),
  useBatchTranslate: () => ({ mutate: mockBatchTranslate, isPending: false }),
}))

vi.mock('@/components/library/EpisodeRow', () => ({
  getRowStatus: () => 'ok',
}))

vi.mock('./EpisodeSearchPanel', () => ({
  EpisodeSearchPanel: () => null,
}))

vi.mock('./EpisodeHistoryPanel', () => ({
  EpisodeHistoryPanel: () => null,
}))

vi.mock('@/components/tracks/TrackPanel', () => ({
  TrackPanel: () => null,
}))

vi.mock('./EpisodeGrid', () => ({
  EPISODE_GRID_COLUMNS: '28px 50px 1fr 90px minmax(180px,1.5fr) 170px',
}))

vi.mock('./seriesUtils', () => ({
  deriveSubtitlePath: () => null,
  normLang: (code: string) => code,
}))

vi.mock('@/components/health/HealthBadge', () => ({
  HealthBadge: () => null,
}))

vi.mock('@/components/episodes/EpisodeActionMenu', () => ({
  EpisodeActionMenu: () => null,
}))

vi.mock('@/components/processing/SubtitleActionsMenu', () => ({
  SubtitleActionsMenu: () => null,
}))

vi.mock('@/api/client', () => ({
  startWantedBatchSearch: (...args: unknown[]) => mockBatchSearch(...args),
  exportSubtitleNfo: vi.fn(),
  getSubtitleDownloadUrl: vi.fn(() => ''),
}))

vi.mock('@/components/shared/Toast', () => ({
  toast: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}))

const episode = (id: number, file: string) => ({
  id,
  title: `Episode ${id}`,
  episode: id,
  season: 1,
  has_file: true,
  file_path: file,
  subtitles: {},
  subtitle_scores: {},
  subtitle_providers: {},
  wanted_status: null,
  wanted_id: null,
})

// Episode IDs and wanted IDs are separate namespaces; picking deliberately
// different numbers so a verbatim episode-ID send cannot pass by coincidence.
const MAP = new Map<number, number>([[101, 555]])

const baseProps = {
  season: 1,
  episodes: [episode(101, '/media/show/s01e01.mkv'), episode(102, '/media/show/s01e02.mkv')],
  targetLanguages: ['de'],
  seriesId: 1,
  isExtracting: false,
  onExtract: vi.fn(),
  expandedEp: null,
  onSearch: vi.fn(),
  onInteractiveSearch: vi.fn(),
  onHistory: vi.fn(),
  onTracks: vi.fn(),
  onClose: vi.fn(),
  searchResults: null,
  searchLoading: false,
  historyEntries: [],
  historyLoading: false,
  onProcess: vi.fn(),
  onPreviewSub: vi.fn(),
  onEditSub: vi.fn(),
  onCompare: vi.fn(),
  onCombine: vi.fn(),
  onSync: vi.fn(),
  onSyncCompare: vi.fn(),
  onAutoSync: vi.fn(),
  onVideoSync: vi.fn(),
  onHealthCheck: vi.fn(),
  healthScores: {},
  onOpenEditor: vi.fn(),
  sidecarMap: {},
  onDeleteSidecar: vi.fn(),
  onOpenCleanupModal: vi.fn(),
  onPreview: vi.fn(),
  streamingEnabled: false,
  onRefreshSidecars: vi.fn(),
  t: (key: string) => key,
  episodeWantedMap: MAP,
  onSkipEpisode: vi.fn(),
  onAcceptEpisode: vi.fn(),
}

import { SeasonGroup } from '../SeasonGroup'

describe('SeasonGroup batch toolbar sends wanted item IDs (episode-ID bug)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('translate queues the wanted IDs of the selected episodes, not episode IDs', () => {
    render(<SeasonGroup {...baseProps} />)
    fireEvent.click(screen.getByTestId('episode-select-101'))
    expect(screen.getByTestId('episode-batch-toolbar')).toBeTruthy()
    fireEvent.click(screen.getByText('episode_ui.translate'))
    expect(mockBatchTranslate).toHaveBeenCalledWith([555])
  })

  it('search queues the wanted IDs of the selected episodes', () => {
    render(<SeasonGroup {...baseProps} />)
    fireEvent.click(screen.getByTestId('episode-select-101'))
    fireEvent.click(screen.getByText('episode_ui.search'))
    expect(mockBatchSearch).toHaveBeenCalledWith([555])
  })

  it('translate is disabled when the selection has no wanted rows', () => {
    render(<SeasonGroup {...baseProps} />)
    fireEvent.click(screen.getByTestId('episode-select-102'))
    const button = screen.getByText('episode_ui.translate').closest('button')
    expect(button?.disabled).toBe(true)
    fireEvent.click(button!)
    expect(mockBatchTranslate).not.toHaveBeenCalled()
  })
})
