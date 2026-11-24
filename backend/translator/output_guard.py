"""Reject LLM output that is chat filler instead of a translation.

Prod 2026-08-18: 1124 translation-memory rows held the model's conversational
replies ("Okay, please provide the English anime subtitle lines...") instead
of translations, written during the batch_size=1 era. The line-count check in
translator.manager cannot catch these — a chat reply is exactly one line —
and once cached they replay into every later file whose source line matches.
"""

import re

# Phrases that only ever appear when the model talks ABOUT translating
# instead of translating. Kept deliberately narrow: a false positive here
# fails the whole batch, so generic words ("ready", "translate") are always
# anchored inside a longer assistant-speak phrase.
_CHAT_FILLER_PATTERNS = (
    r"please provide",
    r"ready when you are",
    r"okay,? i'?m ready",
    r"here (?:is|are) (?:the|your) translat",
    r"subtitle lines? you want me to",
    r"as an ai",
    r"language model",
    r"i can(?:not|'t) translate",
    r"hier (?:ist|sind) die übersetz",
)

_CHAT_FILLER_RE = re.compile("|".join(f"(?:{p})" for p in _CHAT_FILLER_PATTERNS), re.IGNORECASE)


def find_chat_filler(lines):
    """Return (index, line) pairs whose text is chat filler, not a translation.

    Args:
        lines: Translated lines as returned by a backend. None entries
            (cache placeholders) are skipped.

    Returns:
        list[tuple[int, str]]: Offending lines with their index in the batch,
        empty when every line looks like an actual translation.
    """
    return [(i, line) for i, line in enumerate(lines) if line and _CHAT_FILLER_RE.search(line)]


def find_script_mismatch(lines, target_lang):
    """Return a reason when a batch came back in the wrong writing system.

    The filler guard above catches the model talking; this catches the model
    echoing. A Chinese source pushed through an "English → German" prompt
    comes back Chinese, one line per line, and the line-count check is
    satisfied. None when the target's script is unknown or the batch is too
    short to judge.
    """
    from subtitle_script import find_script_mismatch as _find

    return _find(lines, target_lang)


# A source line needs this many words before an unchanged copy of it means
# anything: names, calls and "Papa … Papa!" stay the same in any language.
_ECHO_MIN_WORDS = 3
# Below this many such lines a batch is too small to tell an echo from lines
# that legitimately stay. Refusing there would split down to a single line
# that can never pass, and the whole file would fail over one kept title.
_ECHO_MIN_LINES = 4
_ECHO_MAX_SHARE = 0.5
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")
_WORD_RE = re.compile(r"\w+")


def _echo_key(line):
    return " ".join(_WORD_RE.findall(_ASS_TAG_RE.sub("", line or "").lower()))


def find_untranslated_echo(source_lines, translated_lines):
    """Return a reason when a batch came back as its own input.

    The script check catches an echo only across writing systems. Between two
    Latin languages (de → en, en → de) an untranslated batch passes every
    other check — benchmark 2026-11-14 had ten of fifteen lines come back
    German from a de → en request. None when the batch is too small to judge
    or most of its lines were actually translated.
    """
    pairs = [
        (_echo_key(src), _echo_key(out))
        for src, out in zip(source_lines, translated_lines)
        if len(_WORD_RE.findall(_ASS_TAG_RE.sub("", src or ""))) >= _ECHO_MIN_WORDS
    ]
    if len(pairs) < _ECHO_MIN_LINES:
        return None
    echoed = sum(1 for src, out in pairs if src == out)
    if echoed / len(pairs) < _ECHO_MAX_SHARE:
        return None
    return f"{echoed} of {len(pairs)} lines unchanged"


# --- SubtitleEdit line gates (ported 2026-11-24) -------------------------
#
# SubtitleEdit's TranslationEchoGuard decides per line whether the line is
# even worth translating before comparing source with output. A kept title
# ("Geese!") or a call-out is not an untranslated batch, and the share-based
# check above cannot tell the two apart. These gates classify lines; the
# manager acts on the indices.

# A line only counts as "needs translation" at this many words and letters —
# the same floor as _ECHO_MIN_WORDS above, plus a letter floor so "a b c"
# is not a translation target.
_TRANSLATION_MIN_LETTERS = 10
# Scripts written without spaces (CJK, kana, Hangul, Thai) have no word
# boundaries to count, so they qualify on a lower letter floor instead.
_SCRIPT_MIN_LETTERS = 6
# Distinct ordinary words a line must carry before an unchanged copy of it
# means anything. Names are excluded from the count (see _ordinary_words).
_ECHO_MIN_ORDINARY_WORDS = 3

# Unicode ranges for writing systems that do not separate words by space.
_NO_SPACE_SCRIPT_RANGES = (
    (0x3040, 0x30FF),  # Hiragana
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7FF),  # Hangul syllables
    (0x0E00, 0x0E7F),  # Thai
)

# <br>, \N and \n are line breaks inside one subtitle line; HTML tags carry
# styling, not text. Both collapse to a space so a reflowed translation is
# still comparable with its source.
_BREAK_RE = re.compile(r"<br>|\\N|\n", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]*>")


def _strip_line(line):
    """Collapse one subtitle line to comparable text, keeping case."""
    text = _BREAK_RE.sub(" ", line or "")
    text = _ASS_TAG_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    return " ".join(text.split())


def _letters(text):
    return sum(1 for ch in text if ch.isalpha())


def _has_no_space_script(text):
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in _NO_SPACE_SCRIPT_RANGES)


def _ordinary_words(stripped):
    """Distinct words that carry content, per SubtitleEdit's word gate.

    Counted: the first word of the line, any lowercase-initial word, and any
    all-caps word with more than one letter. Skipped: capital-initial words
    that are not all-caps — those are names, and a line of names legitimately
    reads the same in both languages.
    """
    seen = set()
    for i, word in enumerate(_WORD_RE.findall(stripped)):
        letters = _letters(word)
        counted = i == 0 or word[:1].islower() or (word.isupper() and letters > 1)
        if counted:
            seen.add(word.lower())
    return len(seen)


def needs_translation(text):
    """Whether a line carries enough content to expect a translation of it."""
    stripped = _strip_line(text)
    if not stripped:
        return False
    words = len(_WORD_RE.findall(stripped))
    letters = _letters(stripped)
    if words >= _ECHO_MIN_WORDS and letters >= _TRANSLATION_MIN_LETTERS:
        return True
    return _has_no_space_script(stripped) and letters >= _SCRIPT_MIN_LETTERS


def _echo_norm(text):
    return _strip_line(text).lower()


def find_echo_indices(source_lines, translated_lines):
    """Return the batch indices whose translation is its own source line.

    SubtitleEdit TranslationEchoGuard: a line counts only when it needs
    translation (see :func:`needs_translation`) AND carries at least
    ``_ECHO_MIN_ORDINARY_WORDS`` distinct ordinary words — otherwise a batch
    of names, calls or titles comes back identical and is legitimately so.
    A multi-line block is compared only when the two sides have the same
    number of lines; a merged or split block is a line-count problem, not an
    echo.
    """
    if len(source_lines) != len(translated_lines):
        return []
    indices = []
    for i, (src, out) in enumerate(zip(source_lines, translated_lines)):
        if not out:
            continue
        stripped = _strip_line(src)
        if not needs_translation(stripped):
            continue
        if _ordinary_words(stripped) < _ECHO_MIN_ORDINARY_WORDS:
            continue
        if _echo_norm(stripped) == _echo_norm(out):
            indices.append(i)
    return indices


def find_duplicated_translation(source_lines, translated_lines, start_index=1):
    """Return an index where two different sources got the same translation.

    SubtitleEdit TranslationShiftGuard: a batch that came back shifted by one
    line pairs each source with its neighbour's translation, and the line
    count still looks correct. Two unrelated source lines ending up with one
    output line is the observable symptom. ``start_index`` skips the first
    line, which may legitimately share its output with nothing yet.

    Returns:
        int | None: The first offending index at or after ``start_index``,
        or None when every translation belongs to its own source.
    """
    first_by_output = {}
    for i, (src, out) in enumerate(zip(source_lines, translated_lines)):
        if not out or not needs_translation(out):
            continue
        key = _echo_norm(out)
        earlier = first_by_output.get(key)
        if earlier is None:
            first_by_output[key] = i
            continue
        if i >= start_index and _echo_norm(src) != _echo_norm(source_lines[earlier]):
            return i
    return None


# JSON scaffolding that leaks into a translation when the model answers with
# its prompt format instead of a line: an example key-value pair, a dangling
# quote before a brace, or a closing brace pair. Curly quotes count too — a
# server that re-types the JSON produces them.
_MALFORMED_STRUCTURE_RE = re.compile(
    r"""2["\u201c\u201d]:["\u201c\u201d]|["\u201c\u201d]\}|\}["\u201c\u201d]?\}|\}\]""",
    re.UNICODE,
)
_PROMPT_LEAK_TEXT = "<translation of line"


def find_malformed_value(source, translation):
    """Return a reason when a returned line is not usable subtitle text.

    Three shapes seen in production:
      * a placeholder ("...", "…", "-") where the source had real content —
        the model abstained, and the gap would reach the file;
      * the prompt's own example ("<translation of line N>") copied out;
      * JSON structure left in the line (``2":"``, ``"}``, ``}]}``).

    ``source`` may be None for callers that verify output without the input;
    the placeholder gate then has nothing to compare against and stays quiet.
    """
    if not translation:
        return None
    if (
        source
        and any(ch.isalnum() for ch in source)
        and not any(ch.isalnum() for ch in translation)
    ):
        return f"placeholder instead of a translation ({translation[:40]!r})"
    if _PROMPT_LEAK_TEXT in translation.lower():
        return f"prompt example leaked into the translation ({translation[:60]!r})"
    if _MALFORMED_STRUCTURE_RE.search(translation):
        return f"JSON structure leaked into the translation ({translation[:60]!r})"
    return None


# A source line this long is long enough to measure an expansion ratio on;
# shorter ones carry too little text for the ratio to mean anything.
_RUNAWAY_MIN_SOURCE = 20
# A translation longer than this absolute ceiling is suspect whatever the
# ratio says, and shorter than 4x its source is suspect whatever the ceiling.
_RUNAWAY_ABSOLUTE = 80
_RUNAWAY_RATIO = 4


def _weighted_lower_median(ratios, weights):
    """Length-weighted lower median: the value at the half-weight point."""
    if not ratios:
        return None
    total = sum(weights)
    order = sorted(zip(ratios, weights))
    half = total / 2
    acc = 0
    for value, weight in order:
        acc += weight
        if acc >= half:
            return value
    return order[-1][0]


def find_runaway_lines(source_lines, translated_lines):
    """Return the first index whose translation dwarfs its source.

    SubtitleEdit runaway check: the batch's own expansion factor is the
    length-weighted lower median of ``len(out) / len(src)`` over the pairs
    with at least ``_RUNAWAY_MIN_SOURCE`` source characters — the median so
    one hallucinated line cannot inflate the bar for the rest of the batch.
    A line is flagged when it exceeds ``max(80, 4 * len(src) * expansion)``.
    None when the batch has no measurable pairs.
    """
    ratios = []
    weights = []
    for src, out in zip(source_lines, translated_lines):
        src_len = len(src or "")
        if src_len < _RUNAWAY_MIN_SOURCE or not out:
            continue
        ratios.append(len(out) / src_len)
        weights.append(src_len)
    expansion = _weighted_lower_median(ratios, weights)
    if expansion is None:
        return None
    for i, (src, out) in enumerate(zip(source_lines, translated_lines)):
        if not out:
            continue
        if len(out) > max(_RUNAWAY_ABSOLUTE, _RUNAWAY_RATIO * len(src or "") * expansion):
            return i
    return None
