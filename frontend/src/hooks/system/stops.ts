/**
 * Stop mutations for every in-flight activity surfaced on /activity.
 * Each mirrors `useCancelJob` (invalidate the driving query, nothing else):
 * components own their toasts. `['activity']` is invalidated on every stop so
 * the History tab flips the row from "running" to its terminal status.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { stopScheduledJob } from '@/api/scheduler'
import { stopWantedBatch, stopBatchProbe, stopBatchExtract } from '@/api/wanted'
import { cancelJob as cancelTranslationQueueJob, stopBatchTranslate } from '@/api/translation'
import { stopRemuxJob } from '@/api/library'
import { stopVideoSyncJob, stopCleanupScan, stopRepair } from '@/api/system/tasks'
import { cancelWhisperJob } from '@/api/providers'

// ─── Batch runs (Queue / Translations tabs) ──────────────────────────────────

export function useStopWantedBatch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => stopWantedBatch(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-batch-status'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useStopBatchProbe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => stopBatchProbe(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-batch-probe-status'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useStopBatchExtract() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => stopBatchExtract(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted-batch-extract-status'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useStopBatchTranslate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => stopBatchTranslate(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['batch-status'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

/** Cooperative cancel of a RUNNING translation via the live queue
 *  (POST /translation/queue/<id>/cancel) — unlike `useCancelJob`, which only
 *  soft-cancels queued jobs. */
export function useCancelRunningTranslation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => cancelTranslationQueueJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

// ─── Scheduler & system tasks ────────────────────────────────────────────────

/** Abort a scheduler job's current run; the schedule itself stays active. */
export function useStopScheduledJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => stopScheduledJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useStopCleanupScan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => stopCleanupScan(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cleanup-scan'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useStopRepair() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => stopRepair(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

// ─── Media jobs (History tab stop buttons) ───────────────────────────────────

export function useStopRemuxJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => stopRemuxJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useStopVideoSyncJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => stopVideoSyncJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useCancelWhisperJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => cancelWhisperJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['whisper'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}
