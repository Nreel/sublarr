import { useState, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useHealth, useUpdateInfo } from '@/hooks/useApi'
import { formatVersion } from '@/lib/version'
import { useProviderHealth } from '@/hooks/useProvidersApi'
import { useAutomationState } from '@/hooks/useAutomationState'

/** Dot colour per state value reported by /health. */
const STATE_COLOR: Record<string, string> = {
  alive: 'var(--success)',
  ok: 'var(--success)',
  problem: 'var(--error)',
  down: 'var(--error)',
  not_configured: 'var(--text-muted)',
  timeout: 'var(--warning)',
}

/** The five crucial states, in the order the footer shows them. */
const STATE_ITEMS = [
  { key: 'backend', labelKey: 'status.state_backend', fallback: 'backend' },
  { key: 'database', labelKey: 'status.state_database', fallback: 'db' },
  { key: 'sonarr', labelKey: 'status.state_sonarr', fallback: 'Sonarr' },
  { key: 'radarr', labelKey: 'status.state_radarr', fallback: 'Radarr' },
  { key: 'jellyfin', labelKey: 'status.state_jellyfin', fallback: 'Jellyfin' },
] as const

/** Footer links carry the strip's own colour and stay text-shaped. */
const LINK_STYLE = { color: 'inherit', textDecoration: 'none' }

/** A running scan/batch operation and when it started. */
interface Activity {
  label: string
  started_at: string | null
}

/** UTC ISO → the local time the footer reports in the hover text. */
function formatStartedAt(iso: string): string {
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return iso
  return new Date(ms).toLocaleTimeString()
}

export function StatusBar() {
  const { t } = useTranslation('common')
  const { data: health } = useHealth()
  const { data: updateInfo } = useUpdateInfo()
  const { state: automationState, pausedJobIds, scannerStatus, batchSearch, batchProbe } =
    useAutomationState(60_000)
  const { data: providerHealth } = useProviderHealth(60_000)
  const [popoverOpen, setPopoverOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)

  const isHealthy = health?.status === 'healthy'
  const states = health?.states
  const isScanning = scannerStatus?.is_scanning ?? false
  const isBatchSearching = batchSearch?.running ?? false
  const isBatchExtracting = batchProbe?.running ?? false
  const hasUpdate = updateInfo?.available === true

  const throttledProviders = useMemo(() => {
    const items = providerHealth?.providers ?? []
    return items
      .filter(
        (p) =>
          p.circuit_breaker_state === 'open' ||
          p.throttle_reason === 'rate_limited' ||
          p.auto_disabled,
      )
      .map((p) => p.name)
  }, [providerHealth])

  const stateValue = (value: string) => t(`status.state_${value}`, value.replace(/_/g, ' '))

  const healthTitle = states
    ? t('status.health_summary', {
        backend: stateValue(states.backend),
        database: stateValue(states.database),
        sonarr: stateValue(states.sonarr),
        radarr: stateValue(states.radarr),
        jellyfin: stateValue(states.jellyfin),
        defaultValue:
          'Backend: {{backend}} · DB: {{database}} · Sonarr: {{sonarr}} · Radarr: {{radarr}} · Jellyfin: {{jellyfin}} — open health overview',
      })
    : t('status.health_summary_offline', {
        status: isHealthy ? t('app.online', 'Online') : t('app.offline', 'Offline'),
        defaultValue: 'Backend {{status}} — open health overview',
      })

  // Same scheduler derivation as the dashboard status stripe (useAutomationState)
  // so footer and dashboard can never contradict each other — only the wording
  // differs, and it names what is actually paused instead of "partially paused".
  const automationLabel =
    automationState === 'active'
      ? t('status.automation_running', 'Automation: running')
      : automationState === 'paused'
        ? t('status.automation_paused', 'Automation: paused')
        : automationState === 'partial'
          ? pausedJobIds.includes('wanted_scanner')
            ? t('status.automation_scanner_paused', 'Automation: scanner paused')
            : t('status.automation_search_paused', 'Automation: search paused')
          : t('status.automation_event_driven', 'Automation: event-driven')

  const pausedIds = pausedJobIds.join(', ')
  const automationTitle =
    automationState === 'active'
      ? t('status.automation_title_running', 'A scan, search or batch run is in flight — open automation settings')
      : automationState === 'paused'
        ? t('status.automation_title_paused', {
            jobs: pausedIds,
            defaultValue: 'Both pipeline jobs are paused ({{jobs}}) — nothing runs until resumed',
          })
        : automationState === 'partial'
          ? pausedJobIds.includes('wanted_scanner')
            ? t('status.automation_title_scanner_paused', {
                jobs: pausedIds,
                defaultValue: 'Scanner paused ({{jobs}}), search still scheduled',
              })
            : t('status.automation_title_search_paused', {
                jobs: pausedIds,
                defaultValue: 'Search paused ({{jobs}}), scanner still scheduled',
              })
          : t('status.automation_title_idle', 'Nothing running; the scheduler fires on its next scheduled run')

  const activities: Activity[] = []
  if (isBatchExtracting) {
    activities.push({ label: t('status.extracting', 'Extracting'), started_at: batchProbe?.started_at ?? null })
  }
  if (isBatchSearching) {
    activities.push({ label: t('status.batch_searching', 'Batch search'), started_at: batchSearch?.started_at ?? null })
  }
  if (isScanning) {
    activities.push({ label: t('status.scanning', 'Scanning'), started_at: scannerStatus?.scan_started_at ?? null })
  }
  if (scannerStatus?.is_searching) {
    activities.push({ label: t('status.searching', 'Searching'), started_at: scannerStatus?.search_started_at ?? null })
  }
  // Several runs can overlap; the footer names the one that started last.
  const latestActivity = activities.reduce<Activity | null>((latest, a) => {
    if (!latest) return a
    const latestMs = latest.started_at ? Date.parse(latest.started_at) : -Infinity
    const aMs = a.started_at ? Date.parse(a.started_at) : -Infinity
    return aMs > latestMs ? a : latest
  }, null)

  const activityTitle = latestActivity
    ? t('status.activity_title', {
        label: latestActivity.label,
        time: latestActivity.started_at ? formatStartedAt(latestActivity.started_at) : '—',
        defaultValue: 'Last activity: {{label}}, started {{time}}',
      })
    : t('status.activity_title_none', 'No scan or batch activity running')

  const throttledTitle =
    throttledProviders.length > 0
      ? t('status.throttled_title', {
          names: throttledProviders.join(', '),
          defaultValue: '{{names}} — open providers',
        })
      : t('status.no_throttled_title', 'No provider is circuit-open, rate-limited or auto-disabled — open providers')

  const versionTitle = hasUpdate
    ? t('status.version_update_title', {
        version: health?.version ?? '...',
        latest: formatVersion(updateInfo?.latest),
        defaultValue: 'Running v{{version}} — update to {{latest}} available, click for release notes',
      })
    : t('status.version_title', {
        version: health?.version ?? '...',
        defaultValue: 'Running v{{version}}',
      })

  useEffect(() => {
    if (!popoverOpen) return
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setPopoverOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [popoverOpen])

  return (
    <div
      data-testid="status-bar"
      className="fixed bottom-0 left-0 right-0 z-30 hidden md:flex items-center"
      style={{
        height: 26,
        backgroundColor: 'var(--bg-primary)',
        borderTop: '1px solid var(--border)',
        marginLeft: 'var(--sidebar-width, 60px)',
        padding: '0 14px',
        gap: '14px',
        fontSize: 10,
        color: 'var(--text-muted)',
        fontFamily: 'var(--font-mono)',
      }}
    >
      {/* Crucial states: backend, database, Sonarr, Radarr, Jellyfin */}
      <Link
        data-testid="status-bar-health"
        to="/health"
        title={healthTitle}
        className="flex items-center gap-1.5"
        style={LINK_STYLE}
      >
        {states ? (
          STATE_ITEMS.map((item) => {
            const value = states[item.key]
            return (
              <span key={item.key} className="flex items-center gap-1">
                <span
                  data-testid={`status-bar-state-${item.key}`}
                  data-state={value}
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: STATE_COLOR[value] ?? 'var(--text-muted)' }}
                />
                <span>{t(item.labelKey, item.fallback)}</span>
              </span>
            )
          })
        ) : (
          <span className="flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: isHealthy ? 'var(--success)' : 'var(--error)' }}
            />
            <span>{isHealthy ? t('app.online', 'Online') : t('app.offline', 'Offline')}</span>
          </span>
        )}
      </Link>

      {/* Separator */}
      <div className="h-3" style={{ borderLeft: '1px solid var(--border)' }} />

      {/* Automation status */}
      <Link
        data-testid="status-bar-automation"
        to="/settings/automation"
        title={automationTitle}
        style={LINK_STYLE}
      >
        {automationLabel}
      </Link>

      {/* Separator */}
      <div className="h-3" style={{ borderLeft: '1px solid var(--border)' }} />

      {/* Version */}
      <div className="relative" ref={popoverRef}>
        {hasUpdate ? (
          <button
            data-testid="status-bar-version"
            onClick={() => setPopoverOpen((o) => !o)}
            className="flex items-center gap-1 cursor-pointer"
            title={versionTitle}
            style={{
              color: 'rgb(251,191,36)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              background: 'none',
              border: 'none',
              padding: 0,
            }}
          >
            <span
              data-testid="status-bar-update-dot"
              className="w-1.5 h-1.5 rounded-full shrink-0 animate-pulse"
              style={{ backgroundColor: 'rgb(251,191,36)' }}
            />
            v{health?.version ?? '...'}
          </button>
        ) : (
          <span data-testid="status-bar-version" title={versionTitle}>
            v{health?.version ?? '...'}
          </span>
        )}

        {hasUpdate && popoverOpen && (
          <div
            data-testid="status-bar-update-popover"
            className="absolute bottom-full mb-2 left-0 rounded shadow-lg"
            style={{
              backgroundColor: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              padding: '8px 10px',
              fontSize: 11,
              minWidth: 200,
              fontFamily: 'var(--font-sans)',
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap',
            }}
          >
            <div style={{ color: 'rgb(251,191,36)', fontWeight: 600, marginBottom: 4 }}>
              ↑ {formatVersion(updateInfo?.latest)} {t('update.available')}
            </div>
            <a
              href={updateInfo?.url ?? '#'}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--accent)', textDecoration: 'none' }}
            >
              {t('update.view_release')}
            </a>
          </div>
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Throttled providers — always shown, green when nothing is throttled */}
      <Link
        data-testid="status-bar-throttled"
        to="/providers"
        title={throttledTitle}
        className="flex items-center gap-1"
        style={LINK_STYLE}
      >
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{
            backgroundColor: throttledProviders.length > 0 ? 'var(--warning)' : 'var(--success)',
          }}
        />
        {throttledProviders.length > 0
          ? t('status.providers_throttled', {
              count: throttledProviders.length,
              defaultValue: '{{count}} provider(s) throttled',
            })
          : t('status.providers_no_throttled', 'No throttled providers')}
      </Link>

      {/* Scanner / batch activity — always shown, green dot when idle */}
      <Link
        data-testid="status-bar-scanning"
        to="/activity"
        title={activityTitle}
        className="flex items-center gap-1"
        style={LINK_STYLE}
      >
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={
            latestActivity
              ? {
                  backgroundColor: 'var(--accent)',
                  animation: 'dotGlow 1.5s ease-in-out infinite',
                }
              : { backgroundColor: 'var(--text-muted)' }
          }
        />
        {latestActivity
          ? latestActivity.label
          : t('status.activity_none', 'No activity')}
      </Link>
    </div>
  )
}
