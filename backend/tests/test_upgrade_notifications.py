"""Upgrade notifications: the toggle must actually deliver.

Regression guard for the inert `notify_on_upgrade` toggle — no code path used
to call send_notification("upgrade"), so upgrades never reached Apprise and
never fired the upgrade_complete webhook.
"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from events.catalog import EVENT_CATALOG, upgrade_complete


def _ctx(tmp_path, *, title="Show - S01E06"):
    video = tmp_path / f"{title}.mkv"
    video.write_bytes(b"x")
    return {
        "item": {"id": 7, "title": title},
        "item_id": 7,
        "item_lang": "de",
        "file_path": str(video),
        "current_score": 40,
    }


class TestUpgradeAnnouncement:
    def test_upgrade_emits_catalog_payload_and_notifies(self, tmp_path):
        from wanted_search import process as proc

        captured = []

        def receiver(sender, data=None):
            captured.append(data)

        upgrade_complete.connect(receiver)
        try:
            with (
                patch("translator.find_existing_target_file", return_value=None),
                patch.object(proc, "record_upgrade") as record,
                patch("notifier.send_notification") as notify,
            ):
                proc._retire_replaced_srt(
                    _ctx(tmp_path), SimpleNamespace(provider_name="AnimeTosho"), 95, str(tmp_path / "keep.ass")
                )
        finally:
            upgrade_complete.disconnect(receiver)

        assert record.called
        assert captured, "upgrade_complete was not emitted"
        payload = captured[0]
        assert set(payload) == set(EVENT_CATALOG["upgrade_complete"]["payload_keys"])
        assert payload["provider_name"] == "AnimeTosho"
        assert payload["old_score"] == 40 and payload["new_score"] == 95
        # Payload must not carry absolute paths (events.emit_event contract).
        assert not any(os.path.isabs(str(v)) for v in payload.values())
        assert notify.call_args.kwargs["event_type"] == "upgrade"

    def test_notification_failure_does_not_fail_the_upgrade(self, tmp_path):
        from wanted_search import process as proc

        with (
            patch("translator.find_existing_target_file", return_value=None),
            patch.object(proc, "record_upgrade") as record,
            patch("notifier.send_notification", side_effect=RuntimeError("apprise broken")),
            patch("events.emit_event", side_effect=RuntimeError("bus broken")),
        ):
            proc._retire_replaced_srt(
                _ctx(tmp_path), SimpleNamespace(provider_name="AnimeTosho"), 95, str(tmp_path / "keep.ass")
            )

        assert record.called


class TestNotifierResolvesCatalogEventNames:
    """Templates and filters are stored under EVENT_CATALOG names."""

    def _settings(self):
        return MagicMock(notify_on_upgrade=True, notify_manual_actions=False)

    def _repo(self, template):
        repo = MagicMock()
        repo.is_quiet_hours.return_value = False
        repo.find_template_for_event.return_value = template
        return repo

    def _cfg(self, include=None, exclude=None):
        cfg = MagicMock()

        def get_entry(key):
            if key == "notification_filter_include_events":
                return include
            if key == "notification_filter_exclude_events":
                return exclude
            return None

        cfg.get_config_entry.side_effect = get_entry
        return cfg

    def test_upgrade_template_stored_under_catalog_name_applies(self, app_ctx):
        from notifier import send_notification

        template = {
            "id": 1,
            "enabled": True,
            "title_template": "U: {{ title }} -> {{ new_format }}",
            "body_template": "{{ old_score }}->{{ new_score }} via {{ provider_name }}",
        }
        repo = self._repo(template)
        ap = MagicMock()

        with (
            patch("config.get_settings", return_value=self._settings()),
            patch("db.repositories.config.ConfigRepository", return_value=self._cfg()),
            patch("db.repositories.notifications.NotificationRepository", return_value=repo),
            patch("notifier._get_apprise", return_value=ap),
        ):
            send_notification(title="raw", body="raw", event_type="upgrade")

        assert repo.find_template_for_event.call_args.args[0] == "upgrade_complete"
        assert ap.notify.called
        assert ap.notify.call_args.kwargs["title"] == "U: raw -> ass"
        assert "->" in ap.notify.call_args.kwargs["body"]
        # History keeps the notifier label, so the history filter UI still works.
        assert repo.log_notification.call_args.kwargs["event_type"] == "upgrade"

    def test_exclude_filter_by_catalog_name_suppresses(self, app_ctx):
        from notifier import send_notification

        ap = MagicMock()
        with (
            patch("config.get_settings", return_value=self._settings()),
            patch("db.repositories.config.ConfigRepository", return_value=self._cfg(exclude='["upgrade_complete"]')),
            patch("db.repositories.notifications.NotificationRepository", return_value=self._repo(None)),
            patch("notifier._get_apprise", return_value=ap),
        ):
            send_notification(title="raw", body="raw", event_type="upgrade")

        ap.notify.assert_not_called()

    def test_exclude_filter_by_legacy_notifier_name_still_suppresses(self, app_ctx):
        from notifier import send_notification

        ap = MagicMock()
        with (
            patch("config.get_settings", return_value=self._settings()),
            patch("db.repositories.config.ConfigRepository", return_value=self._cfg(exclude='["upgrade"]')),
            patch("db.repositories.notifications.NotificationRepository", return_value=self._repo(None)),
            patch("notifier._get_apprise", return_value=ap),
        ):
            send_notification(title="raw", body="raw", event_type="upgrade")

        ap.notify.assert_not_called()
