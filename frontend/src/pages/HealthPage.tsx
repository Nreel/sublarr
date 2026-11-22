/**
 * Health page — "where does it hurt" overview of the library.
 *
 * Four views from GET /api/v1/health/library: series with missing subtitles,
 * wanted items stuck in a failure state (unmatched episodes), per-provider
 * health (circuit breaker ⋈ provider stats), and translation health (backend
 * failure counters, recent failed translation calls, and failed translation
 * jobs — before this block those errors were only visible behind one
 * episode's History button). Every row carries a badge naming its problem and
 * linking to the setting that fixes it (see lib/healthProblems); lists are
 * complete and paint in chunks as the reader scrolls.
 */
import { useTranslation } from 'react-i18next';
import { HeartPulse, Loader2, AlertTriangle, CheckCircle2 } from 'lucide-react';
import type { ReactNode, Ref } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '@/components/layout/PageHeader';
import { StatTile } from '@/components/statistics/primitives';
import { useInfiniteChunk } from '@/components/shared/useInfiniteChunk';
import { useLibraryHealth } from '@/hooks/useApi';
import { type HealthPipelineError, type HealthProblemRow, type HealthProviderRow, type HealthTranslationBackend, type HealthTranslationError } from '@/api/system/healthLibrary';
import { problemBadgeSpec, TIER_COLOR } from '@/lib/healthProblems';
import { formatRelativeTime, formatProviderName } from '@/lib/utils';

type T = (key: string) => string;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold text-secondary">{title}</h2>
      {children}
    </section>
  );
}

function Th({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`text-left text-[11px] font-semibold uppercase tracking-wider px-3 py-2 ${className}`}
      style={{ color: 'var(--text-muted)' }}
    >
      {children}
    </th>
  );
}

function BlockLabel({ label }: { label: string }) {
  return (
    <p
      className="text-[11px] font-semibold uppercase tracking-wider px-3 pt-2"
      style={{ color: 'var(--text-muted)' }}
    >
      {label}
    </p>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div
      className="flex items-center gap-2 px-3 py-6 text-sm"
      style={{ color: 'var(--text-secondary)' }}
    >
      <CheckCircle2 size={15} style={{ color: 'var(--success)' }} />
      {label}
    </div>
  );
}

/** Scroll sentinel that reveals the next chunk of a list. */
function SentinelRow({
  list,
  colSpan,
  t,
}: {
  list: { hasMore: boolean; sentinelRef: Ref<HTMLTableRowElement> };
  colSpan: number;
  t: T;
}) {
  if (!list.hasMore) return null;
  return (
    <tr ref={list.sentinelRef}>
      <td colSpan={colSpan} className="px-3 py-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
        {t('more')}
      </td>
    </tr>
  );
}

/**
 * The badge every problem row carries: a chip naming the fault, a one-line
 * explanation beside it, and the whole thing pointing at the setting that
 * resolves it. Unknown codes still render their raw text under the generic
 * badge, so a code added server-side never disappears from the page.
 */
function ProblemBadge({
  kind,
  fallbackLabel,
  count,
  showHint = true,
  t,
}: {
  kind: string | null | undefined;
  fallbackLabel?: string;
  /** Count of items behind this badge (series rows); omitted for single rows. */
  count?: number;
  showHint?: boolean;
  t: T;
}) {
  const spec = problemBadgeSpec(kind);
  const label = kind && spec.labelKey === 'badges.unknown.label' ? (fallbackLabel ?? kind) : t(spec.labelKey);
  const hint = t(spec.hintKey);
  return (
    <Link
      to={spec.href}
      className="inline-flex items-center gap-1.5 group"
      title={`${hint} — ${spec.href}`}
    >
      <span
        className="text-[10px] px-1.5 py-0.5 rounded font-bold uppercase group-hover:underline"
        style={{
          backgroundColor: `color-mix(in srgb, ${TIER_COLOR[spec.tier]} 12%, transparent)`,
          color: TIER_COLOR[spec.tier],
          fontFamily: 'var(--font-mono)',
        }}
      >
        {label}
        {count && count > 1 ? ` ×${count}` : ''}
      </span>
      {showHint && (
        <span
          className="text-[11px] truncate max-w-[220px] hidden lg:inline"
          style={{ color: 'var(--text-muted)' }}
        >
          {hint}
        </span>
      )}
    </Link>
  );
}

function ProblemRow({ item, t }: { item: HealthProblemRow; t: T }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td className="px-3 py-2">
        <div
          className="text-sm font-medium truncate max-w-xs"
          style={{ color: 'var(--text-primary)' }}
        >
          {item.title}
        </div>
        {item.season_episode && (
          <div
            className="text-[11px]"
            style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
          >
            {item.season_episode}
          </div>
        )}
      </td>
      <td
        className="px-3 py-2 text-xs uppercase"
        style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        {item.target_language}
      </td>
      <td className="px-3 py-2">
        <ProblemBadge kind={item.failure_kind} fallbackLabel={item.status} t={t} />
      </td>
      <td
        className="px-3 py-2 text-xs truncate max-w-[240px] hidden md:table-cell"
        title={item.error}
        style={{ color: 'var(--text-secondary)' }}
      >
        {item.error || '—'}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden sm:table-cell"
        style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        {item.search_count}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden lg:table-cell"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        {item.updated_at ? formatRelativeTime(item.updated_at) : ''}
      </td>
    </tr>
  );
}

function ProviderRow({ p, t }: { p: HealthProviderRow; t: T }) {
  const stateColor =
    p.breaker_state === 'closed' && !p.auto_disabled
      ? 'var(--success)'
      : p.breaker_state === 'half_open'
        ? 'var(--warning)'
        : 'var(--error)';
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          {p.degraded && <AlertTriangle size={13} style={{ color: 'var(--warning)' }} />}
          <span
            className="text-sm font-medium capitalize"
            style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}
          >
            {formatProviderName(p.provider)}
          </span>
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] px-1.5 py-0.5 rounded font-bold uppercase"
            style={{
              backgroundColor: `color-mix(in srgb, ${stateColor} 12%, transparent)`,
              color: stateColor,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {p.auto_disabled ? t('providers.auto_disabled') : t(`providers.state_${p.breaker_state}`)}
          </span>
          {/* The breaker state says *how* it is off, not *why*. A provider with
              a blank API key and one whose host is down both read "Open". */}
          {p.status_reason && p.status_reason !== 'ok' && (
            <ProblemBadge kind={p.status_reason} t={t} />
          )}
        </div>
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden sm:table-cell"
        style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        {p.searches}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums"
        style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        {p.hit_rate != null ? `${Math.round(p.hit_rate * 100)}%` : '—'}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden md:table-cell"
        style={{
          color: p.failed_downloads > 0 ? 'var(--warning)' : 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        {p.failed_downloads}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden lg:table-cell"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        {p.breaker_failures}
      </td>
    </tr>
  );
}

function TranslationBackendRow({ b, t }: { b: HealthTranslationBackend; t: T }) {
  const broken = b.failed > 0 || b.consecutive_failures > 0;
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          {broken && <AlertTriangle size={13} style={{ color: 'var(--warning)' }} />}
          <span
            className="text-sm font-medium"
            style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}
          >
            {b.backend}
          </span>
        </div>
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden sm:table-cell"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        {b.requests}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums"
        style={{
          color: b.failed > 0 ? 'var(--error)' : 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        {b.failed}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums"
        style={{
          color: b.consecutive_failures > 0 ? 'var(--error)' : 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        {b.consecutive_failures}
      </td>
      <td className="px-3 py-2">
        {broken ? (
          <div className="flex items-center gap-2">
            <ProblemBadge kind={b.last_error_kind} t={t} />
            <span
              className="text-xs truncate max-w-[240px] hidden md:inline"
              title={b.last_error}
              style={{ color: 'var(--error)' }}
            >
              {b.last_error || '—'}
            </span>
          </div>
        ) : (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            —
          </span>
        )}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden lg:table-cell"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        {b.last_failure_at ? formatRelativeTime(b.last_failure_at) : '—'}
      </td>
    </tr>
  );
}

function TranslationErrorRow({ e, t }: { e: HealthTranslationError; t: T }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td
        className="px-3 py-2 text-sm font-medium"
        style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}
      >
        {e.backend}
      </td>
      <td
        className="px-3 py-2 text-xs uppercase"
        style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        {e.source_lang} → {e.target_lang}
      </td>
      <td className="px-3 py-2">
        <ProblemBadge kind={e.error_kind} fallbackLabel={e.error_type || e.status} t={t} />
      </td>
      <td
        className="px-3 py-2 text-xs truncate max-w-[240px] hidden md:table-cell"
        title={`${e.error_type || e.status}: ${e.error_msg}`}
        style={{ color: 'var(--text-secondary)' }}
      >
        {e.error_msg || '—'}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden sm:table-cell"
        style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        {e.lines_count}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden lg:table-cell"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        {e.started_at ? formatRelativeTime(e.started_at) : ''}
      </td>
    </tr>
  );
}

function TranslationPipelineErrorRow({ e, t }: { e: HealthPipelineError; t: T }) {
  // The path is a media path; the file name is what identifies the item.
  const name = e.file_path.split(/[\\/]/).pop() || e.file_path;
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td
        className="px-3 py-2 text-sm font-medium truncate max-w-[260px]"
        title={e.file_path}
        style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}
      >
        {name}
      </td>
      <td
        className="px-3 py-2 text-xs uppercase hidden sm:table-cell"
        style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        {e.source_format || '—'}
      </td>
      <td className="px-3 py-2">
        <ProblemBadge kind={e.error_kind} t={t} />
      </td>
      <td
        className="px-3 py-2 text-xs truncate max-w-[320px] hidden md:table-cell"
        title={e.error}
        style={{ color: 'var(--error)' }}
      >
        {e.error || '—'}
      </td>
      <td
        className="px-3 py-2 text-xs tabular-nums hidden lg:table-cell"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        {e.created_at ? formatRelativeTime(e.created_at) : ''}
      </td>
    </tr>
  );
}

export function HealthPage() {
  const { t } = useTranslation('health');

  const { data, isLoading } = useLibraryHealth();

  // Every list is complete, so paint it in chunks: rows appear as the reader
  // scrolls to the bottom of the box instead of the page rendering thousands
  // of rows (or hiding the ones past a cap) up front.
  const seriesList = useInfiniteChunk(data?.series ?? [], 60);
  const problemList = useInfiniteChunk(data?.problems ?? [], 60);
  const providerList = useInfiniteChunk(
    [...(data?.providers ?? []).filter(p => p.degraded), ...(data?.providers ?? []).filter(p => !p.degraded)],
    40,
  );
  const backendList = useInfiniteChunk(data?.translation?.backends ?? [], 40);
  const errorList = useInfiniteChunk(data?.translation?.recent_errors ?? [], 40);
  const pipelineList = useInfiniteChunk(data?.translation?.pipeline_errors ?? [], 40);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-60" style={{ color: 'var(--text-muted)' }}>
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  const totals = data?.totals;

  return (
    // Data surface — tables of problem items benefit from the full canvas, so
    // this joins the "wide" tier rather than keeping its own 1024px cap.
    <div className="w-full p-4 space-y-6">
      <PageHeader title={t('title')} subtitle={t('subtitle')} className="mb-0" />

      {/* Totals */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
        <StatTile label={t('totals.wanted')} value={totals?.wanted ?? 0} />
        <StatTile label={t('totals.problems')} value={totals?.problems ?? 0} />
        <StatTile label={t('totals.unmatched')} value={totals?.unmatched ?? 0} />
        <StatTile label={t('totals.series_affected')} value={totals?.series_affected ?? 0} />
        <StatTile label={t('totals.providers_degraded')} value={totals?.providers_degraded ?? 0} />
        {/* Sat next to a reassuring zero before: "0 degraded" and "no provider
            activity recorded yet" are different statements (forgejo #17). */}
        <StatTile
          label={t('totals.providers_no_activity')}
          value={totals?.providers_no_activity ?? 0}
        />
      </div>

      {/* Series with missing subtitles */}
      <Section title={t('series.title')}>
        <div
          className="rounded-lg overflow-hidden"
          style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          {data?.series.length ? (
            <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
              <table className="w-full min-w-[420px]">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <Th>{t('series.col_title')}</Th>
                    <Th>{t('series.col_type')}</Th>
                    <Th>{t('series.col_missing')}</Th>
                    <Th>{t('series.col_problems')}</Th>
                  </tr>
                </thead>
                <tbody>
                  {seriesList.visible.map(s => (
                    <tr
                      key={`${s.item_type}:${s.title}`}
                      style={{ borderBottom: '1px solid var(--border)' }}
                    >
                      <td
                        className="px-3 py-2 text-sm font-medium truncate max-w-xs"
                        style={{ color: 'var(--text-primary)' }}
                      >
                        {s.title}
                      </td>
                      <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                        {t(`series.type_${s.item_type}`)}
                      </td>
                      <td
                        className="px-3 py-2 text-xs tabular-nums"
                        style={{ color: 'var(--warning)', fontFamily: 'var(--font-mono)' }}
                      >
                        {s.missing}
                      </td>
                      <td className="px-3 py-2">
                        {s.problems > 0 ? (
                          <div className="flex flex-wrap items-center gap-1.5">
                            {Object.entries(s.problem_kinds)
                              .sort(([, a], [, b]) => b - a)
                              .map(([kind, count]) => (
                                <ProblemBadge key={kind} kind={kind} count={count} showHint={false} t={t} />
                              ))}
                            {/* The raw total still reads as a number for scanning. */}
                            <span
                              className="text-xs tabular-nums"
                              style={{ color: 'var(--error)', fontFamily: 'var(--font-mono)' }}
                            >
                              {s.problems}
                            </span>
                          </div>
                        ) : (
                          <span
                            className="text-xs tabular-nums"
                            style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
                          >
                            0
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  <SentinelRow list={seriesList} colSpan={4} t={t} />
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState label={t('series.empty')} />
          )}
        </div>
        <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {t('series.hint')}{' '}
          <Link to="/wanted" className="underline" style={{ color: 'var(--accent)' }}>
            {t('series.wanted_link')}
          </Link>
        </p>
      </Section>

      {/* Problem items (failed / unmatched) */}
      <Section title={t('problems.title')}>
        <div
          className="rounded-lg overflow-hidden"
          style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          {data?.problems.length ? (
            <div className="overflow-x-auto max-h-[380px] overflow-y-auto">
              <table className="w-full min-w-[520px]">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <Th>{t('problems.col_item')}</Th>
                    <Th>{t('problems.col_lang')}</Th>
                    <Th>{t('problems.col_kind')}</Th>
                    <Th className="hidden md:table-cell">{t('problems.col_error')}</Th>
                    <Th className="hidden sm:table-cell">{t('problems.col_attempts')}</Th>
                    <Th className="hidden lg:table-cell">{t('problems.col_updated')}</Th>
                  </tr>
                </thead>
                <tbody>
                  {problemList.visible.map(item => (
                    <ProblemRow key={item.id} item={item} t={t} />
                  ))}
                  <SentinelRow list={problemList} colSpan={6} t={t} />
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState label={t('problems.empty')} />
          )}
        </div>
      </Section>

      {/* Provider health */}
      <Section title={t('providers.title')}>
        <div
          className="rounded-lg overflow-hidden"
          style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          {data?.providers.length ? (
            <div className="overflow-x-auto max-h-[380px] overflow-y-auto">
              <table className="w-full min-w-[520px]">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <Th>{t('providers.col_provider')}</Th>
                    <Th>{t('providers.col_state')}</Th>
                    <Th className="hidden sm:table-cell">{t('providers.col_searches')}</Th>
                    <Th>{t('providers.col_hit_rate')}</Th>
                    <Th className="hidden md:table-cell">{t('providers.col_failed_downloads')}</Th>
                    <Th className="hidden lg:table-cell">{t('providers.col_breaker_failures')}</Th>
                  </tr>
                </thead>
                <tbody>
                  {providerList.visible.map(p => (
                    <ProviderRow key={p.provider} p={p} t={t} />
                  ))}
                  <SentinelRow list={providerList} colSpan={6} t={t} />
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState label={t('providers.empty')} />
          )}
        </div>
      </Section>

      {/* Translation health */}
      <Section title={t('translation.title')}>
        <div
          className="rounded-lg overflow-hidden"
          style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          {data?.translation?.backends.length ? (
            <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
              <table className="w-full min-w-[520px]">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <Th>{t('translation.col_backend')}</Th>
                    <Th className="hidden sm:table-cell">{t('translation.col_requests')}</Th>
                    <Th>{t('translation.col_failed')}</Th>
                    <Th>{t('translation.col_consecutive')}</Th>
                    <Th className="hidden md:table-cell">{t('translation.col_last_error')}</Th>
                    <Th className="hidden lg:table-cell">{t('translation.col_last_failure')}</Th>
                  </tr>
                </thead>
                <tbody>
                  {backendList.visible.map(b => (
                    <TranslationBackendRow key={b.backend} b={b} t={t} />
                  ))}
                  <SentinelRow list={backendList} colSpan={6} t={t} />
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState label={t('translation.empty_backends')} />
          )}
        </div>

        <div
          className="rounded-lg overflow-hidden"
          style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          {data?.translation?.pipeline_errors.length ? (
            <>
              <BlockLabel label={t('translation.pipeline_title')} />
              <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
                <table className="w-full min-w-[460px]">
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)' }}>
                      <Th>{t('translation.col_file')}</Th>
                      <Th className="hidden sm:table-cell">{t('translation.col_format')}</Th>
                      <Th>{t('translation.col_reason')}</Th>
                      <Th className="hidden md:table-cell">{t('translation.col_error')}</Th>
                      <Th className="hidden lg:table-cell">{t('translation.col_when')}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {pipelineList.visible.map((e, i) => (
                      <TranslationPipelineErrorRow key={`${e.job_id}:${i}`} e={e} t={t} />
                    ))}
                    <SentinelRow list={pipelineList} colSpan={5} t={t} />
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
          {data?.translation?.recent_errors.length ? (
            <>
              <BlockLabel label={t('translation.backend_errors_title')} />
              <div className="overflow-x-auto max-h-[380px] overflow-y-auto">
                <table className="w-full min-w-[520px]">
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)' }}>
                      <Th>{t('translation.col_backend')}</Th>
                      <Th className="hidden sm:table-cell">{t('translation.col_langs')}</Th>
                      <Th>{t('translation.col_reason')}</Th>
                      <Th className="hidden md:table-cell">{t('translation.col_message')}</Th>
                      <Th className="hidden sm:table-cell">{t('translation.col_lines')}</Th>
                      <Th className="hidden lg:table-cell">{t('translation.col_when')}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {errorList.visible.map((e, i) => (
                      <TranslationErrorRow key={`${e.backend}:${e.started_at}:${i}`} e={e} t={t} />
                    ))}
                    <SentinelRow list={errorList} colSpan={6} t={t} />
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
          {!data?.translation?.pipeline_errors.length &&
          !data?.translation?.recent_errors.length ? (
            <EmptyState label={t('translation.empty_errors')} />
          ) : null}
        </div>

        <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {t('translation.summary', {
            failures7d: data?.translation?.failures_7d ?? 0,
            stuck: data?.translation?.stuck_items ?? 0,
          })}
        </p>
        <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {t('translation.hint')}
        </p>
      </Section>

      <div className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--text-muted)' }}>
        <HeartPulse size={12} />
        {t('refresh_note')}
      </div>
    </div>
  );
}
