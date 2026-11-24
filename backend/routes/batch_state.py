"""Shared in-memory batch state for translate and wanted routes.

These module-level dicts are mutated by translate/wanted routes and read by
the system /stats and /tasks endpoints. Keeping them here avoids system.py
importing from translate.py and wanted.py.
"""

import threading


def serialize_batch_state(state: dict) -> dict:
    """JSON-safe copy of a batch state dict (the ``cancel_event`` is not serializable)."""
    return {k: v for k, v in state.items() if k != "cancel_event"}


def begin_run(state: dict) -> None:
    """Reset cancellation for a new run. Caller must hold the state's lock."""
    state["cancelled"] = False
    state["cancel_event"] = threading.Event()


def request_cancel(state: dict) -> bool:
    """Mark a run as cancelling. Caller must hold the state's lock."""
    if not state.get("running"):
        return False
    state["cancelled"] = True
    event = state.get("cancel_event")
    if event is not None:
        event.set()
    return True

# Translation stats state moved to services.translation_jobs (2026-07-02) so
# the job runner lives entirely in the services layer. Re-exported here for
# routes that still import it from routes.batch_state (same dict/lock objects).
from services.translation_jobs import _memory_stats, stats_lock  # noqa: F401

# --- Translation batch state ------------------------------------------------

batch_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "succeeded": 0,
    "failed": 0,
    "skipped": 0,
    "current_file": None,
    "errors": [],
    "cancelled": False,
    "cancel_event": threading.Event(),
}
batch_lock = threading.Lock()

# --- Retranslate batch state ------------------------------------------------
# /retranslate/batch had no running flag: two overlapping POSTs translated
# the same outdated jobs twice (double API spend, two writers stamping the
# same rows). Same guard shape as batch_state above.

retranslate_batch_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "succeeded": 0,
    "failed": 0,
    "current_file": None,
    "cancelled": False,
    "cancel_event": threading.Event(),
}
retranslate_lock = threading.Lock()

# --- Wanted batch-search state ----------------------------------------------

wanted_batch_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "found": 0,
    "failed": 0,
    "skipped": 0,
    "current_item": None,
    "cancelled": False,
    "cancel_event": threading.Event(),
}
wanted_batch_lock = threading.Lock()

# --- Wanted batch-extract state ---------------------------------------------

_batch_extract_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "succeeded": 0,
    "failed": 0,
    "skipped": 0,
    "current_item": None,
    "cancelled": False,
    "cancel_event": threading.Event(),
}
_batch_extract_lock = threading.Lock()

# --- Wanted batch-probe state -----------------------------------------------

_batch_probe_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "found": 0,
    "extracted": 0,
    "skipped": 0,
    "failed": 0,
    "current_item": None,
    "cancelled": False,
    "cancel_event": threading.Event(),
}
_batch_probe_lock = threading.Lock()
