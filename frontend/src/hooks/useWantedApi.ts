import { useQuery, useInfiniteQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  getWantedItems, getWantedSummary, refreshWanted,
  updateWantedItemStatus,
  searchWantedItem, processWantedItem, extractEmbeddedSub,
  startWantedBatchSearch, getWantedBatchStatus, getBatchExtractStatus, getBatchProbeStatus, startBatchProbe,
  searchAllWanted,
  getScannerStatus,
  cleanupSidecars,
} from '@/api/client'

// ─── Wanted ─────────────────────────────────────────────────────────────

/** When fetchAll=true, fetches page=1 with perPage=9999 (cap ~9999 items). Sufficient for typical Wanted lists. */
export function useWantedItems(page = 1, perPage = 50, itemType?: string, status?: string, subtitleType?: string, fetchAll = false, movieId?: number, sonarrSeriesId?: number) {
  return useQuery({
    queryKey: ['wanted', fetchAll ? 'all' : page, fetchAll ? 9999 : perPage, itemType, status, subtitleType, movieId, sonarrSeriesId],
    queryFn: () =>
      getWantedItems(
        fetchAll ? 1 : page,
        fetchAll ? 9999 : perPage,
        itemType,
        status,
        subtitleType,
        movieId,
        sonarrSeriesId,
      ),
    placeholderData: keepPreviousData,
  })
}

/** Infinite scroll version — loads 50 items per page, fetches next page as user scrolls. */
export function useInfiniteWantedItems(
  itemType?: string,
  status?: string,
  subtitleType?: string,
  search?: string,
  sortBy = 'added_at',
  sortDir: 'asc' | 'desc' = 'desc',
) {
  return useInfiniteQuery({
    queryKey: ['wanted', 'infinite', itemType, status, subtitleType, search, sortBy, sortDir],
    queryFn: ({ pageParam }) =>
      getWantedItems(pageParam as number, 50, itemType, status, subtitleType, undefined, undefined, search, sortBy, sortDir),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page < lastPage.total_pages ? lastPage.page + 1 : undefined,
  })
}

export function useWantedSummary() {
  return useQuery({
    queryKey: ['wanted-summary'],
    queryFn: getWantedSummary,
  })
}

export function useRefreshWanted() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (seriesId?: number) => refreshWanted(seriesId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
      queryClient.invalidateQueries({ queryKey: ['wanted-summary'] })
    },
  })
}

export function useUpdateWantedStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, status }: { itemId: number; status: string }) =>
      updateWantedItemStatus(itemId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
      queryClient.invalidateQueries({ queryKey: ['wanted-summary'] })
    },
  })
}

export function useSearchWantedItem() {
  return useMutation({
    mutationFn: (itemId: number) => searchWantedItem(itemId),
  })
}

export function useProcessWantedItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: number) => processWantedItem(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
      queryClient.invalidateQueries({ queryKey: ['wanted-summary'] })
    },
  })
}

export function useExtractEmbeddedSub() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, options }: { itemId: number; options?: { stream_index?: number; target_language?: string } }) =>
      extractEmbeddedSub(itemId, options),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
      queryClient.invalidateQueries({ queryKey: ['wanted-summary'] })
    },
  })
}

export function useStartWantedBatch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars?: { itemIds?: number[]; seriesId?: number }) =>
      startWantedBatchSearch(vars?.itemIds, vars?.seriesId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-batch-status'] })
    },
  })
}

export function useWantedBatchStatus(idleRefetchMs: number | false = 10000) {
  return useQuery({
    queryKey: ['wanted-batch-status'],
    queryFn: getWantedBatchStatus,
    refetchInterval: (query) => (query.state.data?.running ? 3000 : idleRefetchMs),
  })
}

export function useWantedBatchExtractStatus(idleRefetchMs: number | false = false) {
  return useQuery({
    queryKey: ['wanted-batch-extract-status'],
    queryFn: getBatchExtractStatus,
    refetchInterval: (query) => (query.state.data?.running ? 3000 : idleRefetchMs),
  })
}

export function useWantedBatchProbeStatus(idleRefetchMs: number | false = false) {
  return useQuery({
    queryKey: ['wanted-batch-probe-status'],
    queryFn: getBatchProbeStatus,
    refetchInterval: (query) => (query.state.data?.running ? 2000 : idleRefetchMs),
  })
}

export function useScannerStatus(idleRefetchMs: number | false = 30000) {
  return useQuery({
    queryKey: ['scanner-status'],
    queryFn: getScannerStatus,
    refetchInterval: (query) =>
      query.state.data?.is_scanning || query.state.data?.is_searching ? 3000 : idleRefetchMs,
  })
}

/**
 * Work items still pending in the Queue tab: wanted batch search, batch probe,
 * embedded-sub batch extract, and the wanted scan/search. Each is one global
 * run reporting `{running, total, processed}`, so this is what is left to do —
 * an idle Queue is 0. A run counts at least 1 while it is in flight, since the
 * item being worked on is not yet `processed`.
 *
 * Nav badges read this outside the Queue tab, so idle runs still poll here —
 * WebSocket progress events refresh the same queries immediately (see
 * GlobalWebSocketListener), and this slow interval only covers a dropped
 * socket.
 */
export function useQueueTaskCount(idleRefetchMs = 30000): number {
  const { data: batch } = useWantedBatchStatus(idleRefetchMs)
  const { data: probe } = useWantedBatchProbeStatus(idleRefetchMs)
  const { data: extract } = useWantedBatchExtractStatus(idleRefetchMs)
  const { data: scanner } = useScannerStatus(idleRefetchMs)

  const pending = (run?: { running: boolean; total: number; processed: number }) =>
    run?.running ? Math.max(run.total - run.processed, 1) : 0

  const scanPending =
    scanner?.is_scanning || scanner?.is_searching
      ? Math.max((scanner.progress.total ?? 0) - (scanner.progress.current ?? 0), 1)
      : 0

  return pending(batch) + pending(probe) + pending(extract) + scanPending
}

export function useStartBatchProbe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (seriesId?: number) => startBatchProbe(seriesId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-batch-probe-status'] })
    },
  })
}

export function useCleanupSidecars() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars?: { itemIds?: number[]; dryRun?: boolean }) =>
      cleanupSidecars(vars?.itemIds, vars?.dryRun),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
      queryClient.invalidateQueries({ queryKey: ['wanted-summary'] })
    },
  })
}

// ─── Search All ──────────────────────────────────────────────────────────────

export function useSearchAllWanted() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => searchAllWanted(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
      queryClient.invalidateQueries({ queryKey: ['wanted-summary'] })
    },
  })
}

// ─── Subtitle Automation (0.71.0) ────────────────────────────────────────────

import { getAutomationStatus, runAutomationNow } from '@/api/wanted'

/** Polls `/wanted/automation/status` every 5 s while the page is open. */
export function useAutomationStatus() {
  return useQuery({
    queryKey: ['automation-status'],
    queryFn: getAutomationStatus,
    refetchInterval: 5000,
  })
}

export function useRunAutomationNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: runAutomationNow,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['automation-status'] })
    },
  })
}

// ─── Provisional-MT pending-original review (feature #8b Phase 2, Task 4) ───

import {
  getMtPendingItems,
  approveMtPending,
  approveMtPendingBatch,
  rejectMtPending,
} from '@/api/wanted'

/**
 * Polls `/wanted/mt-pending` every 30s so the toolbar indicator stays fresh,
 * and every 5s while a bulk approval runs so its progress moves visibly.
 */
export function useMtPendingItems() {
  return useQuery({
    queryKey: ['wanted-mt-pending'],
    queryFn: getMtPendingItems,
    refetchInterval: (query) => (query.state.data?.batch?.running ? 5000 : 30000),
  })
}

export function useApproveMtPendingBatch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemIds: number[]) => approveMtPendingBatch(itemIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-mt-pending'] })
    },
  })
}

export function useApproveMtPending() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: number) => approveMtPending(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-mt-pending'] })
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
      queryClient.invalidateQueries({ queryKey: ['wanted-summary'] })
    },
  })
}

export function useRejectMtPending() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: number) => rejectMtPending(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-mt-pending'] })
      queryClient.invalidateQueries({ queryKey: ['wanted'] })
    },
  })
}
