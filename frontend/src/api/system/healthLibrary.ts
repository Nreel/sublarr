/** Library health overview — GET /api/v1/health/library (Health page). */
import { api } from '../core';

export interface HealthSeriesRow {
  title: string;
  item_type: string;
  missing: number;
  problems: number;
  /** Per failure kind behind `problems` (kind -> count); `failed` holds rows
   *  with no recorded kind. Sorted by nothing server-side — sort by count. */
  problem_kinds: Record<string, number>;
}

export interface HealthProblemRow {
  id: number;
  title: string;
  season_episode: string;
  item_type: string;
  target_language: string;
  status: string;
  failure_kind: string | null;
  error: string;
  search_count: number;
  updated_at: string | null;
}

export interface HealthTranslationBackend {
  backend: string;
  requests: number;
  failed: number;
  consecutive_failures: number;
  last_error: string;
  /** Classified cause of `last_error`; empty when the backend is healthy. */
  last_error_kind: string;
  last_failure_at: string | null;
  last_success_at: string | null;
}

export interface HealthTranslationError {
  backend: string;
  source_lang: string;
  target_lang: string;
  lines_count: number;
  status: string;
  error_type: string;
  /** Classified cause (timeout / backend_auth / backend_unreachable / …). */
  error_kind: string;
  error_msg: string;
  started_at: string | null;
}

export interface HealthPipelineError {
  job_id: string;
  file_path: string;
  source_format: string;
  error: string;
  /** Classified cause (source_missing / signs_only / unsupported_format / …). */
  error_kind: string;
  created_at: string | null;
  completed_at: string | null;
}

export interface HealthTranslation {
  /** Failed translations in the last 7 days: backend call errors (status
   *  error/timeout) plus pipeline failures — jobs that broke before reaching
   *  a backend. A job whose failure already has a backend event is counted
   *  once, as that event. */
  failures_7d: number;
  /** Wanted items whose recorded failure_kind is translation_error. */
  stuck_items: number;
  backends: HealthTranslationBackend[];
  recent_errors: HealthTranslationError[];
  /** Failed translation jobs with no backend event — no source subtitle,
   *  nothing to translate, format errors. */
  pipeline_errors: HealthPipelineError[];
}

export interface HealthProviderRow {
  provider: string;
  breaker_state: string;
  breaker_failures: number;
  searches: number;
  hit_rate: number | null;
  failed_downloads: number;
  auto_disabled: boolean;
  degraded: boolean;
  /** Machine-readable verdict behind `degraded` (ok / no_activity /
   *  low_hit_rate / circuit_open / …) — the badge keys off this, not the state. */
  status_reason: string;
}

export interface LibraryHealth {
  totals: {
    wanted: number;
    problems: number;
    unmatched: number;
    series_affected: number;
    providers_degraded: number;
    /** Providers nothing has asked yet — reported apart from health, because
     *  an install that has not searched says nothing about whether they work. */
    providers_no_activity: number;
  };
  series: HealthSeriesRow[];
  problems: HealthProblemRow[];
  providers: HealthProviderRow[];
  translation: HealthTranslation;
}

export async function getLibraryHealth(): Promise<LibraryHealth> {
  const { data } = await api.get('/health/library');
  return data;
}
