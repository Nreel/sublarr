/**
 * Health page problem taxonomy — one badge per machine-readable problem.
 *
 * Keys are the codes the backend emits (`failure_kind`, provider
 * `status_reason`, translation `error_kind`/`last_error_kind`). Each carries a
 * short explanation and the settings route that most often fixes it, so a
 * badge answers "what broke" and "where do I go" without the reader guessing.
 * An unknown code renders its raw text under the generic badge rather than
 * nothing: a code added server-side must stay visible.
 */
import type { LibraryHealth } from '../api/system/healthLibrary';
import { AUTOMATION_SEARCH, GENERAL_PATHS, PROVIDERS_GLOBAL, SYSTEM_DIAGNOSTICS, SUBTITLES_FORMAT, SUBTITLES_LANGUAGES, SUBTITLES_SCORING, TRANSLATION_BACKENDS, TRANSLATION_COST_MEMORY, TRANSLATION_QUALITY } from './settingsRoutes';

export type ProblemTier = 'error' | 'warn';

export interface ProblemBadgeSpec {
  /** i18n key in the `health` namespace for the badge label. */
  labelKey: string;
  /** i18n key in the `health` namespace for the one-line explanation. */
  hintKey: string;
  /** Settings route (+ section anchor) that resolves the problem. */
  href: string;
  tier: ProblemTier;
}

const SPEC: Record<string, ProblemBadgeSpec> = {
  // Wanted-item failure kinds (backend services/wanted_search_outcome.py).
  no_result: {
    labelKey: 'badges.no_result.label',
    hintKey: 'badges.no_result.hint',
    href: AUTOMATION_SEARCH,
    tier: 'warn',
  },
  no_result_slow: {
    labelKey: 'badges.no_result_slow.label',
    hintKey: 'badges.no_result_slow.hint',
    href: AUTOMATION_SEARCH,
    tier: 'warn',
  },
  provider_error: {
    labelKey: 'badges.provider_error.label',
    hintKey: 'badges.provider_error.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'error',
  },
  file_missing: {
    labelKey: 'badges.file_missing.label',
    hintKey: 'badges.file_missing.hint',
    href: GENERAL_PATHS,
    tier: 'error',
  },
  translation_error: {
    labelKey: 'badges.translation_error.label',
    hintKey: 'badges.translation_error.hint',
    href: TRANSLATION_BACKENDS,
    tier: 'error',
  },
  unsourceable: {
    labelKey: 'badges.unsourceable.label',
    hintKey: 'badges.unsourceable.hint',
    href: AUTOMATION_SEARCH,
    tier: 'error',
  },
  failed: {
    labelKey: 'badges.failed.label',
    hintKey: 'badges.failed.hint',
    href: SYSTEM_DIAGNOSTICS,
    tier: 'error',
  },

  // Provider verdicts (backend/providers/manager_status_mixin.py + overview).
  auto_disabled: {
    labelKey: 'badges.auto_disabled.label',
    hintKey: 'badges.auto_disabled.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'error',
  },
  circuit_open: {
    labelKey: 'badges.circuit_open.label',
    hintKey: 'badges.circuit_open.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'error',
  },
  credentials_rejected: {
    labelKey: 'badges.credentials_rejected.label',
    hintKey: 'badges.credentials_rejected.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'error',
  },
  host_unreachable: {
    labelKey: 'badges.host_unreachable.label',
    hintKey: 'badges.host_unreachable.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'error',
  },
  consecutive_failures: {
    labelKey: 'badges.consecutive_failures.label',
    hintKey: 'badges.consecutive_failures.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'error',
  },
  no_results: {
    labelKey: 'badges.no_results.label',
    hintKey: 'badges.no_results.hint',
    href: SUBTITLES_SCORING,
    tier: 'warn',
  },
  no_credentials: {
    labelKey: 'badges.no_credentials.label',
    hintKey: 'badges.no_credentials.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'warn',
  },
  not_initialized: {
    labelKey: 'badges.not_initialized.label',
    hintKey: 'badges.not_initialized.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'error',
  },
  low_hit_rate: {
    labelKey: 'badges.low_hit_rate.label',
    hintKey: 'badges.low_hit_rate.hint',
    href: SUBTITLES_SCORING,
    tier: 'warn',
  },
  no_activity: {
    labelKey: 'badges.no_activity.label',
    hintKey: 'badges.no_activity.hint',
    href: PROVIDERS_GLOBAL,
    tier: 'warn',
  },

  // Translation backend call failures (health_overview._classify_backend_error).
  timeout: {
    labelKey: 'badges.timeout.label',
    hintKey: 'badges.timeout.hint',
    href: TRANSLATION_BACKENDS,
    tier: 'error',
  },
  line_mismatch: {
    labelKey: 'badges.line_mismatch.label',
    hintKey: 'badges.line_mismatch.hint',
    href: TRANSLATION_QUALITY,
    tier: 'error',
  },
  backend_auth: {
    labelKey: 'badges.backend_auth.label',
    hintKey: 'badges.backend_auth.hint',
    href: TRANSLATION_BACKENDS,
    tier: 'error',
  },
  backend_quota: {
    labelKey: 'badges.backend_quota.label',
    hintKey: 'badges.backend_quota.hint',
    href: TRANSLATION_COST_MEMORY,
    tier: 'warn',
  },
  backend_unreachable: {
    labelKey: 'badges.backend_unreachable.label',
    hintKey: 'badges.backend_unreachable.hint',
    href: TRANSLATION_BACKENDS,
    tier: 'error',
  },
  backend_error: {
    labelKey: 'badges.backend_error.label',
    hintKey: 'badges.backend_error.hint',
    href: TRANSLATION_BACKENDS,
    tier: 'error',
  },

  // Pipeline job failures (health_overview._classify_pipeline_error).
  source_missing: {
    labelKey: 'badges.source_missing.label',
    hintKey: 'badges.source_missing.hint',
    href: SUBTITLES_LANGUAGES,
    tier: 'error',
  },
  signs_only: {
    labelKey: 'badges.signs_only.label',
    hintKey: 'badges.signs_only.hint',
    href: SUBTITLES_LANGUAGES,
    tier: 'warn',
  },
  unsupported_format: {
    labelKey: 'badges.unsupported_format.label',
    hintKey: 'badges.unsupported_format.hint',
    href: SUBTITLES_FORMAT,
    tier: 'error',
  },
  outside_media: {
    labelKey: 'badges.outside_media.label',
    hintKey: 'badges.outside_media.hint',
    href: GENERAL_PATHS,
    tier: 'error',
  },
  job_error: {
    labelKey: 'badges.job_error.label',
    hintKey: 'badges.job_error.hint',
    href: SYSTEM_DIAGNOSTICS,
    tier: 'error',
  },

  unknown: {
    labelKey: 'badges.unknown.label',
    hintKey: 'badges.unknown.hint',
    href: SYSTEM_DIAGNOSTICS,
    tier: 'error',
  },
};

/** Badge for a problem code; `null`/unknown codes fall back to `unknown`. */
export function problemBadgeSpec(kind: string | null | undefined): ProblemBadgeSpec {
  return (kind && SPEC[kind]) || SPEC.unknown;
}

export const TIER_COLOR: Record<ProblemTier, string> = {
  error: 'var(--error)',
  warn: 'var(--warning)',
};

/** What the sidebar chip counts: stuck wanted items, degraded providers, and
 *  translation failures in the last 7 days. Zero means the page has nothing
 *  to show, so the chip drops out. */
export function healthProblemCount(health: LibraryHealth | undefined): number {
  if (!health) return 0;
  return (
    (health.totals?.problems ?? 0) +
    (health.totals?.providers_degraded ?? 0) +
    (health.translation?.failures_7d ?? 0)
  );
}
