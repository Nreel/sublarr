"""A profile's source languages must be language tags (#80 follow-up).

Since #80 the profile sources name temporary files in the wanted search, so
a value like "../x" must never reach a provider. The fork stores an ORDERED
priority list; each entry is normalised (lower-case primary subtag, trimmed
spaces) instead of refused — a profile saved before the validation may hold
"EN" or " de ", and refusing it would block every later save from the UI.
"""

import pytest

from services.profile_service import (
    ProfileValidationError,
    normalize_source_tag,
    validate_create_profile_data,
    validate_update_profile_fields,
)

_BASE = {"name": "P", "target_languages": ["de"], "translation_backend": "ollama"}


@pytest.mark.parametrize("bad", ["../x", "en/..", "EN GLISH", "", "e", "toolongcode"])
def test_create_refuses_entries_that_are_not_language_tags(bad):
    with pytest.raises(ProfileValidationError, match="source_languages"):
        validate_create_profile_data({**_BASE, "source_languages": [bad]})


@pytest.mark.parametrize("good", ["en", "ja", "pt-BR", "zh-Hans"])
def test_create_accepts_language_tags(good):
    assert validate_create_profile_data({**_BASE, "source_languages": [good]})["source_langs"] == [
        good
    ]


def test_create_defaults_to_en():
    assert validate_create_profile_data(dict(_BASE))["source_langs"] == ["en"]


def test_update_refuses_a_bad_entry():
    with pytest.raises(ProfileValidationError, match="source_languages"):
        validate_update_profile_fields({"source_languages": ["../x"]})


@pytest.mark.parametrize(
    ("raw", "clean"), [("EN", "en"), (" de ", "de"), ("PT-BR", "pt-BR"), ("Ja", "ja")]
)
def test_create_normalises_case_and_spaces_per_entry(raw, clean):
    # A profile saved before the validation may hold "EN"; refusing it would
    # block every later save of that profile from the UI.
    assert validate_create_profile_data({**_BASE, "source_languages": [raw]})["source_langs"] == [
        clean
    ]


def test_update_normalises_a_legacy_list_and_keeps_priority_order():
    assert validate_update_profile_fields({"source_languages": ["EN", " de "]})[
        "source_languages"
    ] == [
        "en",
        "de",
    ]


def test_update_normalises_a_bare_string_legacy_entry():
    assert validate_update_profile_fields({"source_languages": "EN"})["source_languages"] == ["en"]


def test_normalize_source_tag_rejects_non_strings():
    assert normalize_source_tag(None) is None
    assert normalize_source_tag(7) is None
