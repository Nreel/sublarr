"""Tests for health check endpoints."""

import pytest


def _mock_probes(mocker, *, sonarr="ok", radarr="ok", media_servers=None):
    """Stub the five service probes; ``media_servers`` defaults to one healthy Jellyfin."""
    mocker.patch(
        "routes.system.health._health_check_ollama",
        return_value=({"ollama": "ok"}, True),
    )
    mocker.patch(
        "routes.system.health._health_check_providers",
        return_value=({"providers": "healthy"}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_sonarr",
        return_value=({"sonarr": sonarr}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_radarr",
        return_value=({"radarr": radarr}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_media_servers",
        return_value=(
            media_servers
            if media_servers is not None
            else {"media_servers": "1/1 healthy", "media_server_by_type": {"jellyfin": "ok"}},
            None,
        ),
    )


def test_health_returns_503_when_ollama_down(client, mocker):
    """GET /health must return 503 when Ollama reports unhealthy."""
    mocker.patch(
        "routes.system.health._health_check_ollama",
        return_value=({"ollama": "unreachable"}, False),
    )
    mocker.patch(
        "routes.system.health._health_check_providers",
        return_value=({"providers": "healthy"}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_sonarr",
        return_value=({"sonarr": "ok"}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_radarr",
        return_value=({"radarr": "ok"}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_media_servers",
        return_value=({"media_servers": "1/1 healthy"}, None),
    )
    resp = client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.json["status"] == "unhealthy"


def test_health_returns_200_when_ollama_healthy(client, mocker):
    """GET /health must return 200 when Ollama is healthy."""
    mocker.patch(
        "routes.system.health._health_check_ollama",
        return_value=({"ollama": "ok"}, True),
    )
    mocker.patch(
        "routes.system.health._health_check_providers",
        return_value=({"providers": "healthy"}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_sonarr",
        return_value=({"sonarr": "ok"}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_radarr",
        return_value=({"radarr": "ok"}, None),
    )
    mocker.patch(
        "routes.system.health._health_check_media_servers",
        return_value=({"media_servers": "1/1 healthy"}, None),
    )
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json["status"] == "healthy"


def test_service_state_enum_mapping():
    """_service_state maps probe entries to the footer enum."""
    from routes.system.health import _service_state

    assert _service_state(None) == "timeout"  # probe never returned (budget exceeded)
    assert _service_state("timeout") == "timeout"
    assert _service_state("not configured") == "not_configured"
    assert _service_state("error") == "down"
    assert _service_state("unhealthy: Cannot connect to Sonarr") == "down"
    assert _service_state("ok") == "ok"


def test_health_authenticated_states_present(client, mocker):
    """Authenticated body carries states alongside version/services."""
    _mock_probes(mocker)
    resp = client.get("/api/v1/health")
    body = resp.get_json()
    assert resp.status_code == 200
    # jsonify sorts keys, so insertion order is not observable — assert membership.
    assert set(body) == {"status", "states", "version", "services"}
    assert body["states"] == {
        "backend": "alive",
        "database": "ok",
        "sonarr": "ok",
        "radarr": "ok",
        "jellyfin": "ok",
    }


def test_health_states_enum_from_probe_entries(client, mocker):
    _mock_probes(
        mocker,
        sonarr="unhealthy: Cannot connect to Sonarr at http://192.168.1.10:8989",
        radarr="not configured",
        media_servers={
            "media_servers": "0/1 healthy",
            "media_server:jellyfin": "unhealthy: timeout",
            "media_server_by_type": {"jellyfin": "down"},
        },
    )
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200  # informational states never flip the status
    assert resp.get_json()["states"] == {
        "backend": "alive",
        "database": "ok",
        "sonarr": "down",
        "radarr": "not_configured",
        "jellyfin": "down",
    }


def test_health_states_timeout_and_missing_jellyfin(client, mocker):
    _mock_probes(
        mocker,
        sonarr="timeout",
        radarr="error",
        media_servers={"media_servers": "none configured"},  # no by-type key
    )
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200  # a timed-out optional probe never flaps liveness
    body = resp.get_json()
    assert body["states"] == {
        "backend": "alive",
        "database": "ok",
        "sonarr": "timeout",
        "radarr": "down",
        "jellyfin": "not_configured",
    }
