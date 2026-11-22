import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  searchGlobal, getFilterPresets, createFilterPreset, deleteFilterPreset,
  getApiKeys, updateApiKey, testApiKey, exportApiKeys, importApiKeys,
  revealApiKeys, rotateApiKey,
} from '@/api/client'
import type { FilterScope } from '@/lib/types'

// ─── Phase 12: Search + Filter Presets ────────────────────────────────────

export function useGlobalSearch(query: string) {
  return useQuery({
    queryKey: ['search', query],
    queryFn: () => searchGlobal(query),
    enabled: query.trim().length >= 2,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  })
}

export function useFilterPresets(scope: FilterScope) {
  return useQuery({
    queryKey: ['filter-presets', scope],
    queryFn: () => getFilterPresets(scope),
    staleTime: 60_000,
  })
}

export function useCreateFilterPreset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (preset: Parameters<typeof createFilterPreset>[0]) => createFilterPreset(preset),
    onSuccess: (data) => qc.invalidateQueries({ queryKey: ['filter-presets', data.scope] }),
  })
}

export function useDeleteFilterPreset(scope: FilterScope) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteFilterPreset(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['filter-presets', scope] }),
  })
}

// ─── API Key Management ──────────────────────────────────────────────────────

export function useApiKeys() {
  return useQuery({
    queryKey: ['api-keys'],
    queryFn: getApiKeys,
    staleTime: 30_000,
  })
}

export function useUpdateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ service, keyName, value }: { service: string; keyName: string; value: string }) =>
      updateApiKey(service, keyName, value),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['api-keys'] })
      // The revealed value changed too, so the cached raw copy is stale.
      void qc.invalidateQueries({ queryKey: ['api-keys-raw', vars.service] })
    },
  })
}

/**
 * Full values for the reveal/copy affordance. Fetched on demand: the list
 * endpoint only ever carries masks, so revealing needs its own request.
 */
export function useRevealApiKeys(service: string, enabled: boolean) {
  return useQuery({
    queryKey: ['api-keys-raw', service],
    queryFn: () => revealApiKeys(service),
    enabled,
    staleTime: 0,
  })
}

export function useRotateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (service: string) => rotateApiKey(service),
    onSuccess: (_data, service) => {
      void qc.invalidateQueries({ queryKey: ['api-keys'] })
      void qc.invalidateQueries({ queryKey: ['api-keys-raw', service] })
    },
  })
}

export function useTestApiKey() {
  return useMutation({
    mutationFn: (service: string) => testApiKey(service),
  })
}

export function useExportApiKeys() {
  return useMutation({
    mutationFn: () => exportApiKeys(),
  })
}

export function useImportApiKeys() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => importApiKeys(file),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['api-keys'] }) },
  })
}
