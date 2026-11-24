"""Tests for the operational error sections added to /health/library:
scheduler_errors, whisper_errors, sync_errors, ops_errors, hook_errors,
backup_errors."""

import json
from datetime import UTC, datetime, timedelta


def _add_job_run(app, job_id, status, started=None, error_type=None, error_msg=None, triggered_by="schedule"):
    from db.models.scheduler import JobRun
    from extensions import db

    with app.app_context():
        db.session.add(
            JobRun(
                job_id=job_id,
                started_at=started or datetime.now(UTC),
                status=status,
                triggered_by=triggered_by,
                error_type=error_type,
                error_msg=error_msg,
            )
        )
        db.session.commit()


def _add_whisper_job(app, job_id, status, error="", backend="faster-whisper", created=None):
    from db.models.translation import WhisperJob
    from extensions import db

    with app.app_context():
        now = datetime.now(UTC)
        db.session.add(
            WhisperJob(
                id=job_id,
                file_path=f"/m/{job_id}.mkv",
                status=status,
                error=error,
                backend_name=backend,
                created_at=created or now,
                completed_at=now if status in ("failed", "cancelled", "completed") else None,
            )
        )
        db.session.commit()


def _add_sync_run(app, status, engine="ffsubsync", video="/m/v.mkv", reason=None, created=None):
    from db.models.core import SyncJobRun
    from extensions import db

    with app.app_context():
        db.session.add(
            SyncJobRun(
                engine=engine,
                status=status,
                duration_ms=1000,
                subtitle_path="/m/v.en.srt",
                video_path=video,
                reason=reason,
                created_at=created or datetime.now(UTC),
            )
        )
        db.session.commit()


def _add_activity(app, event_type, status, error=None, file_path=None, created=None):
    from db.models.activity import ActivityLog
    from extensions import db

    with app.app_context():
        db.session.add(
            ActivityLog(
                event_type=event_type,
                file_path=file_path,
                status=status,
                details_json=json.dumps({"error": error}) if error else None,
                created_at=created or datetime.now(UTC),
            )
        )
        db.session.commit()


def _add_hook(app, name, event_name="subtitle_downloaded", hook_id=None, success=0, error="boom"):
    from db.models.hooks import HookConfig, HookLog
    from extensions import db

    with app.app_context():
        now = datetime.now(UTC)
        if hook_id is None:
            cfg = HookConfig(
                name=name,
                event_name=event_name,
                hook_type="script",
                enabled=1,
                created_at=now,
                updated_at=now,
            )
            db.session.add(cfg)
            db.session.commit()
            hook_id = cfg.id
        db.session.add(
            HookLog(
                hook_id=hook_id,
                event_name=event_name,
                hook_type="script",
                success=success,
                error=error,
                triggered_at=now,
            )
        )
        db.session.commit()


def _add_notification(app, event_type, status="failed", error="apprise refused", sent=None):
    from db.models.notifications import NotificationHistory
    from extensions import db

    with app.app_context():
        db.session.add(
            NotificationHistory(
                event_type=event_type,
                title=f"{event_type} title",
                body="body",
                status=status,
                error=error,
                sent_at=sent or datetime.now(UTC),
            )
        )
        db.session.commit()


class TestOpsErrorSections:
    def test_empty_sections_present(self, app_ctx):
        from services.health_overview import get_library_health

        health = get_library_health()
        for key in (
            "scheduler_errors",
            "whisper_errors",
            "sync_errors",
            "ops_errors",
            "hook_errors",
            "backup_errors",
        ):
            assert health[key] == [], key

    def test_scheduler_errors_statuses_and_window(self, app_ctx):
        from services.health_overview import get_library_health

        base = datetime.now(UTC)
        _add_job_run(
            app_ctx,
            "wanted_scanner",
            "error",
            started=base - timedelta(minutes=30),
            error_type="RuntimeError",
            error_msg="sonarr 500",
        )
        _add_job_run(app_ctx, "cleanup", "timeout", started=base - timedelta(minutes=20), error_msg="ran past timeout")
        _add_job_run(app_ctx, "wanted_revive", "missed", started=base - timedelta(minutes=10))
        _add_job_run(app_ctx, "stats_rollup", "ok", started=base)
        _add_job_run(app_ctx, "upgrade_scan", "skipped_overlap", started=base)
        _add_job_run(
            app_ctx,
            "anidb_sync",
            "error",
            started=datetime.now(UTC) - timedelta(days=8),
            error_msg="ancient",
        )

        errs = get_library_health()["scheduler_errors"]
        assert [e["job_id"] for e in errs] == ["wanted_revive", "cleanup", "wanted_scanner"]
        assert errs[2]["error_type"] == "RuntimeError"
        assert errs[2]["error_msg"] == "sonarr 500"
        assert errs[2]["triggered_by"] == "schedule"
        assert errs[0]["started_at"]

    def test_whisper_errors_failed_and_cancelled(self, app_ctx):
        from services.health_overview import get_library_health

        _add_whisper_job(app_ctx, "w1", "failed", error="cuda OOM")
        _add_whisper_job(app_ctx, "w2", "cancelled")
        _add_whisper_job(app_ctx, "w3", "completed")

        errs = get_library_health()["whisper_errors"]
        assert {e["job_id"] for e in errs} == {"w1", "w2"}
        w1 = next(e for e in errs if e["job_id"] == "w1")
        assert w1["error"] == "cuda OOM"
        assert w1["file_path"] == "/m/w1.mkv"
        assert w1["backend_name"] == "faster-whisper"
        assert w1["completed_at"]

    def test_sync_errors_failed_rows(self, app_ctx):
        from services.health_overview import get_library_health

        _add_sync_run(app_ctx, "failed", engine="alass", reason="alass exit 1")
        _add_sync_run(app_ctx, "ok")

        errs = get_library_health()["sync_errors"]
        assert len(errs) == 1
        assert errs[0]["job_id"] == "alass"
        assert errs[0]["file_path"] == "/m/v.mkv"
        assert errs[0]["error"] == "alass exit 1"
        assert errs[0]["started_at"]

    def test_ops_errors_from_activity_log(self, app_ctx):
        from services.health_overview import get_library_health

        _add_activity(app_ctx, "remux", "failed", error="mkvmerge died", file_path="/m/a.mkv")
        _add_activity(app_ctx, "remux", "success")

        errs = get_library_health()["ops_errors"]
        assert len(errs) == 1
        assert errs[0]["event_type"] == "remux"
        assert errs[0]["file_path"] == "/m/a.mkv"
        assert errs[0]["error"] == "mkvmerge died"

    def test_hook_errors_join_config_names(self, app_ctx):
        from services.health_overview import get_library_health

        _add_hook(app_ctx, "notify-on-download", error="script timeout")
        _add_hook(app_ctx, "healthy-hook", success=1)

        errs = get_library_health()["hook_errors"]
        assert len(errs) == 1
        assert errs[0]["hook"] == "notify-on-download"
        assert errs[0]["error"] == "script timeout"

    def test_backup_errors_from_notification_history(self, app_ctx):
        from services.health_overview import get_library_health

        _add_notification(app_ctx, "error", status="failed", error="backup exploded")
        _add_notification(app_ctx, "subtitle_found", status="sent")

        errs = get_library_health()["backup_errors"]
        assert len(errs) == 1
        assert errs[0]["event_type"] == "error"
        assert errs[0]["error"] == "backup exploded"

    def test_sections_capped_newest_first(self, app_ctx):
        from services.health_overview import get_library_health

        base = datetime.now(UTC)
        for i in range(60):
            _add_activity(app_ctx, "scan", "failed", error=f"err{i}", created=base - timedelta(minutes=60 - i))

        errs = get_library_health()["ops_errors"]
        assert len(errs) == 50
        assert errs[0]["error"] == "err59"  # newest first
        assert errs[-1]["error"] == "err10"

    def test_endpoint_exposes_sections(self, client):
        with client.application.app_context():
            _add_notification(client.application, "error", status="failed", error="db backup failed")
        resp = client.get("/api/v1/health/library?fresh=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["backup_errors"][0]["error"] == "db backup failed"
        assert "scheduler_errors" in body


class TestBreakerPersistence:
    def test_persist_breaker_state_writes_row(self, app_ctx):
        from db.circuit_breaker import persist_breaker_state
        from db.models.circuit_breaker import CircuitBreakerState
        from extensions import db

        persist_breaker_state("opensubtitles", "open", 5, 1234.5)
        with app_ctx.app_context():
            row = db.session.get(CircuitBreakerState, "opensubtitles")
        assert row is not None
        assert row.state == "open"
        assert row.failure_count == 5
        assert row.last_failure_epoch == 1234.5

        # Upsert, not a second row.
        persist_breaker_state("opensubtitles", "closed", 0, 1234.5)
        with app_ctx.app_context():
            row = db.session.get(CircuitBreakerState, "opensubtitles")
        assert row.state == "closed"
        assert row.failure_count == 0

    def test_breaker_state_reaches_health_providers(self, app_ctx):
        from db.circuit_breaker import persist_breaker_state
        from services.health_overview import get_library_health

        persist_breaker_state("yts", "half_open", 3, None)
        providers = {p["provider"]: p for p in get_library_health()["providers"]}
        assert providers["yts"]["breaker_state"] == "half_open"
        assert providers["yts"]["breaker_failures"] == 3
