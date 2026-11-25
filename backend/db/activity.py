"""Unified activity log DB operations — delegates to ActivityLogRepository."""

import logging
import threading
import time

from db.repositories.activity import ActivityLogRepository

logger = logging.getLogger(__name__)

# Per-row throttle for ``activity_progress`` socketio emits (worker threads
# share this map; the DB write itself is unthrottled — only emits are limited).
_emit_lock = threading.Lock()
_last_emit: dict[int, float] = {}

_repo: ActivityLogRepository | None = None


def _get_repo() -> ActivityLogRepository:
    global _repo
    if _repo is None:
        _repo = ActivityLogRepository()
    return _repo


def log_activity(
    event_type: str,
    *,
    file_path: str | None = None,
    status: str = "success",
    details: dict | None = None,
) -> int | None:
    """Log an activity event. Safe to call anywhere — never raises.

    Returns the new row's id (or ``None`` on failure).
    """
    return _get_repo().log_event(event_type, file_path=file_path, status=status, details=details)


def update_activity_status(
    row_id: int | None,
    status: str,
    details: dict | None = None,
) -> None:
    """Move a logged activity row to a new status. Safe to call anywhere — never raises."""
    _get_repo().update_activity_status(row_id, status, details=details)


def update_activity_progress(
    row_id: int | None,
    *,
    done: int,
    total: int,
    current: str,
    phase: str,
    event_type: str,
    socketio=None,
    min_emit_interval: float = 2.0,
) -> None:
    """Write live progress into a ``running`` activity row's details.

    Sets ``details["progress"] = {"done", "total", "current", "phase"}``
    without terminalizing the row (status stays ``running``); other details
    keys are preserved by the repository's merge. Safe to call anywhere —
    never raises.

    When ``socketio`` is given, emits ``activity_progress``
    ``{"id": row_id, "type": event_type}`` so the frontend can invalidate
    the activity query; emits are throttled to at most one per
    ``min_emit_interval`` seconds per row.
    """
    if row_id is None:
        return
    update_activity_status(
        row_id,
        "running",
        details={"progress": {"done": done, "total": total, "current": current, "phase": phase}},
    )
    if socketio is None:
        return
    now = time.monotonic()
    with _emit_lock:
        last = _last_emit.get(row_id)
        if last is not None and now - last < min_emit_interval:
            return
        _last_emit[row_id] = now
    try:
        socketio.emit("activity_progress", {"id": row_id, "type": event_type})
    except Exception:
        logger.exception("Failed to emit activity_progress for row %s", row_id)


def get_activity(
    page: int = 1,
    per_page: int = 50,
    event_type: str | None = None,
) -> dict:
    """Return paginated activity log entries."""
    return _get_repo().get_activity(page=page, per_page=per_page, event_type=event_type)
