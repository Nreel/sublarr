"""Which language a translation of a file goes into.

The language profile governing the file decides, as it does for the wanted
search. The global ``settings.target_language`` is only the last fallback: it
is not shown in the settings UI and defaults to 'de', so using it first sent
every UI-started translation of a non-German profile into German (#254).
"""

import logging
from typing import NamedTuple

from config import _get_language_tags, get_settings
from config_language_data import language_name, normalize_language_code
from db.profiles import get_profile_for_item
from db.wanted import get_wanted_items_by_path

logger = logging.getLogger(__name__)

# arr_context key naming the language one job translates into. A re-translation
# of a single wanted row sets it so the job keeps that row's language even when
# the profile has several targets; retried jobs inherit it with the context.
TRANSLATE_TO_KEY = "translate_to"


class TranslationTarget(NamedTuple):
    code: str
    name: str
    # Ordered source-language priority (first = most preferred). The profile's
    # ``source_languages`` list is the whole source policy; the global
    # ``settings.source_language`` is only the fallback when no profile row
    # backs the item. Target language never appears: translating into a
    # language from itself is not a translation.
    sources: list[str]


def _settings_target() -> TranslationTarget:
    s = get_settings()
    return TranslationTarget(s.target_language, s.target_language_name, [s.source_language])


def _ordered_sources(profile: dict, target: str, fallback: list[str]) -> list[str]:
    """The profile's source priority minus the target, de-duplicated."""
    ordered: list[str] = []
    for raw in list(profile.get("source_languages") or []):
        code = normalize_language_code(raw or "")
        if code and code != target and code not in ordered:
            ordered.append(code)
    return ordered or [c for c in fallback if c and c != target]


def _pick_code(profile_targets: list[str], wanted_items: list[dict]) -> str | None:
    """The first profile target that still has a wanted row for this file.

    Without such a row the profile's first target, then the first wanted row.
    """
    wanted = [
        normalize_language_code(i.get("target_language") or "")
        for i in wanted_items
        if i.get("target_language")
    ]
    # Return the NORMALIZED code. Profile targets are stored verbatim
    # (repositories/profiles.py writes ``target_languages_json`` with no
    # cleaner), so a legacy alias like "ger" used to flow out raw: sidecars
    # named ``Movie.ger.ass`` and translation-memory rows keyed under
    # ``target_lang="ger"`` beside the canonical "de" ones - split-brain
    # cache keys and inconsistent cleanup for the same logical language.
    for code in profile_targets:
        norm = normalize_language_code(code or "")
        if norm and norm in wanted:
            return norm
    for code in profile_targets:
        norm = normalize_language_code(code or "")
        if norm:
            return norm
    return wanted[0] if wanted else None


def resolve_translation_target(
    file_path: str, arr_context: dict | None = None
) -> TranslationTarget:
    """Target code, target name and ordered source-language priority for ``file_path``.

    The profile is looked up through the file's wanted row (series, movie or
    standalone owner), else through ``arr_context``, else the default profile.
    A failed lookup falls back to the global settings and is logged.
    """
    fallback = _settings_target()
    try:
        items = get_wanted_items_by_path(file_path) or []
        profile = get_profile_for_item(items[0] if items else arr_context) or {}
    except Exception as exc:
        logger.warning(
            "Translation target for %s: profile lookup failed (%s); using the global target %s",
            file_path,
            exc,
            fallback.code,
        )
        return fallback

    targets = list(profile.get("target_languages") or [])
    stamped = normalize_language_code((arr_context or {}).get(TRANSLATE_TO_KEY) or "")
    code = stamped or _pick_code(targets, items)
    if not code:
        return fallback
    # ``code`` is canonical here (both branches normalize), so the name and
    # sidecar/cache keys never depend on a legacy alias stored on the row or
    # in the profile.
    names = list(profile.get("target_language_names") or [])
    name = ""
    for raw, nm in zip(targets, names):
        if normalize_language_code(raw or "") == code:
            name = nm
            break
    return TranslationTarget(
        code,
        name or language_name(code),
        _ordered_sources(profile, code, fallback.sources),
    )


def target_sidecar_patterns(code: str, fmt: str) -> list[str]:
    """Sidecar suffixes (``.ru.srt``, ``.rus.srt``, ...) of a translation into ``code``."""
    return [f".{tag}.{fmt}" for tag in _get_language_tags(code)]
