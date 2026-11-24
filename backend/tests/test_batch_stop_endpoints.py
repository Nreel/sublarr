"""Stop endpoints for the in-flight batch runs.

Semantics shared by all five batches: no run in flight -> 409; a run in
flight -> the run's cancel_event is set, ``cancelled`` becomes true, and the
endpoint answers 202 {"status": "cancelling"}. The worker loops notice the
event between items; this test only drives the endpoint against fake state.
"""

import pytest

from routes.batch_state import (
    _batch_extract_lock,
    _batch_extract_state,
    _batch_probe_lock,
    _batch_probe_state,
    batch_lock,
    batch_state,
    begin_run,
    retranslate_batch_state,
    retranslate_lock,
    wanted_batch_lock,
    wanted_batch_state,
)

BATCHES = [
    ("/api/v1/wanted/batch/cancel", wanted_batch_state, wanted_batch_lock),
    ("/api/v1/wanted/batch-probe/cancel", _batch_probe_state, _batch_probe_lock),
    ("/api/v1/wanted/batch-extract/cancel", _batch_extract_state, _batch_extract_lock),
    ("/api/v1/batch/cancel", batch_state, batch_lock),
    ("/api/v1/retranslate/batch/cancel", retranslate_batch_state, retranslate_lock),
]


@pytest.mark.parametrize("path, state, lock", BATCHES)
def test_cancel_with_no_run_is_409(client, path, state, lock):
    with lock:
        state["running"] = False
        state["cancelled"] = False
    resp = client.post(path)
    assert resp.status_code == 409


@pytest.mark.parametrize("path, state, lock", BATCHES)
def test_cancel_running_run_sets_event(client, path, state, lock):
    with lock:
        state["running"] = True
        begin_run(state)  # fresh event per run
        event = state["cancel_event"]
    try:
        resp = client.post(path)
        assert resp.status_code == 202
        assert resp.get_json()["status"] == "cancelling"
        assert event.is_set()
        assert state["cancelled"] is True
    finally:
        with lock:
            state["running"] = False
            state["cancelled"] = False


@pytest.mark.parametrize("path, state, lock", BATCHES)
def test_begin_run_stamps_started_at(client, path, state, lock):
    """Every batch dict carries a UTC ISO started_at, passed through /status serialization."""
    from datetime import UTC, datetime

    from routes.batch_state import serialize_batch_state

    with lock:
        state["running"] = True
        begin_run(state)
        stamp = state["started_at"]
    try:
        assert stamp is not None
        assert datetime.fromisoformat(stamp).tzinfo is not None
        serialized = serialize_batch_state(state)
        assert serialized["started_at"] == stamp
        assert "cancel_event" not in serialized
    finally:
        with lock:
            state["running"] = False
            state["cancelled"] = False
            state["started_at"] = None
