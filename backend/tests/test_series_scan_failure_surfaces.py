"""A failed series re-scan must error *and* show up in /health "Failed & unmatched items".

Two bugs from 2026-11-23, both on /library/series/<id>:

1. ``POST /standalone/series/<id>/scan`` looked the request id up in
   ``standalone_series`` raw. Page ids are signed (negative = standalone row,
   positive = Sonarr id), so a Sonarr series 404'd and a standalone series 404'd
   too (its row is ``-id``) — every "Re-scan Series" click errored.
2. Whatever the scan reported as an error came back as HTTP 200 (the scanner
   swallows failures into a summary dict), and nothing wrote an error onto the
   series' items, so the Health page stayed empty while the operator's button
   had just failed.
"""

import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SONARR_ID = 7


def _seed_items(app):
    """Open + settled rows for Sonarr series 7, plus another series' row."""
    from db.models.core import WantedItem
    from extensions import db

    with app.app_context():
        now = datetime.now(UTC)
        rows = [
            WantedItem(
                item_type="episode",
                title="Judas Erased - 01",
                sonarr_series_id=SONARR_ID,
                season_episode="S01E01",
                file_path="/library/series/[Judas] Erased/Season/01.mkv",
                status="wanted",
                target_language="de",
                error="",
                error_count=0,
                added_at=now,
                updated_at=now,
            ),
            WantedItem(
                item_type="episode",
                title="Judas Erased - 02",
                sonarr_series_id=SONARR_ID,
                season_episode="S01E02",
                file_path="/library/series/[Judas] Erased/Season/02.mkv",
                status="downloaded",
                target_language="de",
                error="",
                error_count=0,
                added_at=now,
                updated_at=now,
            ),
            WantedItem(
                item_type="episode",
                title="Other Show - 01",
                sonarr_series_id=11,
                season_episode="S01E01",
                file_path="/library/series/Other/01.mkv",
                status="wanted",
                target_language="de",
                error="",
                error_count=0,
                added_at=now,
                updated_at=now,
            ),
        ]
        db.session.add_all(rows)
        db.session.commit()


@pytest.fixture()
def app_client(temp_db):
    from app import create_app

    app = create_app(testing=True)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield app, client


def test_scan_failure_charges_open_rows_of_that_series_only(app_client):
    app, _client = app_client
    _seed_items(app)

    from db.wanted import record_series_scan_failure

    with app.app_context():
        charged = record_series_scan_failure(SONARR_ID, standalone=False, message="Sonarr exploded")
    assert charged == 1

    from db.wanted import get_wanted_item

    # The open row carries the failure; the settled row of the same series and
    # the other series' open row stay untouched.
    with app.app_context():
        from db.models.core import WantedItem
        from extensions import db

        rows = db.session.query(WantedItem).all()
        by_title = {r.title: r for r in rows}
        failed = by_title["Judas Erased - 01"]
        assert failed.failure_kind == "scan_failed"
        assert failed.error_count == 1
        assert failed.last_error_at is not None
        assert "Sonarr exploded" in failed.error
        assert failed.status == "wanted"
        assert by_title["Judas Erased - 02"].failure_kind is None
        assert by_title["Other Show - 01"].failure_kind is None


def test_health_lists_the_scan_failure(app_client):
    app, client = app_client
    _seed_items(app)
    from db.wanted import record_series_scan_failure

    with app.app_context():
        record_series_scan_failure(SONARR_ID, standalone=False, message="folder unreadable")

    resp = client.get("/api/v1/health/library")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["totals"]["problems"] == 1
    row = next(p for p in body["problems"] if p["failure_kind"] == "scan_failed")
    assert row["title"] == "Judas Erased - 01"


def test_sonarr_series_rescan_no_longer_404s(app_client):
    _app, client = app_client
    scanner = MagicMock(is_scanning=False, scan_series=MagicMock(return_value={"added": 3}))

    with (
        patch("sonarr_client.get_sonarr_client", return_value=MagicMock()),
        patch("services.wanted_scanner.get_scanner", return_value=scanner),
    ):
        resp = client.post(f"/api/v1/standalone/series/{SONARR_ID}/scan")

    assert resp.status_code == 200
    assert resp.get_json()["summary"]["added"] == 3
    scanner.scan_series.assert_called_once_with(SONARR_ID)


def test_standalone_wire_id_resolves_to_its_row(app_client):
    """A negative wire id names row ``-id``; the scan must receive the row id."""
    _app, client = app_client

    with (
        patch("db.standalone.get_standalone_series", return_value={"id": 4, "title": "Standalone"}) as lookup,
        patch("services.standalone_manager.scan_series_or_fallback", return_value={"series_id": 4}) as scan,
    ):
        resp = client.post("/api/v1/standalone/series/-4/scan")

    assert resp.status_code == 200
    lookup.assert_called_once_with(4)
    scan.assert_called_once_with(4)


def test_scanner_error_is_a_bad_gateway_and_charges_the_series(app_client):
    app, client = app_client
    _seed_items(app)
    scanner = MagicMock(is_scanning=False, scan_series=MagicMock(return_value={"error": "sonarr_timeout"}))

    with (
        patch("sonarr_client.get_sonarr_client", return_value=MagicMock()),
        patch("services.wanted_scanner.get_scanner", return_value=scanner),
    ):
        resp = client.post(f"/api/v1/standalone/series/{SONARR_ID}/scan")

    assert resp.status_code == 502
    assert resp.get_json()["error"] == "sonarr_timeout"

    with app.app_context():
        from db.models.core import WantedItem
        from extensions import db

        failed = db.session.query(WantedItem).filter_by(title="Judas Erased - 01").one()
        assert failed.failure_kind == "scan_failed"
        assert failed.error == "sonarr_timeout"


def test_crashed_scan_is_recorded_too(app_client):
    """An exception (not a summary error) still errors *and* charges the series."""
    app, client = app_client
    from db.models.core import WantedItem
    from extensions import db

    with app.app_context():
        now = datetime.now(UTC)
        db.session.add(
            WantedItem(
                item_type="episode",
                title="Standalone Show - 01",
                standalone_series_id=3,
                season_episode="S01E01",
                file_path="/media/standalone/[Standalone Show]/01.mkv",
                status="wanted",
                target_language="de",
                error="",
                error_count=0,
                added_at=now,
                updated_at=now,
            )
        )
        db.session.commit()

    with (
        patch("db.standalone.get_standalone_series", return_value={"id": 3, "title": "Standalone Show"}),
        patch("services.standalone_manager.scan_series_or_fallback", side_effect=RuntimeError("boom")),
    ):
        resp = client.post("/api/v1/standalone/series/-3/scan")

    assert resp.status_code == 500
    with app.app_context():
        charged = db.session.query(WantedItem).filter_by(title="Standalone Show - 01").one()
        assert charged.failure_kind == "scan_failed"
        assert charged.error == "scan crashed: boom"
