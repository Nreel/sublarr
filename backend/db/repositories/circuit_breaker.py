"""Repository for CircuitBreakerState — persistence of breaker states."""

import logging
from datetime import UTC, datetime

from db.models.circuit_breaker import CircuitBreakerState
from extensions import db

logger = logging.getLogger(__name__)


class CircuitBreakerRepository:
    def save_state(
        self,
        name: str,
        state: str,
        failure_count: int,
        last_failure_epoch: float | None = None,
    ) -> None:
        """Upsert the persisted state for one breaker. Rolls back on error."""
        try:
            row = db.session.get(CircuitBreakerState, name)
            if row is None:
                row = CircuitBreakerState(name=name)
                db.session.add(row)
            row.state = state
            row.failure_count = failure_count
            row.last_failure_epoch = last_failure_epoch
            row.updated_at = datetime.now(UTC)
            db.session.commit()
        except Exception:
            logger.exception("Failed to persist circuit breaker state %s", name)
            db.session.rollback()
