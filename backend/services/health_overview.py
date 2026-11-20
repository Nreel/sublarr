"""Library health overview — the data behind GET /api/v1/health/library.

Aggregates three "where does it hurt" views from data that already exists:

  * ``series``   — which series/movies have missing subtitles, and how many
                   of their wanted items are stuck in a failure state.
  * ``problems`` — the concrete wanted items that failed or were classified
                   with a ``failure_kind`` (no_result, provider_error,
                   unsourceable, ...), i.e. episodes the pipeline could not
                   satisfy or match.
  * ``providers``— per-provider health: circuit-breaker state merged with
                   the hit/failure counters from provider_stats.
  * ``translation``— translation-pipeline health: per-backend failure counters
                     from translation_backend_stats plus the most recent failed
                     translate_batch calls from translation_events. Until this,
                     a translation error was only visible behind one episode's
                     History button; a dead backend showed nowhere.

Everything is read-only and bounded (top-N lists) so the endpoint stays
cheap enough for a dashboard poll.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError

from providers.manager_status_mixin import _classify_health

logger = logging.getLogger(__name__)

# Bounded list sizes — a dashboard needs the worst offenders, not everything.
MAX_SERIES_ROWS = 50
MAX_PROBLEM_ROWS = 100
MAX_TRANSLATION_ERROR_ROWS = 50

# Wanted statuses that mean "the user does not want this tracked".
_EXCLUDED_STATUSES = ("ignored",)

# translation_events statuses that mean the translation itself broke.
# "cancelled" is an operator action, not a failure.
_FAILED_TRANSLATION_STATUSES = ("error", "timeout")


def _is_problem_clause(wanted_model):
    """Filter: item is stuck — failed outright or classified with a failure kind."""
    return (wanted_model.status == "failed") | (wanted_model.failure_kind.isnot(None))


def get_library_health() -> dict:
    from db.models.circuit_breaker import CircuitBreakerState
    from db.models.core import WantedItem
    from db.models.providers import ProviderStats
    from db.models.translation import TranslationBackendStats, TranslationEvent
    from extensions import db

    session = db.session

    # ── series/movies with missing subtitles ────────────────────────────────
    problem_case = case((_is_problem_clause(WantedItem), 1), else_=0)
    series_rows = session.execute(
        select(
            WantedItem.title,
            WantedItem.item_type,
            func.count(WantedItem.id).label("missing"),
            func.sum(problem_case).label("problems"),
        )
        .where(WantedItem.status.notin_(_EXCLUDED_STATUSES))
        .group_by(WantedItem.title, WantedItem.item_type)
        .order_by(func.count(WantedItem.id).desc())
        .limit(MAX_SERIES_ROWS)
    ).all()
    series = [
        {
            "title": row[0] or "?",
            "item_type": row[1],
            "missing": int(row[2] or 0),
            "problems": int(row[3] or 0),
        }
        for row in series_rows
    ]

    # ── concrete problem items (failed / unmatched episodes) ────────────────
    problem_rows = (
        session.execute(
            select(WantedItem)
            .where(_is_problem_clause(WantedItem))
            .where(WantedItem.status.notin_(_EXCLUDED_STATUSES))
            .order_by(WantedItem.updated_at.desc())
            .limit(MAX_PROBLEM_ROWS)
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
    translation: dict = {"failures_7d": 0, "stuck_items": 0, "backends": [], "recent_errors": []}
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
                .limit(MAX_TRANSLATION_ERROR_ROWS)
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
                "error_msg": e.error_msg or "",
                "started_at": e.started_at.isoformat() if e.started_at else None,
            }
            for e in error_rows
        ]
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
            select(func.count(WantedItem.id)).where(WantedItem.failure_kind == "unsourceable")
        ).scalar_one()
        or 0
    )

    return {
        "totals": {
            "wanted": int(wanted_total),
            "problems": int(problems_total),
            "unmatched": int(unmatched_total),
            "series_affected": len(series),
            "providers_degraded": sum(1 for p in providers if p["degraded"]),
            # Reported apart from health on purpose: an install that has not
            # searched yet says nothing about whether its providers work.
            "providers_no_activity": sum(
                1 for p in providers if p["status_reason"] == "no_activity"
            ),
        },
        "series": series,
        "problems": problems,
        "providers": providers,
        "translation": translation,
    }
