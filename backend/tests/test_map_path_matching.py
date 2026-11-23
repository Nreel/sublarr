"""The *arr path mapping matches whole folders and prefers the longest pair.

Before 1.17.1 ``map_path`` took the first pair whose remote prefix was a plain
string prefix of the path: ``/data/movies=/mnt/movies`` also rewrote
``/data/movies-4k/...`` to ``/mnt/movies-4k/...``, a general pair listed first
shadowed a specific one, and a trailing slash on one side only glued the rest
of the path onto the folder name. The media server mapping already behaved
(1.17.0); this pins the same rules for Sonarr/Radarr paths.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from config_utils import map_path


def _mapped(mapping: str, path: str) -> str:
    with patch("config.get_settings", return_value=SimpleNamespace(path_mapping=mapping)):
        return map_path(path)


def test_a_single_pair_maps_as_before():
    assert _mapped("/data/tv=/mnt/tv", "/data/tv/Show/S01E01.mkv") == "/mnt/tv/Show/S01E01.mkv"


def test_a_pair_matches_whole_folders_only():
    assert (
        _mapped("/data/movies=/mnt/movies", "/data/movies-4k/Film/Film.mkv")
        == "/data/movies-4k/Film/Film.mkv"
    )


def test_the_longest_pair_wins_in_any_order():
    mapping = "/data=/mnt;/data/anime=/anime"
    assert _mapped(mapping, "/data/anime/Show/ep.mkv") == "/anime/Show/ep.mkv"
    assert _mapped(mapping, "/data/tv/Show/ep.mkv") == "/mnt/tv/Show/ep.mkv"


@pytest.mark.parametrize(
    "mapping", ["/data/tv/=/mnt/tv", "/data/tv=/mnt/tv/", "/data/tv/=/mnt/tv/"]
)
def test_a_trailing_slash_on_either_side_is_fine(mapping):
    assert _mapped(mapping, "/data/tv/Show/ep.mkv") == "/mnt/tv/Show/ep.mkv"


def test_the_folder_itself_maps():
    assert _mapped("/data/tv=/mnt/tv", "/data/tv") == "/mnt/tv"


def test_no_matching_pair_leaves_the_path():
    assert _mapped("/data/tv=/mnt/tv;broken;=/x", "/other/ep.mkv") == "/other/ep.mkv"


def test_a_windows_local_prefix_joins_backslashes():
    # Separator style follows the local prefix, not the host.
    assert _mapped("/data/tv=D:/tv", "/data/tv/Show/ep.mkv") == "D:\\tv\\Show\\ep.mkv"


# Sonarr/Radarr on Windows report "D:\..." or UNC "\\server\share\..." paths (#228).
UNC_FILE = "\\\\192.168.1.198\\kuf\\Anime Season\\Show\\Staffel 02\\Show.S02E01.mkv"


def test_a_windows_unc_path_maps_to_forward_slashes():
    assert (
        _mapped("\\\\192.168.1.198\\kuf=/media", UNC_FILE)
        == "/media/Anime Season/Show/Staffel 02/Show.S02E01.mkv"
    )


@pytest.mark.parametrize(
    "remote", ["//192.168.1.198/kuf", "\\\\192.168.1.198\\kuf\\", "//192.168.1.198/kuf/"]
)
def test_the_windows_prefix_matches_with_either_separator(remote):
    assert (
        _mapped(f"{remote}=/media", UNC_FILE)
        == "/media/Anime Season/Show/Staffel 02/Show.S02E01.mkv"
    )


def test_a_drive_letter_path_maps_to_forward_slashes():
    assert _mapped("D:\\TV=/mnt/tv", "D:\\TV\\Show\\ep.mkv") == "/mnt/tv/Show/ep.mkv"


def test_a_windows_pair_still_matches_whole_folders_only():
    assert _mapped("D:\\TV=/mnt/tv", "D:\\TV-4K\\Show\\ep.mkv") == "D:\\TV-4K\\Show\\ep.mkv"


def test_a_backslash_in_a_posix_file_name_is_kept():
    assert _mapped("/data/tv=/mnt/tv", "/data/tv/Show/a\\b.mkv") == "/mnt/tv/Show/a\\b.mkv"


# Mapping is idempotent: the scanner resolves a Sonarr path once, and the editor /
# HI tools hand that local path back in. A pair whose local prefix sits inside its
# remote prefix ("/media=/media/library") used to rewrite it again into
# "/media/library/library/...", so GET /tools/content answered 404 — "Subtitle file
# not found" — for a sidecar the listing had just found (2026-11-23).
def test_a_nested_pair_does_not_remap_an_already_mapped_path():
    assert _mapped("/media=/media/library", "/media/library/Season/[Judas] Erased - 01.ru.srt") == (
        "/media/library/Season/[Judas] Erased - 01.ru.srt"
    )
    assert _mapped("/media=/media/library", "/media/library") == "/media/library"


def test_a_nested_pair_still_maps_a_remote_path():
    assert _mapped("/media=/media/library", "/media/Season/[Judas] Erased - 01.ru.srt") == (
        "/media/library/Season/[Judas] Erased - 01.ru.srt"
    )


def test_a_mapped_windows_path_is_not_remapped():
    assert _mapped(
        "D:\\TV=D:\\TV\\anime", UNC_FILE.replace("\\\\192.168.1.198\\kuf", "D:\\TV\\anime")
    ) == ("D:\\TV\\anime\\Anime Season\\Show\\Staffel 02\\Show.S02E01.mkv")


def test_a_windows_local_prefix_keeps_backslashes():
    assert _mapped("\\\\nas\\tv=T:\\", "\\\\nas\\tv\\Show\\ep.mkv") == "T:\\Show\\ep.mkv"
