import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useActivity, useStopRemuxJob, useStopVideoSyncJob, useCancelWhisperJob, useStopCleanupScan, useStopScheduledJob, useStopRepair } from '@/hooks/useSystemApi'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ProgressBar } from '@/components/shared/ProgressBar'
import { toast } from '@/components/shared/Toast'
import { parseMediaTitle, formatRelativeTime } from '@/lib/utils'
import type { ActivityEntry } from '@/api/system/activity'
import { X } from 'lucide-react'

const EVENT_TYPE_COLORS: Record<string, string> = {
  download: 'var(--success)',
  translate: 'var(--info, var(--accent))',
  extract: 'var(--accent)',
  delete: 'var(--danger)',
  scan: 'var(--text-muted)',
  search: 'var(--success)',
  whisper: 'var(--info, var(--accent))',
  remux: 'var(--upgrade)',
  sync: 'var(--upgrade)',
  cleanup: 'var(--warning)',
  backup: 'var(--text-muted)',
  hook: 'var(--warning)',
  automation: 'var(--accent)',
  anidb: 'var(--info, var(--accent))',
  repair: 'var(--danger)',
}

const PER_PAGE = 50

/** Live progress written by the runners into details["progress"] while a row is running. */
interface RowProgress {
  done: number
  total: number
  current: string
  phase: string
}

function rowProgress(entry: ActivityEntry): RowProgress | null {
  if (entry.status !== 'running') return null
  const raw = entry.details?.progress
  if (typeof raw !== 'object' || raw === null) return null
  const p = raw as Record<string, unknown>
  return {
    done: typeof p.done === 'number' ? p.done : 0,
    total: typeof p.total === 'number' ? p.total : 0,
    current: typeof p.current === 'string' ? p.current : '',
    phase: typeof p.phase === 'string' ? p.phase : '',
  }
}

function TypeBadge({ entry }: { entry: ActivityEntry }) {
  return (
    <span
      data-testid={`activity-type-${entry.id}`}
      data-type={entry.event_type}
      style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: '3px',
        fontSize: '10px',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.3px',
        color: EVENT_TYPE_COLORS[entry.event_type] ?? 'var(--text-muted)',
        border: `1px solid ${EVENT_TYPE_COLORS[entry.event_type] ?? 'var(--border)'}`,
        flexShrink: 0,
        whiteSpace: 'nowrap',
      }}
    >
      {entry.event_type}
    </span>
  )
}

function ActivityRow({
  entry,
  onStop,
  stopping,
}: {
  entry: ActivityEntry
  onStop?: () => void
  stopping?: boolean
}) {
  const { t } = useTranslation('activity')
  const media = entry.file_path ? parseMediaTitle(entry.file_path) : null
  const progress = rowProgress(entry)

  return (
    <div
      data-testid={`activity-row-${entry.id}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '7px 12px',
        borderBottom: '1px solid var(--border)',
        fontSize: '13px',
      }}
    >
      <TypeBadge entry={entry} />

      <span
        style={{ flex: 1, minWidth: 0, color: 'var(--text-primary)' }}
        title={entry.file_path ?? undefined}
      >
        {progress ? (
          <span style={{ display: 'flex', flexDirection: 'column', gap: '3px', minWidth: 0 }}>
            <span
              style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              data-testid={`activity-progress-current-${entry.id}`}
            >
              {progress.current || t('history.progress_running', 'Running')}
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
              <ProgressBar value={progress.done} max={progress.total} showLabel={false} className="min-w-0 flex-1" />
              <span
                data-testid={`activity-progress-label-${entry.id}`}
                style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}
              >
                {progress.phase ? t(`history.phase_${progress.phase}`, progress.phase) : ''}
                {progress.total > 0 ? ` · ${progress.done}/${progress.total}` : ''}
              </span>
            </span>
          </span>
        ) : media ? (
          <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {media.title}
            {media.episodeCode && (
              <span style={{ color: 'var(--text-muted)', marginLeft: '5px', fontSize: '11px' }}>
                {media.episodeCode}
              </span>
            )}
          </span>
        ) : (
          <span style={{ color: 'var(--text-muted)' }}>
            {t('queue.scanner_running', 'Wanted scan')}
          </span>
        )}
      </span>

      <span style={{ flexShrink: 0 }}>
        <StatusBadge status={entry.status} />
      </span>

      {entry.status === 'running' && onStop && (
        <button
          type="button"
          aria-label={t('history.stop_running')}
          title={t('history.stop_running')}
          data-testid={`activity-stop-${entry.id}`}
          onClick={onStop}
          disabled={stopping}
          className="shrink-0 p-1 rounded-md text-muted hover:text-error hover:bg-surface-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <X size={14} />
        </button>
      )}

      <span style={{ fontSize: '11px', color: 'var(--text-muted)', flexShrink: 0, whiteSpace: 'nowrap' }}>
        {formatRelativeTime(entry.created_at)}
      </span>
    </div>
  )
}

const EVENT_TYPES = [
  'download', 'translate', 'extract', 'delete', 'scan',
  'whisper', 'remux', 'sync', 'cleanup', 'backup', 'hook', 'automation', 'anidb', 'repair',
] as const

const EVENT_TYPE_I18N_KEYS: Record<string, string> = {
  download: 'history.filter_downloads',
  translate: 'history.filter_translate',
  extract: 'history.filter_extract',
  delete: 'history.filter_delete',
  scan: 'history.filter_scan',
  whisper: 'history.filter_whisper',
  remux: 'history.filter_remux',
  sync: 'history.filter_sync',
  cleanup: 'history.filter_cleanup',
  backup: 'history.filter_backup',
  hook: 'history.filter_hook',
  automation: 'history.filter_automation',
  anidb: 'history.filter_anidb',
  repair: 'history.filter_repair',
}

export function ActivityLogTab({ defaultFilter, hideFilter }: { defaultFilter?: string; hideFilter?: boolean }) {
  const { t } = useTranslation('activity')
  const [page, setPage] = useState(1)
  const [typeFilter, setTypeFilter] = useState<string | undefined>(defaultFilter)

  const stopRemux = useStopRemuxJob()
  const stopSync = useStopVideoSyncJob()
  const cancelWhisper = useCancelWhisperJob()
  const stopCleanupScan = useStopCleanupScan()
  const stopScheduled = useStopScheduledJob()
  const stopRepair = useStopRepair()
  const stopping =
    stopRemux.isPending || stopSync.isPending || cancelWhisper.isPending ||
    stopCleanupScan.isPending || stopScheduled.isPending || stopRepair.isPending
  const stopOptions = {
    onSuccess: () => toast(t('history.stop_success'), 'success'),
    onError: () => toast(t('history.stop_failed'), 'error'),
  }
  const jobIdOf = (entry: ActivityEntry): string | null =>
    entry.details?.job_id != null ? String(entry.details.job_id) : null

  /** Stop control for a running row, picked by event type. Terminal kinds
   *  (download/translate/delete/scan/search/backup/hook) have no stop — the
   *  row is already finished. */
  const stopFor = (entry: ActivityEntry): (() => void) | null => {
    const jobId = jobIdOf(entry)
    switch (entry.event_type) {
      case 'remux':
        return jobId ? () => stopRemux.mutate(jobId, stopOptions) : null
      case 'sync':
        return jobId ? () => stopSync.mutate(jobId, stopOptions) : null
      case 'whisper':
        return jobId ? () => cancelWhisper.mutate(jobId, stopOptions) : null
      case 'cleanup':
        return entry.details?.kind === 'dedup_scan'
          ? () => stopCleanupScan.mutate(undefined, stopOptions)
          : () => stopScheduled.mutate('cleanup', stopOptions)
      case 'automation':
        return () => stopScheduled.mutate('subtitle_automation', stopOptions)
      case 'anidb':
        return () => stopScheduled.mutate('anidb_sync', stopOptions)
      case 'repair':
        return () => stopRepair.mutate(undefined, stopOptions)
      default:
        return null
    }
  }

  const { data, isLoading } = useActivity(page, PER_PAGE, typeFilter)
  const entries = data?.data ?? []
  const total = data?.total ?? 0
  const totalPages = data?.total_pages ?? 1

  if (isLoading) {
    return (
      <div data-testid="activity-loading" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
        {t('activity.loading', 'Loading…')}
      </div>
    )
  }

  return (
    <div data-testid="activity-log-tab">
      {/* Filter bar */}
      {!hideFilter && (
        <div style={{ display: 'flex', gap: '6px', marginBottom: '12px' }}>
          <button
            onClick={() => { setTypeFilter(undefined); setPage(1) }}
            style={{
              padding: '4px 10px',
              borderRadius: '4px',
              border: '1px solid var(--border)',
              background: typeFilter === undefined ? 'var(--accent)' : 'transparent',
              color: typeFilter === undefined ? '#fff' : 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            {t('filter.all', 'All')}
          </button>
          {EVENT_TYPES.map((type) => (
            <button
              key={type}
              onClick={() => { setTypeFilter(type); setPage(1) }}
              style={{
                padding: '4px 10px',
                borderRadius: '4px',
                border: '1px solid var(--border)',
                background: typeFilter === type ? 'var(--accent)' : 'transparent',
                color: typeFilter === type ? '#fff' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              {t(EVENT_TYPE_I18N_KEYS[type], type)}
            </button>
          ))}
        </div>
      )}

      {/* Table */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
        {entries.length === 0 ? (
          <div
            data-testid="activity-empty"
            style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}
          >
            {t('log_empty', 'No activity recorded yet.')}
          </div>
        ) : (
          entries.map((entry) => (
            <ActivityRow key={entry.id} entry={entry} onStop={stopFor(entry) ?? undefined} stopping={stopping} />
          ))
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginTop: '12px', alignItems: 'center' }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            style={{ padding: '4px 10px', border: '1px solid var(--border)', borderRadius: '4px',
              cursor: page <= 1 ? 'not-allowed' : 'pointer', opacity: page <= 1 ? 0.4 : 1 }}
          >
            ←
          </button>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {page} / {totalPages} ({total} {t('log_events', 'events')})
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            style={{ padding: '4px 10px', border: '1px solid var(--border)', borderRadius: '4px',
              cursor: page >= totalPages ? 'not-allowed' : 'pointer', opacity: page >= totalPages ? 0.4 : 1 }}
          >
            →
          </button>
        </div>
      )}
    </div>
  )
}
