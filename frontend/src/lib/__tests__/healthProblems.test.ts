import { describe, it, expect } from 'vitest'
import { problemBadgeSpec, healthProblemCount } from '../healthProblems'
import en from '@/i18n/locales/en/health.json'
import de from '@/i18n/locales/de/health.json'

/** Every code the backend can emit on /api/v1/health/library. A code missing
 *  here (or lacking locale strings) would show a raw key instead of a badge. */
const CODES = [
  'no_result', 'no_result_slow', 'provider_error', 'file_missing', 'translation_error', 'scan_failed', 'unsourceable', 'failed',
  'auto_disabled', 'circuit_open', 'credentials_rejected', 'host_unreachable', 'consecutive_failures',
  'no_results', 'no_credentials', 'not_initialized', 'low_hit_rate', 'no_activity',
  'timeout', 'line_mismatch', 'backend_auth', 'backend_quota', 'backend_unreachable', 'backend_error',
  'source_missing', 'signs_only', 'unsupported_format', 'outside_media', 'job_error',
  'scheduler_error', 'timeout_not_started', 'timeout_abandoned', 'missed', 'cancelled',
  'whisper_failed', 'sync_failed', 'remux_failed', 'extract_failed', 'cleanup_failed',
  'backup_failed', 'hook_failed', 'automation_failed', 'anidb_failed', 'repair_failed',
  'notification_failed',
]

function lookup(locale: Record<string, unknown>, key: string): string | undefined {
  let v: unknown = locale
  for (const part of key.split('.')) {
    if (typeof v !== 'object' || v === null || !(part in v)) return undefined
    v = (v as Record<string, unknown>)[part]
  }
  return typeof v === 'string' ? v : undefined
}

describe('problemBadgeSpec', () => {
  it.each(CODES)('%s links to a settings route and has localized text in en and de', code => {
    const spec = problemBadgeSpec(code)
    expect(spec.href.startsWith('/settings/')).toBe(true)
    expect(lookup(en as unknown as Record<string, unknown>, spec.labelKey)).toBeDefined()
    expect(lookup(en as unknown as Record<string, unknown>, spec.hintKey)).toBeDefined()
    expect(lookup(de as unknown as Record<string, unknown>, spec.labelKey)).toBeDefined()
    expect(lookup(de as unknown as Record<string, unknown>, spec.hintKey)).toBeDefined()
  })

  it('falls back to a generic badge for unknown and empty codes', () => {
    for (const code of ['made_up_kind', '', null, undefined]) {
      const spec = problemBadgeSpec(code)
      expect(spec.href).toBe('/settings/system/diagnostics')
      expect(lookup(en as unknown as Record<string, unknown>, spec.labelKey)).toBeDefined()
    }
  })
})

describe('healthProblemCount', () => {
  it('counts stuck items, degraded providers, recent translation failures, and new failure sections', () => {
    expect(
      healthProblemCount({
        totals: { problems: 5, providers_degraded: 2 },
        translation: { failures_7d: 3 },
        scheduler_errors: [{}],
        whisper_errors: [{}, {}],
        sync_errors: [{}],
        ops_errors: [{}, {}, {}],
        hook_errors: [{}],
        backup_errors: [{}],
      } as never),
    ).toBe(19)
  })

  it('is zero when the payload is missing or everything is healthy', () => {
    expect(healthProblemCount(undefined)).toBe(0)
    expect(
      healthProblemCount({ totals: { problems: 0, providers_degraded: 0 }, translation: { failures_7d: 0 } } as never),
    ).toBe(0)
  })
})
