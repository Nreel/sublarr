"""Lyric-aware chunk boundaries and CJK-safe line-break repair.

`build_chunks(..., music_boundaries=True)` must never put dialogue and lyrics
in the same batch, while the default path stays byte-for-byte the old chunking.
`fix_line_breaks(..., target_lang=...)` repairs break syntax but leaves
spacing alone for CJK targets and lyric lines.
"""

import inspect

from ass_utils import fix_line_breaks
from translation.context_windower import build_chunks, has_music_symbols


def test_has_music_symbols():
    for glyph in "♩♪♫♬🎵🎶":
        assert has_music_symbols(f"{glyph} la la")
    # Raw text, override tags included.
    assert has_music_symbols("{\\c&HFF0000&}♪ la la")
    assert not has_music_symbols("plain dialogue line")
    assert not has_music_symbols("")


def test_music_boundaries_is_keyword_only():
    param = inspect.signature(build_chunks).parameters["music_boundaries"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is False


def test_batch_grows_to_next_lyric_line_never_crosses_it():
    lines = [f"d{i}" for i in range(10)] + ["♪ song"] + [f"d{i}" for i in range(10, 20)]
    chunks = build_chunks(lines, batch_size=5, lookback=2, lookahead=2, music_boundaries=True)

    assert chunks[0].batch == lines[:11]
    assert chunks[0].batch[-1] == "♪ song"
    assert chunks[0].batch_start_index == 0

    # Next chunk starts right after the boundary line.
    assert chunks[1].batch_start_index == 11
    assert chunks[1].batch == lines[11:16]
    assert len(chunks) == 3
    assert chunks[-1].batch == lines[16:]

    # Lookback/lookahead semantics still apply around the boundary.
    assert chunks[1].lookback == lines[9:11]
    assert chunks[1].lookahead == lines[16:18]


def test_no_lyric_ahead_keeps_plain_batch_size():
    """A stretch of dialogue after the last lyric is chunked normally, not glued."""
    lines = ["♪ song"] + [f"d{i}" for i in range(20)]
    chunks = build_chunks(lines, batch_size=5, lookback=0, lookahead=0, music_boundaries=True)
    # The lyric line still ends its own chunk; dialogue after it chunks normally.
    assert [len(chunk.batch) for chunk in chunks] == [1, 5, 5, 5, 5]


def test_batch_shrinks_when_lyric_falls_inside_window():
    lines = ["a", "b", "c", "d", "🎶 s1", "🎶 s2", "e", "f", "g", "h"] + [
        "🎵 s3",
        "i",
        "j",
        "k",
        "l",
        "m",
    ]
    chunks = build_chunks(lines, batch_size=10, lookback=3, lookahead=2, music_boundaries=True)

    assert chunks[0].batch == lines[:6]
    assert chunks[0].batch[-1] == "🎶 s2"
    assert chunks[1].batch_start_index == 6
    assert chunks[1].batch == lines[6:11]
    assert chunks[1].batch[-1] == "🎵 s3"
    assert chunks[1].lookback == ["d", "🎶 s1", "🎶 s2"]  # clipped to what precedes start
    assert chunks[1].lookahead == ["i", "j"]
    assert chunks[2].batch == lines[11:]


def test_no_batch_spans_lyric_block():
    """Dialogue never sits on both sides of a lyric line inside one batch."""
    lines = [
        "hello there",
        "how are you",
        "♪ verse one",
        "♪ verse two",
        "♪ verse three",
        "back to dialogue",
        "more dialogue",
        "🎶 chorus",
        "🎶 chorus 2",
        "tail line",
    ]
    chunks = build_chunks(lines, batch_size=3, lookback=1, lookahead=1, music_boundaries=True)

    covered = [line for chunk in chunks for line in chunk.batch]
    assert covered == lines
    for chunk in chunks:
        lyric_positions = [i for i, line in enumerate(chunk.batch) if has_music_symbols(line)]
        assert lyric_positions == [] or lyric_positions[-1] == len(chunk.batch) - 1


def test_music_boundaries_false_is_identical_to_legacy():
    lines = ["a", "b", "c", "♪ song", "d", "e", "f", "🎶 song2", "g", "h"]
    with_flag = build_chunks(lines, batch_size=3, lookback=2, lookahead=1, music_boundaries=False)
    default = build_chunks(lines, batch_size=3, lookback=2, lookahead=1)

    assert with_flag == default
    assert [chunk.batch_start_index for chunk in default] == [0, 3, 6, 9]
    assert default[0].batch == ["a", "b", "c"]


def test_music_boundaries_empty_and_single_line():
    assert build_chunks([], batch_size=5, music_boundaries=True) == []
    assert build_chunks(["♪ only"], batch_size=5, music_boundaries=True)[0].batch == ["♪ only"]


def test_fix_line_breaks_signature_keyword_only():
    param = inspect.signature(fix_line_breaks).parameters["target_lang"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_fix_line_breaks_default_unchanged():
    assert fix_line_breaks("Line 1\\nLine 2") == "Line 1\\NLine 2"
    assert fix_line_breaks("Hello  world\nLine 2") == "Hello world\\NLine 2"


def test_fix_line_breaks_cjk_target_keeps_spacing():
    for lang in ("zh", "ja", "ko", "th", "zho", "jpn", "kor", "tha", "zh-CN", "ja_JP"):
        assert fix_line_breaks("你好  世界\n第二行", target_lang=lang) == "你好  世界\\N第二行"


def test_fix_line_breaks_cjk_text_skips_even_without_target():
    assert fix_line_breaks("안녕  보세요") == "안녕  보세요"
    assert fix_line_breaks("こんにちは  です") == "こんにちは  です"


def test_fix_line_breaks_non_cjk_target_still_repairs():
    assert fix_line_breaks("Привет   мир\nВторой", target_lang="ru") == "Привет мир\\NВторой"


def test_fix_line_breaks_lyric_line_keeps_spacing():
    assert fix_line_breaks("♪ la   la\nsecond line", target_lang="en") == "♪ la   la\\Nsecond line"
