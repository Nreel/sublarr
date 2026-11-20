/** Library health overview — GET /api/v1/health/library (Health page). */
import { api } from '../core'

export interface HealthSeriesRow {
  title: string
  item_type: string
  missing: number
  problems: number
}

export interface HealthProblemRow {
  id: number
  title: string
  season_episode: string
  item_type: string
  target_language: string
  status: string
  failure_kind: string | null
  error: string
  search_count: number
  updated_at: string | null
}

export interface HealthTranslationBackend {
  backend: string
  requests: number
  failed: number
  consecutive_failures: number
  last_error: string
  last_failure_at: string | null
  last_success_at: string | null
}

export interface HealthTranslationError {
  backend: string
  source_lang: string
  target_lang: string
  lines_count: number
  status: string
  error_type: string
  error_msg: string
  started_at: string | null
}

export interface HealthTranslation {
  /** Failed translate_batch calls (status error/timeout) in the last 7 days. */
  failures_7d: number
  /** Wanted items whose recorded failure_kind is translation_error. */
  stuck_items: number
  backends: HealthTranslationBackend[]
  recent_errors: HealthTranslationError[]
}

export interface HealthProviderRow {
  provider: string
  breaker_state: string
  breaker_failures: number
  searches: number
  hit_rate: number | null
  failed_downloads: number
  auto_disabled: boolean
  degraded: boolean
}

export interface LibraryHealth {
  totals: {
    wanted: number
    problems: number
    unmatched: number
    series_affected: number
    providers_degraded: number
    /** Providers nothing has asked yet — reported apart from health, because
     *  an install that has not searched says nothing about whether they work. */
    providers_no_activity: number
  }
  series: HealthSeriesRow[]
  problems: HealthProblemRow[]
  providers: HealthProviderRow[]
  translation: HealthTranslation
}

export async function getLibraryHealth(): Promise<LibraryHealth> {
  const { data } = await api.get('/health/library')
  return data
}
