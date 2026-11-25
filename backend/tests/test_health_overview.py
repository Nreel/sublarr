"""Tests for services.health_overview + GET /api/v1/health/library
and the sync-rate fields added to /api/v1/statistics/subtitles."""

from datetime import UTC, datetime, timedelta


def _add_wanted(app, title, status="wanted", failure_kind=None, item_type="episode", **kw):
    from db.models.core import WantedItem
    from extensions import db

    with app.app_context():
        now = datetime.now(UTC)
        item = WantedItem(
            item_type=item_type,
            title=title,
            file_path=kw.get("file_path", f"/media/{title}/{title}-{status}.mkv"),
            status=status,
            failure_kind=failure_kind,
            season_episode=kw.get("season_episode", "S01E01"),
            target_language="de",
            error=kw.get("error", ""),
            error_count=kw.get("error_count", 0),
            last_error_at=kw.get("last_error_at"),
            search_count=kw.get("search_count", 0),
            added_at=now,
            updated_at=now,
        )
        db.session.add(item)
        db.session.commit()
        return item.id


def _add_provider_stats(app, name, searches=0, hits=0, auto_disabled=False):
    from db.models.providers import ProviderStats
    from extensions import db

    with app.app_context():
        row = ProviderStats(
            provider_name=name,
            total_searches=searches,
            successful_searches=hits,
            auto_disabled=1 if auto_disabled else 0,
            updated_at=datetime.now(UTC),
        )
        db.session.add(row)
        db.session.commit()


def _add_breaker(app, name, state="open", failures=5):
    from db.models.circuit_breaker import CircuitBreakerState
    from extensions import db

    with app.app_context():
        db.session.add(
            CircuitBreakerState(
                name=name,
                state=state,
                failure_count=failures,
                updated_at=datetime.now(UTC),
            )
        )
        db.session.commit()


def _add_translation_event(
    app, backend, status, started, error_type=None, error_msg=None, lines=5, job_id=None
):
    from db.models.translation import TranslationEvent
    from extensions import db

    with app.app_context():
        db.session.add(
            TranslationEvent(
                backend=backend,
                source_lang="en",
                target_lang="de",
                lines_count=lines,
                chars_in=100,
                status=status,
                error_type=error_type,
                error_msg=error_msg,
                started_at=started,
                job_id=job_id,
            )
        )
        db.session.commit()


def _add_job(app, job_id, status="failed", error="", created=None, source_format="ass"):
    from db.models.core import Job
    from extensions import db

    with app.app_context():
        now = created or datetime.now(UTC)
        db.session.add(
            Job(
                id=job_id,
                file_path="/media/Show A/Show A - S01E01.mkv",
                status=status,
                source_format=source_format,
                error=error,
                created_at=now,
                completed_at=now if status != "queued" else None,
            )
        )
        db.session.commit()


def _add_backend_stats(app, name, requests=0, failed=0, consecutive_failures=0, last_error=""):
    from db.models.translation import TranslationBackendStats
    from extensions import db

    with app.app_context():
        now = datetime.now(UTC)
        db.session.add(
            TranslationBackendStats(
                backend_name=name,
                total_requests=requests,
                successful_translations=requests - failed,
                failed_translations=failed,
                consecutive_failures=consecutive_failures,
                last_error=last_error,
                last_failure_at=now - timedelta(hours=2) if failed else None,
                last_success_at=now if requests - failed else None,
                updated_at=now,
            )
        )
        db.session.commit()


class TestLibraryHealthService:
    def test_empty_library(self, app_ctx):
        from services.health_overview import get_library_health

        result = get_library_health()
        assert result["totals"]["wanted"] == 0
        assert result["totals"]["problems"] == 0
        assert result["problems"] == []
        assert result["translation"] == {
            "failures_7d": 0,
            "stuck_items": 0,
            "backends": [],
            "recent_errors": [],
            "pipeline_errors": [],
        }

    def test_problem_items_cover_every_error_signal(self, client):
        app = client.application
        _add_wanted(app, "Show A", status="wanted", file_path="/m/a1.mkv")
        _add_wanted(app, "Show A", status="failed", error="File not found", file_path="/m/a2.mkv")
        _add_wanted(app, "Show A", failure_kind="unsourceable", file_path="/m/a3.mkv")
        # Requeued by an operator: status back to 'wanted' and no recorded kind,
        # but the fault is still on the row. Only the error side carries it, so
        # a clause that reads status/kind alone would hide it.
        _add_wanted(
            app, "Show A", status="wanted", error="Provider returned 500", file_path="/m/a4.mkv"
        )
        _add_wanted(
            app,
            "Show A",
            status="wanted",
            error_count=2,
            last_error_at=datetime.now(UTC),
            file_path="/m/a5.mkv",
        )
        _add_wanted(app, "Show B", status="wanted", file_path="/m/b1.mkv")
        # Ignored rows are never shown, and never counted — not even as unmatched.
        _add_wanted(app, "Show C", status="ignored", file_path="/m/c1.mkv")
        _add_wanted(
            app, "Show C", status="ignored", failure_kind="unsourceable", file_path="/m/c2.mkv"
        )

        resp = client.get("/api/v1/health/library")
        assert resp.status_code == 200
        body = resp.get_json()

        assert body["totals"]["wanted"] == 6  # ignored excluded
        assert body["totals"]["problems"] == 4
        assert body["totals"]["unmatched"] == 1

        paths = {p["title"] for p in body["problems"]}
        assert paths == {"Show A"}
        assert len(body["problems"]) == 4
        kinds = {p["failure_kind"] for p in body["problems"]}
        assert "unsourceable" in kinds
        assert kinds == {None, "unsourceable"}  # error-only rows carry no kind
        assert {p["status"] for p in body["problems"]} == {"failed", "wanted"}
        assert all(p["status"] != "ignored" for p in body["problems"])
        assert {p["error"] for p in body["problems"]} == {
            "File not found",
            "Provider returned 500",
            "",
        }
        # The per-title roll-up moved to /wanted; the payload no longer carries it.
        assert "series" not in body
        assert "series_affected" not in body["totals"]

    def test_problem_list_is_not_truncated(self, client):
        app = client.application
        for i in range(120):
            _add_wanted(app, f"Show {i}", failure_kind="provider_error", file_path=f"/m/{i}.mkv")

        resp = client.get("/api/v1/health/library")
        assert resp.status_code == 200
        body = resp.get_json()
        # The frontend paints in chunks; the payload must never drop rows.
        assert len(body["problems"]) == 120
        assert body["totals"]["problems"] == 120

    def test_failures_recorded_after_a_read_surface_on_the_next_read(self, client):
        # /health/library is deliberately not response-cached: a failure written
        # after one poll must show up on the next poll, not stay hidden until
        # the cache TTL expires.
        assert client.get("/api/v1/health/library").get_json()["totals"]["problems"] == 0

        _add_wanted(
            client.application,
            "Late Failure",
            status="failed",
            error="boom",
            file_path="/m/late.mkv",
        )

        body = client.get("/api/v1/health/library").get_json()
        assert body["totals"]["problems"] == 1
        assert body["problems"][0]["error"] == "boom"

    def test_provider_health_merges_breaker_and_stats(self, client):
        app = client.application
        _add_provider_stats(app, "goodprov", searches=100, hits=60)
        _add_provider_stats(app, "deadprov", searches=50, hits=1)
        _add_breaker(app, "brokenprov", state="open", failures=7)

        resp = client.get("/api/v1/health/library")
        assert resp.status_code == 200
        providers = {p["provider"]: p for p in resp.get_json()["providers"]}

        assert providers["goodprov"]["degraded"] is False
        assert providers["deadprov"]["degraded"] is True  # 2% hit rate over 50 searches
        assert providers["brokenprov"]["degraded"] is True
        assert providers["brokenprov"]["breaker_state"] == "open"
        assert providers["brokenprov"]["breaker_failures"] == 7
        # Degraded providers sort first.
        listed = [p["provider"] for p in resp.get_json()["providers"]]
        assert listed.index("goodprov") > max(listed.index("deadprov"), listed.index("brokenprov"))

    def test_translation_section(self, client):
        app = client.application
        now = datetime.now(UTC)
        _add_backend_stats(
            app,
            "ollama",
            requests=10,
            failed=3,
            consecutive_failures=2,
            last_error="Connection refused",
        )
        _add_backend_stats(app, "azure", requests=5, failed=0, consecutive_failures=0)
        _add_translation_event(
            app,
            "ollama",
            "error",
            now - timedelta(hours=2),
            error_type="LineCountMismatchError",
            error_msg="expected 4 lines, got 3",
        )
        _add_translation_event(app, "ollama", "timeout", now - timedelta(hours=1))
        _add_translation_event(app, "ollama", "ok", now - timedelta(minutes=30))
        _add_translation_event(app, "ollama", "cancelled", now - timedelta(minutes=10))
        _add_translation_event(app, "azure", "error", now - timedelta(days=8))
        # Pipeline failures — jobs that broke before reaching a backend. The 8-day-old
        # one is listed (the list is not windowed) but not counted.
        _add_job(app, "j1", error="No source subtitle found to translate from")
        _add_job(app, "j2", error="boom", created=now - timedelta(days=8))
        # A backend exception fails its job too; that job belongs to the event,
        # so it must not appear in the pipeline list or inflate the count.
        _add_translation_event(
            app,
            "ollama",
            "error",
            now - timedelta(hours=3),
            error_msg="Connection refused",
            job_id="j3",
        )
        _add_job(app, "j3", error="Connection refused")
        _add_job(app, "j4", status="completed")
        _add_job(app, "j5", status="cancelled", error="operator cancel")
        _add_wanted(
            app,
            "Show T",
            status="failed",
            failure_kind="translation_error",
            error="translation failed",
        )

        resp = client.get("/api/v1/health/library")
        assert resp.status_code == 200
        tr = resp.get_json()["translation"]

        # error + timeout inside the window; ok, cancelled, and an 8-day-old
        # error are all excluded. j1 (no backend event) counts as a pipeline
        # failure; j3's job is already counted as its event.
        assert tr["failures_7d"] == 4
        assert tr["stuck_items"] == 1

        # Failing backend sorts first.
        assert [b["backend"] for b in tr["backends"]] == ["ollama", "azure"]
        assert tr["backends"][0]["failed"] == 3
        assert tr["backends"][0]["consecutive_failures"] == 2
        assert tr["backends"][0]["last_error"] == "Connection refused"

        # Recent errors: newest first, failed statuses only — the list is not
        # windowed, so the 8-day-old azure failure is listed too.
        assert len(tr["recent_errors"]) == 4
        assert tr["recent_errors"][0]["status"] == "timeout"
        assert tr["recent_errors"][1]["error_type"] == "LineCountMismatchError"
        assert tr["recent_errors"][1]["error_msg"] == "expected 4 lines, got 3"
        assert tr["recent_errors"][2]["error_msg"] == "Connection refused"
        assert tr["recent_errors"][3]["backend"] == "azure"
        assert tr["recent_errors"][0]["started_at"] > tr["recent_errors"][1]["started_at"]

        # Pipeline failures: failed jobs with no backend event, newest first.
        # j3 (backend-attributed), j4 (completed) and j5 (cancelled) are out.
        assert [p["job_id"] for p in tr["pipeline_errors"]] == ["j1", "j2"]
        assert tr["pipeline_errors"][0]["error"] == "No source subtitle found to translate from"
        assert tr["pipeline_errors"][0]["source_format"] == "ass"
        assert tr["pipeline_errors"][0]["created_at"] > tr["pipeline_errors"][1]["created_at"]


class TestSyncRateInSubtitlesStats:
    def _add_sync_run(self, app, status, engine="ffsubsync"):
        from db.models.core import SyncJobRun
        from extensions import db

        with app.app_context():
            db.session.add(
                SyncJobRun(
                    engine=engine,
                    status=status,
                    offset_ms=100,
                    duration_ms=1000,
                    subtitle_path="/m/a.de.srt",
                    video_path="/m/a.mkv",
                    created_at=datetime.now(UTC),
                )
            )
            db.session.commit()

    def test_sync_rate_none_without_runs(self, client):
        resp = client.get("/api/v1/statistics/subtitles")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["sync_runs"] == 0
        assert body["sync_rate"] is None

    def test_sync_rate_computed(self, client):
        app = client.application
        self._add_sync_run(app, "ok")
        self._add_sync_run(app, "ok")
        self._add_sync_run(app, "ok")
        self._add_sync_run(app, "failed")

        resp = client.get("/api/v1/statistics/subtitles")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["sync_runs"] == 4
        assert body["sync_ok"] == 3
        assert body["sync_rate"] == 0.75
