"""One bad title must not cost the sweep; incremental passes must notice new episodes.

Two prod-shaped failures of the same pass:

* An exception inside one series' scan (a dead database connection, a broken
  profile row) ended the whole instance sweep — and every later instance —
  through the source-level ``except`` in ``_scan_all_sonarr``, which also sets
  ``_scan_had_errors``. The cleanup that follows then skipped, but the
  watermark froze and the titles after the failing one were never looked at.
  Worse, in a pass that did prune, the paths already collected from the
  instance were the only ones cleanup protected — the failing title's rows
  were not among them.
* The incremental Sonarr filter compared only ``added``. A series that got new
  episodes after it was added never looked changed, so new episodes waited for
  the periodic full pass (``FULL_SCAN_INTERVAL`` cycles).
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch


def _scanner():
    from services.wanted_scanner_core import WantedScanner

    s = WantedScanner.__new__(WantedScanner)
    s.__init__()
    return s


def _settings():
    return MagicMock(
        wanted_anime_only=False,
        wanted_anime_movies_only=False,
        scan_yield_ms=0,
        upgrade_enabled=False,
    )


def _sonarr(series):
    client = MagicMock()
    client.get_series.return_value = series
    return client


@contextmanager
def _patches():
    """The two module-level dependencies every instance sweep needs."""
    with (
        patch("services.wanted_scanner_sources.batch_upsert_context"),
        patch("services.wanted_scanner_sources.abort_requested", return_value=False),
    ):
        yield


class TestTitleFailureIsolation:
    def test_one_broken_series_does_not_end_the_instance_sweep(self):
        scanner = _scanner()
        scanner._pass_done = {}
        seen = []

        def fake_scan(
            sonarr, series_id, settings, series=None, instance_name="", auto_extract_fn=None
        ):
            seen.append(series_id)
            if series_id == 2:
                raise RuntimeError("server closed the connection unexpectedly")
            return 1, 0, {f"/media/{series_id}.mkv"}

        series = [{"id": i, "title": f"S{i}"} for i in (1, 2, 3)]
        with (
            patch("services.wanted_scanner_sources.scan_sonarr_series", side_effect=fake_scan),
            patch(
                "services.wanted_scanner_sources.get_wanted_paths_for_title",
                return_value={"/media/row-of-2.mkv"},
            ),
            _patches(),
        ):
            added, _, all_paths = scanner._scan_sonarr_instance(
                _sonarr(series), _settings(), "Sonarr"
            )

        assert seen == [1, 2, 3], "the titles after the failing one were never scanned"
        assert added == 2
        assert all_paths == {"/media/1.mkv", "/media/3.mkv", "/media/row-of-2.mkv"}
        # The failed title's rows join the pass set: cleanup prunes everything
        # the pass did not report, and a transient error must not delete them.
        assert ("sonarr", "Sonarr", 2) not in scanner._pass_done
        assert ("sonarr", "Sonarr", 1) in scanner._pass_done

    def test_a_contained_title_failure_does_not_flag_the_scan(self):
        """``_scan_had_errors`` freezes the watermark and skips pruning; a single
        bad title handled here must not put the whole pass into that state."""
        scanner = _scanner()

        def fake_scan(*args, **kwargs):
            raise RuntimeError("boom")

        series = [{"id": 1, "title": "Broken"}, {"id": 2, "title": "Other"}]
        with (
            patch("services.wanted_scanner_sources.scan_sonarr_series", side_effect=fake_scan),
            patch("services.wanted_scanner_sources.get_wanted_paths_for_title", return_value=set()),
            _patches(),
        ):
            scanner._scan_sonarr_instance(_sonarr(series), _settings(), "Sonarr")

        assert scanner._scan_had_errors is False
        assert scanner._episode_fingerprints == {}

    def test_a_broken_movie_does_not_end_the_radarr_sweep(self):
        scanner = _scanner()
        seen = []

        def fake_scan(radarr, movie, settings, instance_name="", auto_extract_fn=None):
            seen.append(movie["id"])
            if movie["id"] == 2:
                raise RuntimeError("db died")
            return 1, 0, {f"/media/m{movie['id']}.mkv"}

        movies = [{"id": i, "title": f"M{i}"} for i in (1, 2, 3)]
        client = MagicMock()
        client.get_movies.return_value = movies
        with (
            patch("services.wanted_scanner_sources.scan_radarr_movie", side_effect=fake_scan),
            patch(
                "services.wanted_scanner_sources.get_wanted_paths_for_title",
                return_value={"/media/row-of-2.mkv"},
            ),
            _patches(),
        ):
            _, _, all_paths = scanner._scan_radarr_instance(client, _settings(), "Radarr")

        assert seen == [1, 2, 3]
        assert "/media/row-of-2.mkv" in all_paths


class TestEpisodeFileFingerprint:
    @staticmethod
    def _series(count, size):
        return {"statistics": {"episodeFileCount": count, "sizeOnDisk": size}}

    def test_new_episode_files_rescan_the_series(self):
        scanner = _scanner()
        key = ("sonarr", "Sonarr", 7)
        scanner._episode_fingerprints[key] = (3, 100)
        assert scanner._episode_files_changed(key, self._series(4, 250)) is True

    def test_a_replaced_file_of_the_same_count_rescans_the_series(self):
        scanner = _scanner()
        key = ("sonarr", "Sonarr", 7)
        scanner._episode_fingerprints[key] = (3, 100)
        assert scanner._episode_files_changed(key, self._series(3, 120)) is True

    def test_an_unchanged_series_is_not_rescanned(self):
        scanner = _scanner()
        key = ("sonarr", "Sonarr", 7)
        scanner._episode_fingerprints[key] = (3, 100)
        assert scanner._episode_files_changed(key, self._series(3, 100)) is False

    def test_a_series_never_seen_baselines_instead_of_rescanning(self):
        """Otherwise the first incremental pass after a restart re-walks the library."""
        scanner = _scanner()
        assert (
            scanner._episode_files_changed(("sonarr", "Sonarr", 9), self._series(3, 100)) is False
        )

    def test_the_incremental_filter_keeps_a_series_with_new_episode_files(self):
        scanner = _scanner()
        scanner._episode_fingerprints[("sonarr", "Sonarr", 2)] = (1, 100)
        series = [
            {
                "id": 1,
                "title": "Old",
                "added": "2020-01-01T00:00:00Z",
                "statistics": {"episodeFileCount": 1, "sizeOnDisk": 100},
            },
            {
                "id": 2,
                "title": "Fresh",
                "added": "2020-01-01T00:00:00Z",
                "statistics": {"episodeFileCount": 2, "sizeOnDisk": 250},
            },
        ]
        scanned = []

        def fake_scan(
            sonarr, series_id, settings, series=None, instance_name="", auto_extract_fn=None
        ):
            scanned.append(series_id)
            return 0, 0, set()

        with (
            patch("services.wanted_scanner_sources.scan_sonarr_series", side_effect=fake_scan),
            _patches(),
        ):
            scanner._scan_sonarr_instance(
                _sonarr(series), _settings(), "Sonarr", since=datetime(2026, 1, 1, tzinfo=UTC)
            )

        assert scanned == [2], "a series whose episodes moved was invisible to the incremental pass"

    def test_the_fingerprint_is_recorded_after_a_successful_title(self):
        scanner = _scanner()

        def fake_scan(*args, **kwargs):
            return 1, 0, {"/media/x.mkv"}

        series = [{"id": 7, "title": "S", "statistics": {"episodeFileCount": 4, "sizeOnDisk": 900}}]
        with (
            patch("services.wanted_scanner_sources.scan_sonarr_series", side_effect=fake_scan),
            _patches(),
        ):
            scanner._scan_sonarr_instance(_sonarr(series), _settings(), "Sonarr")

        assert scanner._episode_fingerprints[("sonarr", "Sonarr", 7)] == (4, 900)
