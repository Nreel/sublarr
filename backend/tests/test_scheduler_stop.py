"""POST /api/v1/scheduler/jobs/<id>/stop — abort the in-flight run only.

The route must wire ``services.scheduler.cancellation.request_stop`` and must
NOT pause the job: pausing would take the schedule away, and auto-triggered
jobs have to keep firing after a stop.
"""

from unittest.mock import patch

import routes.system.scheduler as sched


class _FakeScheduler:
    """Enough surface for the stop route; any pause/resume call is a failure."""

    _registered_ids = {"wanted_scan"}

    def pause_job(self, job_id):
        raise AssertionError(f"stop must not pause job {job_id!r}")

    def resume_job(self, job_id):
        raise AssertionError(f"stop must not resume job {job_id!r}")


def _post_stop(client, job_id="wanted_scan"):
    return client.post(f"/api/v1/scheduler/jobs/{job_id}/stop")


def test_stop_unknown_job_404(client):
    with patch.object(sched, "_get_scheduler", return_value=_FakeScheduler()):
        resp = _post_stop(client, "no-such-job")
    assert resp.status_code == 404


def test_stop_without_in_flight_run_409(client):
    with (
        patch.object(sched, "_get_scheduler", return_value=_FakeScheduler()),
        patch("services.scheduler.cancellation.request_stop", return_value=False) as req_stop,
    ):
        resp = _post_stop(client)
    assert resp.status_code == 409
    req_stop.assert_called_once_with("wanted_scan", reason="stopped by user")


def test_stop_in_flight_run_202_and_never_pauses(client):
    with (
        patch.object(sched, "_get_scheduler", return_value=_FakeScheduler()),
        patch("services.scheduler.cancellation.request_stop", return_value=True) as req_stop,
        patch("routes.system.scheduler._audit_log") as audit,
    ):
        resp = _post_stop(client)
    assert resp.status_code == 202
    assert resp.get_json() == {"status": "cancelling"}
    req_stop.assert_called_once_with("wanted_scan", reason="stopped by user")
    audit.assert_called_once_with("wanted_scan", "stop")
