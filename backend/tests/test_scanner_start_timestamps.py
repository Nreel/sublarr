"""Wanted scanner start timestamps — the footer activity block reads these."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from services.wanted_scanner_core import WantedScanner


def _iso(stamp):
    assert stamp is not None
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    assert parsed <= datetime.now(UTC)
    return parsed


def test_start_timestamps_start_empty():
    scanner = WantedScanner()
    assert scanner.scan_started_at is None
    assert scanner.search_started_at is None


def test_scan_all_stamps_scan_started_at():
    scanner = WantedScanner()
    scanner._scan_all_locked = lambda incremental: {"added": 0, "updated": 0}
    scanner._report_scan = lambda result: result
    scanner.scan_all(incremental=True)
    _iso(scanner.scan_started_at)


def test_scan_series_stamps_scan_started_at(mocker):
    scanner = WantedScanner()
    mocker.patch.object(scanner, "_scan_standalone_series", return_value=None)
    mocker.patch("services.wanted_scanner_core.get_settings", return_value=MagicMock())
    mocker.patch("sonarr_client.get_sonarr_client", return_value=None)
    assert scanner.scan_series(1) == {"error": "sonarr_not_configured"}
    _iso(scanner.scan_started_at)


def test_scan_movie_stamps_scan_started_at(mocker):
    scanner = WantedScanner()
    mocker.patch.object(scanner, "_scan_standalone_movie", return_value=None)
    mocker.patch("services.wanted_scanner_core.get_settings", return_value=MagicMock())
    mocker.patch("radarr_client.get_radarr_client", return_value=None)
    assert scanner.scan_movie(1) == {"error": "radarr_not_configured"}
    _iso(scanner.scan_started_at)


def test_search_all_stamps_search_started_at(mocker):
    scanner = WantedScanner()
    mocker.patch("services.wanted_scanner_core.run_wanted_search", return_value={"found": 0})
    scanner.search_all()
    _iso(scanner.search_started_at)


def test_scanner_status_exposes_start_timestamps(client, monkeypatch):
    scanner = MagicMock()
    scanner.is_scanning = True
    scanner.is_searching = False
    scanner.scan_progress = {}
    scanner.last_scan_at = None
    scanner.last_search_at = None
    scanner.scan_started_at = "2026-11-24T00:00:00+00:00"
    scanner.search_started_at = None
    scanner.last_summary = {}
    monkeypatch.setattr("services.wanted_scanner.get_scanner", lambda: scanner)
    body = client.get("/api/v1/wanted/scanner/status").get_json()
    assert body["scan_started_at"] == "2026-11-24T00:00:00+00:00"
    assert body["search_started_at"] is None
