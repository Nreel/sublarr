"""Standalone wanted items must carry the upgrade fields the *arr scanner files.

With upgrades enabled and the only subtitle an SRT, the Sonarr/Radarr scanner
writes ``upgrade_candidate=True`` plus the score of that file
(``wanted_item_scanner._check_language_for_item``). The search step then beats
an on-disk subtitle only when the candidate scores higher. Standalone wrote
neither field, so a title with a good SRT was treated like a title with nothing
and any provider result replaced the file on disk.
"""

from unittest.mock import MagicMock, patch


def _scanner():
    from standalone.scanner import StandaloneScanner

    return StandaloneScanner.__new__(StandaloneScanner)


def test_a_sidecar_srt_under_upgrades_is_an_upgrade_candidate():
    s = _scanner()
    with (
        patch("config.get_settings", return_value=MagicMock(upgrade_enabled=True)),
        patch("translator.find_existing_target_file", return_value="/media/m.de.srt"),
        patch("upgrade_scorer.score_existing_subtitle", return_value=("srt", 72)),
    ):
        assert s._upgrade_fields("/media/m.mkv", "de", "srt") == (True, 72)


def test_upgrades_off_leaves_the_row_a_plain_missing_item():
    s = _scanner()
    with patch("config.get_settings", return_value=MagicMock(upgrade_enabled=False)):
        assert s._upgrade_fields("/media/m.mkv", "de", "srt") == (False, 0)


def test_an_ass_sidecar_is_already_the_preferred_format():
    s = _scanner()
    assert s._upgrade_fields("/media/m.mkv", "de", "ass") == (False, 0)


def test_an_embedded_track_has_no_file_to_score():
    s = _scanner()
    assert s._upgrade_fields("/media/m.mkv", "de", "embedded_srt") == (False, 0)


def test_a_sidecar_that_vanished_between_detect_and_score_is_not_a_candidate():
    s = _scanner()
    with (
        patch("config.get_settings", return_value=MagicMock(upgrade_enabled=True)),
        patch("translator.find_existing_target_file", return_value=None),
    ):
        assert s._upgrade_fields("/media/m.mkv", "de", "srt") == (False, 0)


def test_a_scoring_failure_does_not_break_the_scan():
    s = _scanner()
    with (
        patch("config.get_settings", return_value=MagicMock(upgrade_enabled=True)),
        patch("translator.find_existing_target_file", return_value="/media/m.de.srt"),
        patch("upgrade_scorer.score_existing_subtitle", side_effect=OSError("unreadable")),
    ):
        assert s._upgrade_fields("/media/m.mkv", "de", "srt") == (False, 0)
