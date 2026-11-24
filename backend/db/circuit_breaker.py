"""Circuit breaker state persistence — delegates to CircuitBreakerRepository."""

import logging

from db.repositories.circuit_breaker import CircuitBreakerRepository

logger = logging.getLogger(__name__)

_repo: CircuitBreakerRepository | None = None


def _get_repo() -> CircuitBreakerRepository:
    global _repo
    if _repo is None:
        _repo = CircuitBreakerRepository()
    return _repo


def persist_breaker_state(
    name: str,
    state: str,
    failure_count: int,
    last_failure_time: float | None = None,
) -> None:
    """Write a breaker's state to ``circuit_breaker_states``. Never raises.

    Matches what :func:`services.health_overview.get_library_health` reads.
    Used as the ``persist_fn`` callback of provider CircuitBreakers; skipped
    outside a Flask app context, where the session is unavailable.
    """
    try:
        from flask import has_app_context

        if not has_app_context():
            return
    except Exception:
        return
    _get_repo().save_state(name, str(state), failure_count, last_failure_time)
