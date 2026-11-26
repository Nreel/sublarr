"""Steps 2/4 of the wanted search walk the profile's ordered source list (#80).

The fork's profile carries an ordered ``source_languages`` priority; Steps 2
and 4 only ever search languages inside it (never the item's target). A
profile saved before the validation may hold "EN" or junk: valid entries are
normalised, entries that are not language tags are filtered with a warning
so they never reach a provider or a file name.
"""

from types import SimpleNamespace

from wanted_search.process import _source_priority


def _ctx(source_languages, global_source="en", item_lang="de"):
    return {
        "_pf": {"source_languages": source_languages},
        "settings": SimpleNamespace(source_language=global_source),
        "item": {"id": 1},
        "item_lang": item_lang,
    }


def test_profile_entries_win_over_the_global_source_in_order():
    assert _source_priority(_ctx(["EN", "de", "ja"], item_lang="pt")) == ["en", "de", "ja"]


def test_invalid_entries_are_filtered_and_order_is_kept():
    assert _source_priority(_ctx(["EN", "../x", " de "], item_lang="pt")) == ["en", "de"]


def test_entry_equal_to_the_target_is_dropped():
    assert _source_priority(_ctx(["EN", "de"], item_lang="de")) == ["en"]


def test_global_fallback_without_profile_entries():
    assert _source_priority(_ctx([])) == ["en"]


def test_empty_priority_when_the_global_source_is_the_target():
    assert _source_priority(_ctx([], item_lang="en")) == []
