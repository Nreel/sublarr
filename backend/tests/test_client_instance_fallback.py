"""An unknown instance name must not poison the client cache.

``get_sonarr_client("Sonarr-2")`` answers with the first instance's client and
labels the scan rows ``Sonarr-2``. Cached under that missing name, the wrong
pairing survived for the rest of the process — until some unrelated config
change called ``invalidate_client()`` — so rows of one instance were pruned or
searched as another's, and an instance later added under that name was never
reached. Cache it under the instance it actually talks to.
"""

from unittest.mock import patch

import radarr_client
import sonarr_client


def _reset():
    sonarr_client._clients_cache.clear()
    radarr_client._clients_cache.clear()


def test_fallback_client_is_cached_under_the_instance_it_talks_to():
    _reset()
    instances = [{"name": "Primary", "url": "http://a:8989", "api_key": "k1"}]
    with patch("config.get_sonarr_instances", return_value=instances):
        sonarr_client.get_sonarr_client(instance_name="Missing")

    assert set(sonarr_client._clients_cache) == {"Primary"}


def test_an_instance_added_under_the_previously_missing_name_is_used():
    _reset()
    first = [{"name": "Primary", "url": "http://a:8989", "api_key": "k1"}]
    with patch("config.get_sonarr_instances", return_value=first):
        poisoned = sonarr_client.get_sonarr_client(instance_name="Second")

    both = [
        {"name": "Primary", "url": "http://a:8989", "api_key": "k1"},
        {"name": "Second", "url": "http://b:8989", "api_key": "k2"},
    ]
    with patch("config.get_sonarr_instances", return_value=both):
        real = sonarr_client.get_sonarr_client(instance_name="Second")

    assert real is not poisoned
    assert real.api_key == "k2"


def test_the_fallback_client_is_reused_for_the_real_name():
    _reset()
    instances = [{"name": "Primary", "url": "http://a:8989", "api_key": "k1"}]
    with patch("config.get_sonarr_instances", return_value=instances):
        fallback = sonarr_client.get_sonarr_client(instance_name="Missing")
        direct = sonarr_client.get_sonarr_client(instance_name="Primary")

    assert direct is fallback


def test_radarr_fallback_is_cached_under_the_real_name():
    _reset()
    instances = [{"name": "Primary", "url": "http://a:7878", "api_key": "k1"}]
    with patch("config.get_radarr_instances", return_value=instances):
        radarr_client.get_radarr_client(instance_name="Missing")

    assert set(radarr_client._clients_cache) == {"Primary"}
