"""Content-based language guards for the translation flows.

Prod bug 2026-11-24: a Spanish fansub carried a [RU] tag; the flow trusted
the tag and the LLM echoed the Spanish lines instead of translating them, so
a Spanish file was saved under .ru.ass. SubtitleEdit runs LanguageAutoDetect
on the SOURCE only (--translate-from) and has no whole-file check of the
TARGET output — we add both: ``resolve_source_language`` (trust content over
the tag) and ``guard_output_language`` (refuse a non-target result before
saving). Inconclusive detection must never block a legitimate translation.
"""

import shutil
from unittest.mock import MagicMock, patch

from tests.test_translator_core import _make_ass_file, _make_result, _make_srt_file

SPANISH_LINES = [
    "¿Dónde está la estación de tren?",
    "El tren llega en cinco minutos más.",
    "No olvides los boletos en la taquilla.",
    "La lluvia empieza a caer sobre la ciudad.",
    "Mi abuela cocía este pan cada domingo.",
    "Los niños juegan en el parque del barrio.",
    "El doctor dijo que necesita más descanso.",
    "La reunión comenzará a las ocho en punto.",
    "Debemos hablar con el gerente mañana mismo.",
    "El viento sopla fuerte junto al mar.",
    "Esta canción recuerda los veranos del pueblo.",
    "La puerta del jardín está cerrada con llave.",
]

RUSSIAN_LINES = [
    "Где находится вокзал?",
    "Поезд прибыл через пять минут.",
    "Не забудьте билеты в кассе.",
    "Дождь начинается над городом.",
    "Бабушка пекла этот хлеб каждое воскресенье.",
    "Дети играют в парке нашего района.",
    "Врач сказал, что нужно больше отдыхать.",
    "Собрание начнётся ровно в восемь часов.",
    "Мы должны поговорить с управляющим завтра.",
    "Ветер сильный у моря.",
    "Эта песня вспоминает лето в деревне.",
    "Дверь сада закрыта на ключ.",
]

GIBBERISH_LINES = [
    "xqjw vkpl ztrb nmhf gds",
    "qzxd wmpk jvrt lfbn hwc",
    "vkqp zjwr tbmf hnxl dgk",
    "dfjx qzkp wmbv rtln jwh",
    "zjqw xkpv dfrb mthn gwq",
    "bpqz wjvk xrtm dfnl zkh",
    "jzqw pkvx wtfb rnmh dgp",
    "xzqp vkjw mtbf rlnh qwd",
    "qjzw xpvk wbmf tnhl jrf",
    "kvqp zjwx wbtf rnhm gpz",
    "pwqz xjvk tmbf rlnh wdk",
    "zqjw pkvx wmbf tlnh qrf",
]


def _patched_flow(tmp_path, mkv, ass_path=None, srt_path=None, settings=None, translated=None):
    """Patch the translator package namespace the flows look up at call time."""
    output_path = str(tmp_path / "video.ru.ass")
    settings = settings or MagicMock(
        hi_removal_enabled=False, source_language="ru", target_language="ru"
    )
    pkg = MagicMock()
    if ass_path is not None:
        pkg.extract_subtitle_stream = MagicMock(
            side_effect=lambda mkv_, si, out: shutil.copy(ass_path, out)
        )
    pkg.get_settings = MagicMock(return_value=settings)
    pkg._translate_with_manager = MagicMock(
        return_value=(list(translated) if translated is not None else [], _make_result([]))
    )
    pkg._get_quality_config = MagicMock(return_value=(False, 50, 2))
    patches = [
        patch("translator.core._pkg", return_value=pkg),
        patch("translator.core.get_output_path_for_lang", return_value=output_path),
        patch("translator.core.check_disk_space"),
        patch("translator.core._write_quality_sidecar"),
        patch("translator.core._compute_quality_stats", return_value={}),
        patch("translator.core._check_translation_quality", return_value=[]),
        patch("nfo_export.maybe_write_nfo"),
    ]
    for p in patches:
        p.start()
    return pkg, output_path, patches


def _stop_patches(patches):
    for p in patches:
        p.stop()


# --- detect_content_language ------------------------------------------------


def test_detect_content_language_spanish():
    from translator._helpers import detect_content_language

    assert detect_content_language(SPANISH_LINES) == "es"


def test_detect_content_language_russian():
    from translator._helpers import detect_content_language

    assert detect_content_language(RUSSIAN_LINES) == "ru"


def test_detect_content_language_gibberish_is_none():
    from translator._helpers import detect_content_language

    assert detect_content_language(GIBBERISH_LINES) is None


def test_detect_content_language_short_sample_is_none():
    from translator._helpers import detect_content_language

    assert detect_content_language(["Hola"]) is None
    assert detect_content_language([]) is None


# --- resolve_source_language ------------------------------------------------


def test_resolve_corrects_mislabelled_source():
    """Spanish dialogue tagged 'ru' is translated FROM Spanish, with a reason."""
    from translator._helpers import resolve_source_language

    src, reason = resolve_source_language("ru", SPANISH_LINES, "ru")
    assert src == "es"
    assert reason == "tagged ru, content detected es"


def test_resolve_keeps_tag_when_content_matches():
    from translator._helpers import resolve_source_language

    src, reason = resolve_source_language("es", SPANISH_LINES, "ru")
    assert src == "es"
    assert reason is None


def test_resolve_content_already_in_target():
    """Russian dialogue tagged 'en' with target 'ru': refusal, not a round-trip."""
    from translator._helpers import ALREADY_TARGET_LANGUAGE, resolve_source_language

    src, reason = resolve_source_language("en", RUSSIAN_LINES, "ru")
    assert src == "ru"
    assert reason == ALREADY_TARGET_LANGUAGE


def test_resolve_tagged_target_language_keeps_tag():
    """Content matching the tag wins over the target comparison (spec order)."""
    from translator._helpers import resolve_source_language

    src, reason = resolve_source_language("ru", RUSSIAN_LINES, "ru")
    assert src == "ru"
    assert reason is None


def test_resolve_inconclusive_keeps_tag():
    from translator._helpers import resolve_source_language

    src, reason = resolve_source_language("en", ["Hola"], "ru")
    assert src == "en"
    assert reason is None


# --- guard_output_language --------------------------------------------------


def test_guard_refuses_spanish_output_for_ru_target():
    from translator._helpers import guard_output_language

    refusal = guard_output_language(SPANISH_LINES, SPANISH_LINES, "ru")
    assert refusal is not None
    assert "detected as es" in refusal
    assert "not target ru" in refusal
    assert "refusing to save" in refusal
    assert "verbatim echo" in refusal


def test_guard_passes_russian_output_for_ru_target():
    from translator._helpers import guard_output_language

    assert guard_output_language(SPANISH_LINES, RUSSIAN_LINES, "ru") is None


def test_guard_passes_when_inconclusive():
    from translator._helpers import guard_output_language

    assert guard_output_language(SPANISH_LINES, ["Bonjour"], "ru") is None


# --- integration: the prod-bug scenario -------------------------------------


def test_translate_ass_refuses_echoed_spanish_and_writes_nothing(tmp_path):
    """Spanish dialogue tagged ru, target ru, an echo from the manager: the
    flow must fail with the refusal and leave the target file untouched."""
    from translator.core import translate_ass

    ass_path = str(tmp_path / "source.ass")
    _make_ass_file(ass_path, SPANISH_LINES)
    pkg, output_path, patches = _patched_flow(
        tmp_path, "/media/test.mkv", ass_path=ass_path, translated=SPANISH_LINES
    )
    try:
        result = translate_ass(
            "/media/test.mkv", {"index": 0, "format": "ass"}, {}, target_language="ru"
        )
    finally:
        _stop_patches(patches)

    assert result["success"] is False
    assert "refusing to save" in result["error"]
    assert "detected as es" in result["error"]
    # Direction was corrected before the call: translated FROM Spanish.
    _, kwargs = pkg._translate_with_manager.call_args
    assert kwargs["source_lang"] == "es"
    assert not (tmp_path / "video.ru.ass").exists()


def test_translate_ass_refuses_same_language_without_llm(tmp_path):
    """Russian dialogue tagged en with target ru: refused before the manager."""
    from translator.core import translate_ass

    ass_path = str(tmp_path / "source.ass")
    _make_ass_file(ass_path, RUSSIAN_LINES)
    settings = MagicMock(hi_removal_enabled=False, source_language="en", target_language="ru")
    pkg, output_path, patches = _patched_flow(
        tmp_path,
        "/media/test.mkv",
        ass_path=ass_path,
        settings=settings,
        translated=RUSSIAN_LINES,
    )
    try:
        result = translate_ass(
            "/media/test.mkv", {"index": 0, "format": "ass"}, {}, target_language="ru"
        )
    finally:
        _stop_patches(patches)

    assert result["success"] is False
    assert result.get("reason") == "content already in target language"
    pkg._translate_with_manager.assert_not_called()
    assert not (tmp_path / "video.ru.ass").exists()


def test_translate_srt_refuses_echoed_spanish_and_writes_nothing(tmp_path):
    from translator.core import translate_srt_from_file

    srt_path = str(tmp_path / "source.srt")
    _make_srt_file(srt_path, SPANISH_LINES)
    settings = MagicMock(hi_removal_enabled=False, source_language="ru", target_language="ru")
    pkg = MagicMock()
    pkg.get_settings = MagicMock(return_value=settings)
    pkg._translate_with_manager = MagicMock(
        return_value=(list(SPANISH_LINES), _make_result(SPANISH_LINES))
    )
    pkg._get_quality_config = MagicMock(return_value=(False, 50, 2))
    output_path = str(tmp_path / "video.ru.srt")
    with (
        patch("translator.core._pkg", return_value=pkg),
        patch("translator.core.get_output_path_for_lang", return_value=output_path),
        patch("translator.core.check_disk_space"),
        patch("translator.core._write_quality_sidecar"),
        patch("translator.core._compute_quality_stats", return_value={}),
        patch("translator.core._check_translation_quality", return_value=[]),
        patch("nfo_export.maybe_write_nfo"),
    ):
        result = translate_srt_from_file("/media/test.mkv", srt_path, target_language="ru")

    assert result["success"] is False
    assert "refusing to save" in result["error"]
    assert "detected as es" in result["error"]
    _, kwargs = pkg._translate_with_manager.call_args
    assert kwargs["source_lang"] == "es"
    assert not (tmp_path / "video.ru.srt").exists()
