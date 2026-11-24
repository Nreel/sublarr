/** Library health overview — GET /api/v1/health/library (Health page). */
import { api } from '../core';

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

/** Scheduler tick failures (scheduler_job_runs): error / timeout variants / missed. */
export interface HealthSchedulerError {
  job_id: string;
  status: string;
  error_type: string;
  error_msg: string;
  started_at: string | null;
  triggered_by: string;
}

/** Failed/cancelled whisper transcriptions (whisper_jobs). */
export interface HealthWhisperError {
  job_id: string;
  file_path: string;
  backend_name: string;
  status: string;
  error: string;
  completed_at: string | null;
}

/** Video-sync engine failures (sync_job_runs); `job_id` carries the engine name. */
export interface HealthSyncError {
  job_id: string;
  file_path: string;
  status: string;
  error: string;
  started_at: string | null;
}

/** Failed operations recorded in the activity log (scan/extract/remux/sync/… failures). */
export interface HealthOpsError {
  event_type: string;
  file_path: string;
  error: string;
  created_at: string | null;
}

/** Hook/webhook execution failures (hook_log). */
export interface HealthHookError {
  hook: string;
  error: string;
  created_at: string | null;
}

/** Failed backup alerts and failed notification deliveries (notification_history). */
export interface HealthBackupError {
  event_type: string;
  error: string;
  created_at: string | null;
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
    providers_degraded: number;
    /** Providers nothing has asked yet — reported apart from health, because
     *  an install that has not searched says nothing about whether they work. */
    providers_no_activity: number;
  };
  /** Wanted items carrying an error, newest first; complete, painted in chunks. */
  problems: HealthProblemRow[];
  providers: HealthProviderRow[];
  translation: HealthTranslation;
  /** Scheduler tick failures in the last 7 days, newest first (≤50). */
  scheduler_errors?: HealthSchedulerError[];
  /** Whisper transcription failures in the last 7 days, newest first (≤50). */
  whisper_errors?: HealthWhisperError[];
  /** Video-sync engine failures in the last 7 days, newest first (≤50). */
  sync_errors?: HealthSyncError[];
  /** Failed operations in the activity log, last 7 days, newest first (≤50). */
  ops_errors?: HealthOpsError[];
  /** Hook failures in the last 7 days, newest first (≤50). */
  hook_errors?: HealthHookError[];
  /** Backup/notification failures in the last 7 days, newest first (≤50). */
  backup_errors?: HealthBackupError[];
}

export async function getLibraryHealth(): Promise<LibraryHealth> {
  const { data } = await api.get('/health/library');
  return data;
}
