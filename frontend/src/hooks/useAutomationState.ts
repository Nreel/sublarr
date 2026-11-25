import { useScannerStatus, useWantedBatchStatus, useWantedBatchProbeStatus } from '@/hooks/useWantedApi'
import { useSchedulerJobs } from '@/hooks/useSchedulerJobs'

export type AutomationState = 'active' | 'idle' | 'paused' | 'partial'

/** Job ids that make up the wanted-subtitle automation pipeline. */
const AUTOMATION_JOB_IDS = ['wanted_scanner', 'wanted_search'] as const

/**
 * Single source of truth for the automation status shown in the dashboard
 * status stripe AND the footer status bar. Previously the two widgets derived
 * "paused"/"ready" from different endpoints and contradicted each other.
 *
 * - 'active'  — a scan/search/batch operation is running right now
 * - 'paused'  — every scheduler job of the pipeline is paused
 * - 'partial' — some (not all) pipeline jobs are paused
 * - 'idle'    — armed and waiting for the next scheduled run
 */
export function useAutomationState(refetchMs = 10000) {
  // Same idle cadence as the scheduler/batch polls the caller passed; the
  // scanner-status hook's own default (30s) would drift from the 60s footer.
  const { data: scannerStatus } = useScannerStatus(refetchMs)
  const { data: scheduler } = useSchedulerJobs(refetchMs)
  const { data: batchSearch } = useWantedBatchStatus(refetchMs)
  const { data: batchProbe } = useWantedBatchProbeStatus()

  const isRunning = Boolean(
    scannerStatus?.is_scanning ||
      scannerStatus?.is_searching ||
      batchSearch?.running ||
      batchProbe?.running
  )

  const jobs = scheduler?.jobs ?? []
  const automationJobs = jobs.filter((j) =>
    (AUTOMATION_JOB_IDS as readonly string[]).includes(j.id)
  )
  const pausedJobs = automationJobs.filter((j) => j.paused)

  const state: AutomationState = isRunning
    ? 'active'
    : automationJobs.length > 0 && pausedJobs.length === automationJobs.length
      ? 'paused'
      : pausedJobs.length > 0
        ? 'partial'
        : 'idle'

  return {
    state,
    isRunning,
    pausedJobIds: pausedJobs.map((j) => j.id),
    scannerStatus,
    batchSearch,
    batchProbe,
  }
}
