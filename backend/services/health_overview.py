"""Library health overview — the data behind GET /api/v1/health/library.

Aggregates three "where does it hurt" views from data that already exists:

  * ``problems`` — the concrete wanted items carrying an error: failed outright,
                   classified with a ``failure_kind`` (no_result, provider_error,
                   unsourceable, ...), or holding a recorded error message /
                   error count. Per-title roll-ups live on /wanted, so this page
                   lists items rather than titles.
  * ``providers``— per-provider health: circuit-breaker state merged with
                   the hit/failure counters from provider_stats.
  * ``translation``— translation-pipeline health: per-backend failure counters
                     from translation_backend_stats, the most recent failed
                     translate_batch calls from translation_events, and failed
                     translation jobs from ``jobs``. Until this, a translation
                     error was only visible behind one episode's History
                     button; a dead backend showed nowhere.

Everything is read-only and complete (no top-N truncation): the frontend
renders in chunks so a large library stays cheap to paint, while the payload
never hides a problem the reader would otherwise miss. Polling stays cheap
because the endpoint is cached.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from providers.manager_status_mixin import _classify_health

logger = logging.getLogger(__name__)

# No row caps. The page exists to be trusted: a list truncated at 50 items
# hides the items that hurt most when there are 51, and the reader cannot
# tell "no more problems" from "not shown". The frontend renders in chunks
# (see ScrollList-style infinite scroll in HealthPage) instead of trimming
# the payload.

# Wanted statuses that mean "the user does not want this tracked".
_EXCLUDED_STATUSES = ("ignored",)

# translation_events statuses that mean the translation itself broke.
# "cancelled" is an operator action, not a failure.
_FAILED_TRANSLATION_STATUSES = ("error", "timeout")

# jobs.status that means the pipeline broke. "cancelled" is an operator action.
_FAILED_JOB_STATUS = "failed"


def _is_problem_clause(wanted_model):
    """Filter: item carries an error.

    Three signals, because the scheduler records failures in three places:
    ``status == "failed"`` (set by status changes, e.g. the bulk status API),
    ``failure_kind`` (set by every scheduler outcome), and the error side
    (``error_count`` / ``last_error_at`` / a non-empty ``error`` note) which
    can outlive a kind — an item put back to ``wanted`` with an error message
    keeps the note while losing its kind, and a row that only ever got a
    provider fault without a kind would otherwise show nowhere.
    """
    return (
        (wanted_model.status == "failed")
        | (wanted_model.failure_kind.isnot(None))
        | (wanted_model.error_count > 0)
        | (wanted_model.last_error_at.isnot(None))
        | (wanted_model.error.isnot(None) & (wanted_model.error != ""))
    )


# Job failures that broke before a backend was ever reached. The Health page
# badges these, so each needs a machine-readable kind rather than a free-text
# error string the reader has to parse.
_PIPELINE_ERROR_KINDS = (
    ("no source subtitle found", "source_missing"),
    ("looks like signs only", "signs_only"),
    ("lies outside its folder or the media folder", "outside_media"),
    ("unsupported format", "unsupported_format"),
    ("unsupported subtitle format", "unsupported_format"),
    ("unsupported codec", "unsupported_format"),
    ("unsupported subtitle codec", "unsupported_format"),
)

# Backend call failures. ``error_type`` is an exception class name and
# ``error_msg`` free text; both are searched, newest rule first.
_BACKEND_ERROR_KINDS = (
    ("timeout", "timeout"),
    ("timed out", "timeout"),
    ("linecountmismatch", "line_mismatch"),
    ("unauthorized", "backend_auth"),
    ("forbidden", "backend_auth"),
    ("authentication", "backend_auth"),
    ("api key", "backend_auth"),
    ("apikey", "backend_auth"),
    ("invalid key", "backend_auth"),
    ("rate limit", "backend_quota"),
    ("too many requests", "backend_quota"),
    ("429", "backend_quota"),
    ("quota", "backend_quota"),
    ("budget", "backend_quota"),
    ("connection refused", "backend_unreachable"),
    ("connection error", "backend_unreachable"),
    ("connectionreset", "backend_unreachable"),
    ("unreachable", "backend_unreachable"),
    ("networkerror", "backend_unreachable"),
    ("connectionerror", "backend_unreachable"),
    ("oserror", "backend_unreachable"),
)


def _activity_error(details_json: str | None) -> str:
    """Error message stored in an activity_log row's ``details_json``."""
    if not details_json:
        return ""
    try:
        details = json.loads(details_json)
    except (TypeError, ValueError):
        return ""
    if isinstance(details, dict):
        return str(details.get("error", ""))
    return ""


def _classify_pipeline_error(error: str) -> str:
    """Kind of a failed translation job that never reached a backend."""
    lowered = (error or "").lower()
    for needle, kind in _PIPELINE_ERROR_KINDS:
        if needle in lowered:
            return kind
    return "job_error"


def _classify_backend_error(status: str, error_type: str, error_msg: str) -> str:
    """Kind of a failed backend call: outage, auth, quota, timeout, or bad output."""
    if status == "timeout":
        return "timeout"
    blob = f"{error_type} {error_msg}".lower()
    for needle, kind in _BACKEND_ERROR_KINDS:
        if needle in blob:
            return kind
    return "backend_error"


def get_library_health() -> dict:
    from db.models.activity import ActivityLog
    from db.models.circuit_breaker import CircuitBreakerState
    from db.models.core import Job, SyncJobRun, WantedItem
    from db.models.hooks import HookConfig, HookLog, WebhookConfig
    from db.models.notifications import NotificationHistory
    from db.models.providers import ProviderStats
    from db.models.scheduler import JobRun
    from db.models.translation import TranslationBackendStats, TranslationEvent, WhisperJob
    from extensions import db

    session = db.session

    # ── concrete problem items (failed / unmatched episodes) ────────────────
    problem_rows = (
        session.execute(
            select(WantedItem)
            .where(_is_problem_clause(WantedItem))
            .where(WantedItem.status.notin_(_EXCLUDED_STATUSES))
            .order_by(WantedItem.updated_at.desc())
        )
        .scalars()
        .all()
    )
    problems = [
        {
            "id": item.id,
            "title": item.title,
            "season_episode": item.season_episode or "",
            "item_type": item.item_type,
            "target_language": item.target_language or "",
            "status": item.status,
            "failure_kind": item.failure_kind,
            "error": item.error or "",
            "search_count": item.search_count or 0,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in problem_rows
    ]

    # ── provider health: circuit breaker ⋈ provider_stats ───────────────────
    # circuit_breaker_states is absent on installs whose schema drifted from
    # their alembic_version (prod and RC are both stamped downstream of the
    # migration that creates it, yet lack the table). A health overview must
    # never be the thing that 500s, so treat the breaker join as optional and
    # fall back to "no breaker known" — every consumer already defaults to
    # "closed" for a provider without a breaker row.
    try:
        breakers = {
            row.name: row for row in session.execute(select(CircuitBreakerState)).scalars().all()
        }
    except SQLAlchemyError:
        session.rollback()
        logger.warning(
            "circuit_breaker_states unavailable — reporting provider health without breaker state",
            exc_info=True,
        )
        breakers = {}
    stats_rows = session.execute(select(ProviderStats)).scalars().all()
    provider_names = sorted(set(breakers) | {r.provider_name for r in stats_rows})
    providers = []
    for name in provider_names:
        breaker = breakers.get(name)
        stats = next((r for r in stats_rows if r.provider_name == name), None)
        searches = (stats.total_searches or 0) if stats else 0
        hits = (stats.successful_searches or 0) if stats else 0
        breaker_state = (breaker.state if breaker else "closed") or "closed"
        auto_disabled = bool(stats.auto_disabled) if stats else False
        hit_rate = round(hits / searches, 3) if searches else None
        # One verdict, not a third one. This page used to decide "degraded"
        # on its own — breaker open, auto-disabled, or a poor hit rate over
        # 10+ searches — while /api/v1/providers asked the classifier behind
        # it. The two disagreed in public: six providers unhealthy there and
        # "PROVIDERS DEGRADED 0" here, both correct under their own rule
        # (forgejo #17). The classifier needs nothing this function has not
        # already loaded, so both surfaces can answer from it.
        if searches == 0 and not auto_disabled and breaker_state == "closed":
            # Never asked anything. Not broken — but not evidence of health
            # either, and reporting it as healthy is what made "no provider
            # activity recorded yet" sit next to a reassuring zero.
            healthy, status_reason = True, "no_activity"
        else:
            healthy, _message, status_reason = _classify_health(
                auto_disabled=auto_disabled,
                cb_state=breaker_state,
                consecutive_failures=int(stats.consecutive_failures or 0) if stats else 0,
                total_searches=int(searches),
                results=int(hits),
                downloads=int(stats.successful_downloads or 0) if stats else 0,
                last_failure_kind=(stats.last_failure_kind if stats else None),
            )
            # The classifier asks "is it broken". This page also wants "is it
            # worth its slot", and its answer is narrower than the delivers-
            # nothing verdict: a provider that hits once in fifty searches is
            # not dead by that measure but is not earning anything either.
            # Kept as its own reason rather than as a second definition of
            # health, so the two surfaces complement instead of contradicting.
            if healthy and searches >= 10 and hit_rate is not None and hit_rate < 0.05:
                healthy, status_reason = False, "low_hit_rate"

        providers.append(
            {
                "provider": name,
                "breaker_state": breaker_state,
                "breaker_failures": int(breaker.failure_count or 0) if breaker else 0,
                "searches": int(searches),
                "hit_rate": hit_rate,
                "failed_downloads": int(stats.failed_downloads or 0) if stats else 0,
                "auto_disabled": auto_disabled,
                "degraded": not healthy,
                "status_reason": status_reason,
            }
        )
    providers.sort(key=lambda p: (not p["degraded"], p["provider"]))

    # ── translation health ──────────────────────────────────────────────────
    # Same defensive contract as the breaker join above: an install whose
    # schema drifted from its alembic_version may lack the translation tables,
    # and a health overview must never be the thing that 500s.
    translation: dict = {
        "failures_7d": 0,
        "stuck_items": 0,
        "backends": [],
        "recent_errors": [],
        "pipeline_errors": [],
    }
    try:
        window_start = datetime.now(UTC) - timedelta(days=7)
        translation["failures_7d"] = int(
            session.execute(
                select(func.count(TranslationEvent.id))
                .where(TranslationEvent.status.in_(_FAILED_TRANSLATION_STATUSES))
                .where(TranslationEvent.started_at >= window_start)
            ).scalar_one()
            or 0
        )
        error_rows = (
            session.execute(
                select(TranslationEvent)
                .where(TranslationEvent.status.in_(_FAILED_TRANSLATION_STATUSES))
                .order_by(TranslationEvent.started_at.desc())
            )
            .scalars()
            .all()
        )
        translation["recent_errors"] = [
            {
                "backend": e.backend,
                "source_lang": e.source_lang,
                "target_lang": e.target_lang,
                "lines_count": int(e.lines_count or 0),
                "status": e.status,
                "error_type": e.error_type or "",
                "error_kind": _classify_backend_error(
                    e.status or "", e.error_type or "", e.error_msg or ""
                ),
                "error_msg": e.error_msg or "",
                "started_at": e.started_at.isoformat() if e.started_at else None,
            }
            for e in error_rows
        ]
        # Pipeline failures: translation jobs that broke without reaching a
        # backend — no source subtitle, nothing to translate, container/format
        # errors. Those only ever surfaced behind an episode's History button:
        # they write no translation_events row and no backend stat, so this
        # page said "No translation errors" while the pipeline was failing.
        # A backend exception also fails its job, so a job already accounted
        # for by an error/timeout event is excluded here — one incident must
        # not be counted, or listed, twice.
        backend_failed_jobs = (
            select(TranslationEvent.job_id)
            .where(TranslationEvent.status.in_(_FAILED_TRANSLATION_STATUSES))
            .where(TranslationEvent.job_id.isnot(None))
            .where(TranslationEvent.job_id != "")
        )
        pipeline_rows = (
            session.execute(
                select(Job)
                .where(Job.status == _FAILED_JOB_STATUS)
                .where(Job.id.notin_(backend_failed_jobs))
                .order_by(Job.created_at.desc())
            )
            .scalars()
            .all()
        )
        translation["pipeline_errors"] = [
            {
                "job_id": j.id,
                "file_path": j.file_path,
                "source_format": j.source_format or "",
                "error": j.error or "",
                "error_kind": _classify_pipeline_error(j.error or ""),
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in pipeline_rows
        ]
        # Same dedup as the list above, windowed like the backend count.
        translation["failures_7d"] += int(
            session.execute(
                select(func.count(Job.id))
                .where(Job.status == _FAILED_JOB_STATUS)
                .where(Job.created_at >= window_start)
                .where(Job.id.notin_(backend_failed_jobs))
            ).scalar_one()
            or 0
        )
        backend_rows = session.execute(select(TranslationBackendStats)).scalars().all()
        # Failing backends first — the page exists to show where it hurts.
        translation["backends"] = sorted(
            [
                {
                    "backend": r.backend_name,
                    "requests": int(r.total_requests or 0),
                    "failed": int(r.failed_translations or 0),
                    "consecutive_failures": int(r.consecutive_failures or 0),
                    "last_error": r.last_error or "",
                    # The badge behind "Last error" needs a kind, not the raw
                    # string: "Connection refused" and "API key rejected" are
                    # different fixes on the same settings page.
                    "last_error_kind": _classify_backend_error("error", "", r.last_error or "")
                    if (r.failed_translations or r.consecutive_failures)
                    else "",
                    "last_failure_at": r.last_failure_at.isoformat() if r.last_failure_at else None,
                    "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
                }
                for r in backend_rows
            ],
            key=lambda b: (b["failed"] == 0 and b["consecutive_failures"] == 0, b["backend"]),
        )
    except SQLAlchemyError:
        session.rollback()
        logger.warning(
            "translation tables unavailable — reporting health without translation state",
            exc_info=True,
        )

    # Wanted items whose recorded failure was a translation error. They return
    # to the wanted pool with escalating retry delay; separating them from
    # provider-side problems answers "found it but could not translate it".
    translation["stuck_items"] = int(
        session.execute(
            select(func.count(WantedItem.id))
            .where(WantedItem.failure_kind == "translation_error")
            .where(WantedItem.status.notin_(_EXCLUDED_STATUSES))
        ).scalar_one()
        or 0
    )

    # ── operational error sections ──────────────────────────────────────────
    # Failures from subsystems that write no wanted-item, provider stat or
    # translation event: scheduler ticks, whisper jobs, sync engines, the
    # unified activity log, hooks, and notification delivery (which carries
    # database-backup failures). Each is a capped, newest-first list in a
    # 7-day window — these are diagnostics, not per-item problems, so a cap
    # costs nothing the page would otherwise miss (a flood past 50 rows is
    # evidence enough). Each section degrades independently like the
    # breaker/translation joins above: an install whose schema drifted must
    # never 500 here.
    window_start = datetime.now(UTC) - timedelta(days=7)
    _ERROR_CAP = 50

    scheduler_errors: list[dict] = []
    try:
        run_rows = (
            session.execute(
                select(JobRun)
                .where(
                    JobRun.status.in_(
                        ("error", "timeout", "timeout_not_started", "timeout_abandoned", "missed")
                    )
                )
                .where(JobRun.started_at >= window_start)
                .order_by(JobRun.started_at.desc(), JobRun.id.desc())
                .limit(_ERROR_CAP)
            )
            .scalars()
            .all()
        )
        scheduler_errors = [
            {
                "job_id": r.job_id,
                "status": r.status,
                "error_type": r.error_type or "",
                "error_msg": r.error_msg or "",
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "triggered_by": r.triggered_by or "schedule",
            }
            for r in run_rows
        ]
    except SQLAlchemyError:
        session.rollback()
        logger.warning(
            "scheduler_job_runs unavailable — reporting without scheduler errors", exc_info=True
        )

    whisper_errors: list[dict] = []
    try:
        w_rows = (
            session.execute(
                select(WhisperJob)
                .where(WhisperJob.status.in_(("failed", "cancelled")))
                .where(WhisperJob.created_at >= window_start)
                .order_by(WhisperJob.created_at.desc(), WhisperJob.id.desc())
                .limit(_ERROR_CAP)
            )
            .scalars()
            .all()
        )
        whisper_errors = [
            {
                "job_id": j.id,
                "file_path": j.file_path,
                "backend_name": j.backend_name or "",
                "status": j.status,
                "error": j.error or "",
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in w_rows
        ]
    except SQLAlchemyError:
        session.rollback()
        logger.warning("whisper_jobs unavailable — reporting without whisper errors", exc_info=True)

    sync_errors: list[dict] = []
    try:
        s_rows = (
            session.execute(
                select(SyncJobRun)
                .where(SyncJobRun.status.in_(("failed", "error")))
                .where(SyncJobRun.created_at >= window_start)
                .order_by(SyncJobRun.created_at.desc(), SyncJobRun.id.desc())
                .limit(_ERROR_CAP)
            )
            .scalars()
            .all()
        )
        sync_errors = [
            {
                "job_id": r.engine,
                "file_path": r.video_path or r.subtitle_path or "",
                "status": r.status,
                "error": r.reason or "",
                "started_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in s_rows
        ]
    except SQLAlchemyError:
        session.rollback()
        logger.warning("sync_job_runs unavailable — reporting without sync errors", exc_info=True)

    ops_errors: list[dict] = []
    try:
        a_rows = (
            session.execute(
                select(ActivityLog)
                .where(ActivityLog.status == "failed")
                .where(ActivityLog.created_at >= window_start)
                .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
                .limit(_ERROR_CAP)
            )
            .scalars()
            .all()
        )
        ops_errors = [
            {
                "event_type": r.event_type,
                "file_path": r.file_path or "",
                "error": _activity_error(r.details_json),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in a_rows
        ]
    except SQLAlchemyError:
        session.rollback()
        logger.warning("activity_log unavailable — reporting without ops errors", exc_info=True)

    hook_errors: list[dict] = []
    try:
        hook_names = {h.id: h.name for h in session.execute(select(HookConfig)).scalars().all()}
        webhook_names = {
            w.id: w.name for w in session.execute(select(WebhookConfig)).scalars().all()
        }
        h_rows = (
            session.execute(
                select(HookLog)
                .where(HookLog.success == 0)
                .where(HookLog.triggered_at >= window_start)
                .order_by(HookLog.triggered_at.desc(), HookLog.id.desc())
                .limit(_ERROR_CAP)
            )
            .scalars()
            .all()
        )
        hook_errors = [
            {
                "hook": (
                    hook_names.get(r.hook_id) or webhook_names.get(r.webhook_id) or r.event_name
                ),
                "error": r.error or r.stderr or "",
                "created_at": r.triggered_at.isoformat() if r.triggered_at else None,
            }
            for r in h_rows
        ]
    except SQLAlchemyError:
        session.rollback()
        logger.warning("hook_log unavailable — reporting without hook errors", exc_info=True)

    backup_errors: list[dict] = []
    try:
        # notification_history carries both backup-failure alerts and failed
        # deliveries of any notification — both are "we tried to tell you and
        # it broke", which /health must show.
        n_rows = (
            session.execute(
                select(NotificationHistory)
                .where(NotificationHistory.status == "failed")
                .where(NotificationHistory.sent_at >= window_start)
                .order_by(NotificationHistory.sent_at.desc(), NotificationHistory.id.desc())
                .limit(_ERROR_CAP)
            )
            .scalars()
            .all()
        )
        backup_errors = [
            {
                "event_type": r.event_type,
                "error": r.error or r.title or "",
                "created_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in n_rows
        ]
    except SQLAlchemyError:
        session.rollback()
        logger.warning(
            "notification_history unavailable — reporting without backup/notification errors",
            exc_info=True,
        )

    # ── totals ──────────────────────────────────────────────────────────────
    wanted_total = (
        session.execute(
            select(func.count(WantedItem.id)).where(WantedItem.status.notin_(_EXCLUDED_STATUSES))
        ).scalar_one()
        or 0
    )
    problems_total = (
        session.execute(
            select(func.count(WantedItem.id))
            .where(_is_problem_clause(WantedItem))
            .where(WantedItem.status.notin_(_EXCLUDED_STATUSES))
        ).scalar_one()
        or 0
    )
    unmatched_total = (
        session.execute(
            select(func.count(WantedItem.id))
            .where(WantedItem.failure_kind == "unsourceable")
            # Same exclusion as the list below: an ignored item is not a
            # problem the page can show, so the tile must not count it.
            .where(WantedItem.status.notin_(_EXCLUDED_STATUSES))
        ).scalar_one()
        or 0
    )

    return {
        "totals": {
            "wanted": int(wanted_total),
            "problems": int(problems_total),
            "unmatched": int(unmatched_total),
            "providers_degraded": sum(1 for p in providers if p["degraded"]),
            # Reported apart from health on purpose: an install that has not
            # searched yet says nothing about whether its providers work.
            "providers_no_activity": sum(
                1 for p in providers if p["status_reason"] == "no_activity"
            ),
        },
        "problems": problems,
        "providers": providers,
        "translation": translation,
        "scheduler_errors": scheduler_errors,
        "whisper_errors": whisper_errors,
        "sync_errors": sync_errors,
        "ops_errors": ops_errors,
        "hook_errors": hook_errors,
        "backup_errors": backup_errors,
    }
