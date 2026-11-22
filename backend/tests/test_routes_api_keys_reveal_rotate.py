"""Reveal / rotate semantics for /api/v1/api-keys.

Pins the behaviour the settings UI depends on: the key the UI displays is the
value auth actually accepts (env-authoritative when SUBLARR_API_KEY is set, DB
override otherwise), reveal returns the full value, rotate takes effect without
a restart, and a masked display value cannot be saved as a credential.
"""

from __future__ import annotations

from unittest.mock import patch

RAW = "bdea8565fc9b45471b884883c2019db8"


class TestReveal:
    def test_reveal_returns_raw_value_from_db(self, client):
        def fake_entry(key):
            return RAW if key == "api_key" else ""

        with patch("db.config.get_config_entry", side_effect=fake_entry):
            resp = client.get("/api/v1/api-keys/sublarr/reveal")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["keys"][0] == {"name": "api_key", "value": RAW}

    def test_reveal_falls_back_to_env_key_when_db_row_empty(self, client):
        from config_settings import Settings

        with (
            patch("db.config.get_config_entry", return_value=""),
            patch("config.peek_settings", return_value=Settings(api_key=RAW)),
        ):
            resp = client.get("/api/v1/api-keys/sublarr/reveal")
            listed = client.get("/api/v1/api-keys/")

        assert resp.status_code == 200
        assert resp.get_json()["keys"][0]["value"] == RAW
        sublarr = next(s for s in listed.get_json()["services"] if s["service"] == "sublarr")
        assert sublarr["status"] == "configured"
        assert sublarr["keys"][0]["masked_value"] == RAW[:4] + "***" + RAW[-4:]

    def test_reveal_unknown_service_returns_404(self, client):
        resp = client.get("/api/v1/api-keys/nope/reveal")
        assert resp.status_code == 404


class TestUpdateRejectsMaskedValue:
    def test_masked_value_is_rejected_not_saved(self, client):
        with patch("db.config.save_config_entry") as save:
            resp = client.put("/api/v1/api-keys/sublarr", json={"api_key": "abcd***wxyz"})
        assert resp.status_code == 400
        assert "masked" in resp.get_json()["error"]
        save.assert_not_called()


class TestRotate:
    def test_rotate_takes_effect_without_restart(self, client):
        import config_singleton

        saved: dict[str, str] = {}

        def fake_save(key, value):
            saved[key] = value

        with (
            patch("db.config.save_config_entry", side_effect=fake_save),
            patch("db.config.get_all_config_entries", side_effect=lambda: dict(saved)),
        ):
            resp = client.post("/api/v1/api-keys/sublarr/rotate")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "rotated"
        assert len(saved["api_key"]) == 64
        assert data["masked_value"] == saved["api_key"][:4] + "***" + saved["api_key"][-4:]
        # api_key is runtime-overridable, so the rotated key gates requests now.
        assert config_singleton.get_settings().api_key == saved["api_key"]

        config_singleton._settings = None

    def test_rotate_refused_when_env_key_is_set(self, client, monkeypatch):
        monkeypatch.setenv("SUBLARR_API_KEY", RAW)
        with patch("db.config.save_config_entry") as save:
            resp = client.post("/api/v1/api-keys/sublarr/rotate")
        assert resp.status_code == 409
        assert "SUBLARR_API_KEY" in resp.get_json()["error"]
        save.assert_not_called()

    def test_rotate_refused_for_multi_credential_service(self, client):
        resp = client.post("/api/v1/api-keys/opensubtitles/rotate")
        assert resp.status_code == 400

    def test_rotate_unknown_service_returns_404(self, client):
        resp = client.post("/api/v1/api-keys/nope/rotate")
        assert resp.status_code == 404
