"""POST /api/v1/tasks/wanted_scan/cancel + the ``cancellable`` flag in GET /tasks.

A scan stop is cooperative (``WantedScanner.cancel_scan``), so the answer is
202 "cancelling", not 200: the pass unwinds at its next item boundary and
stays resumable (the _resume/_pass_done bookkeeping is untouched).
"""

from unittest.mock import patch


class _FakeScanner:
    def __init__(self, scanning: bool):
        self.is_scanning = scanning
        self.is_searching = False
        self.cancel_scan_calls = 0

    def cancel_scan(self):
        self.cancel_scan_calls += 1


def test_scan_cancel_idle_409(client):
    fake = _FakeScanner(False)
    with patch("services.wanted_scanner.get_scanner", return_value=fake):
        resp = client.post("/api/v1/tasks/wanted_scan/cancel")
    assert resp.status_code == 409
    assert fake.cancel_scan_calls == 0


def test_scan_cancel_running_202(client):
    fake = _FakeScanner(True)
    with patch("services.wanted_scanner.get_scanner", return_value=fake):
        resp = client.post("/api/v1/tasks/wanted_scan/cancel")
    assert resp.status_code == 202
    assert resp.get_json()["status"] == "cancelling"
    assert fake.cancel_scan_calls == 1


def test_unknown_task_cancel_404(client):
    resp = client.post("/api/v1/tasks/nonsense/cancel")
    assert resp.status_code == 404


def test_tasks_listing_marks_wanted_scan_cancellable(client):
    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 200
    entry = next(t for t in resp.get_json()["tasks"] if t["name"] == "wanted_scan")
    assert entry["cancellable"] is True
