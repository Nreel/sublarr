import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

// ─── Mocks ───────────────────────────────────────────────────────────────────

const mockBatchTranslateMutate = vi.fn()
const mockRefreshMutate = vi.fn()
const mockCleanupMutate = vi.fn()
let mockMtPendingTotal = 0
let mockProfiles: unknown = undefined

vi.mock('@/hooks/useTranslationApi', () => ({
  useBatchTranslate: () => ({ mutate: mockBatchTranslateMutate, isPending: false }),
}))

vi.mock('@/hooks/useApi', () => ({
  useWantedItems: () => ({ data: { data: [], total: 0 }, isLoading: false }),
  useWantedSummary: () => ({ data: { total: 0, by_status: {}, by_type: {}, upgradeable: 0, by_subtitle_type: {} } }),
  useRefreshWanted: () => ({ mutate: mockRefreshMutate, isPending: false }),
  useUpdateWantedStatus: () => ({ mutate: vi.fn() }),
  useSearchWantedItem: () => ({ mutate: vi.fn() }),
  useProcessWantedItem: () => ({ mutate: vi.fn() }),
  useExtractEmbeddedSub: () => ({ mutate: vi.fn() }),
  useStartWantedBatch: () => ({ mutate: vi.fn(), isPending: false }),
  useWantedBatchStatus: () => ({ data: null }),
  useWantedBatchExtractStatus: () => ({ data: null, refetch: vi.fn() }),
  useWantedBatchProbeStatus: () => ({ data: null }),
  useStartBatchProbe: () => ({ mutate: vi.fn(), isPending: false }),
  useRetranslateSingle: () => ({ mutate: vi.fn() }),
  useAddToBlacklist: () => ({ mutate: vi.fn() }),
  useCleanupSidecars: () => ({ mutate: mockCleanupMutate, isPending: false }),
  useTranslationEnabled: () => true,
  useLanguageProfiles: () => ({ data: mockProfiles }),
  useInfiniteWantedItems: () => ({ data: undefined, fetchNextPage: vi.fn(), hasNextPage: false, isFetchingNextPage: false }),
  useMtPendingItems: () => ({ data: { data: [], total: mockMtPendingTotal }, isLoading: false, isError: false }),
  useApproveMtPending: () => ({ mutate: vi.fn(), isPending: false }),
  useApproveMtPendingBatch: () => ({ mutate: vi.fn(), isPending: false }),
  useRejectMtPending: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/stores/selectionStore', () => ({
  useSelectionStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      selections: {},
      toggleItem: vi.fn(),
      selectAll: vi.fn(),
      clearSelection: vi.fn(),
    }),
}))

vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: () => ({}),
}))

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>()
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
      if (Array.isArray(queryKey) && queryKey[0] === 'config') {
        return { data: { source_language: 'en' } }
      }
      return { data: undefined }
    },
  }
})

vi.mock('@/components/wanted/VirtualWantedTable', () => ({
  useWantedVirtualizer: () => ({ parentRef: { current: null }, virtualItems: [], paddingTop: 0, paddingBottom: 0 }),
}))

vi.mock('@/components/filters/FilterBar', () => ({
  FilterBar: () => <div data-testid="filter-bar" />,
}))

vi.mock('@/components/filters/FilterPresetMenu', () => ({
  FilterPresetMenu: () => <div data-testid="filter-preset-menu" />,
}))

vi.mock('@/components/batch/BatchActionBar', () => ({
  BatchActionBar: () => <div data-testid="batch-action-bar" />,
}))

vi.mock('@/components/editor/SubtitleEditorModal', () => ({
  default: () => null,
}))

vi.mock('@/components/wanted/InteractiveSearchModal', () => ({
  InteractiveSearchModal: () => null,
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}))

vi.mock('@/components/shared/Toast', () => ({
  toast: vi.fn(),
}))

vi.mock('@/components/shared/StatusBadge', () => ({
  StatusBadge: () => null,
  SubtitleTypeBadge: () => null,
}))

vi.mock('@/lib/utils', () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(' '),
  formatRelativeTime: () => '',
  truncatePath: (p: string) => p,
}))

// ─── Tests ───────────────────────────────────────────────────────────────────

async function renderWanted() {
  const { WantedPage } = await import('../Wanted')
  return render(
    <MemoryRouter>
      <WantedPage />
    </MemoryRouter>
  )
}

describe('Wanted toolbar buttons (Steps 56 & 57)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockMtPendingTotal = 0
    mockProfiles = undefined
  })

  it('renders batch-translate-btn', async () => {
    await renderWanted()
    expect(screen.getByTestId('batch-translate-btn')).toBeTruthy()
  })

  it('calls batchTranslate.mutate when batch translate button is clicked', async () => {
    await renderWanted()
    fireEvent.click(screen.getByTestId('batch-translate-btn'))
    expect(mockBatchTranslateMutate).toHaveBeenCalledTimes(1)
  })

  it('renders wanted-refresh-btn', async () => {
    await renderWanted()
    expect(screen.getByTestId('wanted-refresh-btn')).toBeTruthy()
  })

  it('calls refreshWanted.mutate when refresh button is clicked', async () => {
    await renderWanted()
    fireEvent.click(screen.getByTestId('wanted-refresh-btn'))
    expect(mockRefreshMutate).toHaveBeenCalledTimes(1)
  })

  it('disables Refresh when language profiles are loaded but none is configured', async () => {
    mockProfiles = []
    await renderWanted()
    const btn = screen.getByTestId('wanted-refresh-btn')
    expect(btn).toBeDisabled()
    fireEvent.click(btn)
    expect(mockRefreshMutate).not.toHaveBeenCalled()
    expect(btn.getAttribute('title')).toBe('ui.refresh_needs_profile')
  })

  it('enables Refresh and describes its action once a profile exists', async () => {
    mockProfiles = [{ id: 1, target_language: 'de', source_languages: ['en'], is_default: true }]
    await renderWanted()
    const btn = screen.getByTestId('wanted-refresh-btn')
    expect(btn).not.toBeDisabled()
    expect(btn.getAttribute('title')).toBe('ui.refresh_wanted')
  })

  it('every toolbar button carries a tooltip describing its action', async () => {
    mockProfiles = [{ id: 1, target_language: 'de', source_languages: ['en'], is_default: true }]
    await renderWanted()
    expect(screen.getByTestId('wanted-export-btn').getAttribute('title')).toBe('ui.export_wanted')
    expect(screen.getByTestId('wanted-cleanup-btn').getAttribute('title')).toBe('ui.cleanup_sidecars')
    expect(screen.getByTestId('wanted-search-all-btn').getAttribute('title')).toBe('ui.search_all')
    expect(screen.getByTestId('batch-translate-btn').getAttribute('title')).toBe('ui.batch_translate_downloaded')
    expect(screen.getByTestId('wanted-refresh-btn').getAttribute('title')).toBe('ui.refresh_wanted')
    // Scan Embedded renders without a testid; match by its label key.
    const scanBtn = screen.getByRole('button', { name: /wanted.scan_embedded/ })
    expect(scanBtn.getAttribute('title')).toBe('ui.scan_embedded')
  })

  it('renders wanted-cleanup-btn', async () => {
    await renderWanted()
    expect(screen.getByTestId('wanted-cleanup-btn')).toBeTruthy()
  })

  it('hides the pending-original indicator when there is nothing pending', async () => {
    await renderWanted()
    expect(screen.queryByTestId('mt-pending-toolbar-btn')).toBeNull()
  })

  it('shows the pending-original indicator with a count when items are pending (feature #8b)', async () => {
    mockMtPendingTotal = 3
    await renderWanted()
    expect(screen.getByTestId('mt-pending-toolbar-btn')).toBeTruthy()
    expect(screen.getByTestId('mt-pending-count')).toHaveTextContent('3')
  })

  it('opens the pending-original modal when the indicator is clicked', async () => {
    mockMtPendingTotal = 1
    await renderWanted()
    fireEvent.click(screen.getByTestId('mt-pending-toolbar-btn'))
    expect(screen.getByRole('dialog')).toBeTruthy()
  })
})
