"""Context-window pre-chunker for LLM translation batches.

Splits a full subtitle file into batches with surrounding lookback + lookahead
context. LLMs use this to resolve pronouns, maintain terminology consistency
across batch boundaries, and preserve narrative coherence — they see the
surrounding lines but translate only the batch.

Non-LLM backends (DeepL, Google, LibreTranslate) should skip context entirely
— the caller in TranslationManager is responsible for that conditional.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Musical notation glyphs used by lyric subtitles (ASS/Karaoke sign styles).
#: A line containing any of these is a lyric line, not dialogue.
MUSIC_SYMBOLS = "♩♪♫♬🎵🎶"


def has_music_symbols(text: str) -> bool:
    """Whether ``text`` contains a musical-notation glyph (lyric line)."""
    return any(symbol in text for symbol in MUSIC_SYMBOLS)


@dataclass(frozen=True)
class ContextChunk:
    """One batch of lines to translate, with surrounding context.

    Attributes:
        lookback: N lines BEFORE the batch, for context only (not translated).
        batch: the lines the LLM must translate.
        lookahead: N lines AFTER the batch, for context only.
        batch_start_index: index of batch[0] in the original `lines` list.
            Used by callers to reassemble the full translated file.
    """

    lookback: list[str]
    batch: list[str]
    lookahead: list[str]
    batch_start_index: int


def _lyric_boundary(lines: list[str], start: int, window_end: int, total: int) -> int:
    """Chunk end that stops on a lyric line instead of spanning one.

    Prefers the last music line inside the planned window (keeps chunks near
    `batch_size`); when the window has none, grows to the next music line so a
    batch never crosses lyrics; when no lyric line is ahead at all, the planned
    window stands and the chunking is the plain batch_size one.
    """
    last_in_window = -1
    for index in range(start, window_end):
        if has_music_symbols(lines[index]):
            last_in_window = index
    if last_in_window >= 0:
        return last_in_window + 1
    for index in range(window_end, total):
        if has_music_symbols(lines[index]):
            return index + 1
    return window_end


def build_chunks(
    lines: list[str],
    batch_size: int,
    lookback: int = 10,
    lookahead: int = 5,
    *,
    music_boundaries: bool = False,
) -> list[ContextChunk]:
    """Split a full subtitle file into ContextChunks.

    Args:
        lines: the full file as a list of subtitle lines.
        batch_size: max lines to translate per chunk (matches backend.max_batch_size).
        lookback: lines before each batch to include as context (clipped to available).
        lookahead: lines after each batch to include as context (clipped).
        music_boundaries: lyric-aware chunking. When True every chunk ENDS on a
            line containing a music glyph (see `has_music_symbols`), so no batch
            ever spans lyrics — dialogue and songs never mix in one request.
            The boundary line is the last line of the chunk and the next chunk
            starts immediately after it. `batch_size` becomes a target rather
            than a hard cap: a chunk shrinks to the last lyric line inside the
            window, or grows to the next one when the window has none (it may
            exceed `batch_size`, but never crosses a lyric). With no lyric line
            ahead, `batch_size` chunking applies unchanged.
            False (default) chunks exactly as before, ignoring music glyphs.

    Returns:
        List of ContextChunks covering every line exactly once in `batch`.
        Empty list if `lines` is empty.

    Raises:
        ValueError: batch_size < 1 or lookback < 0 or lookahead < 0.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    if lookback < 0:
        raise ValueError(f"lookback must be >= 0, got {lookback}")
    if lookahead < 0:
        raise ValueError(f"lookahead must be >= 0, got {lookahead}")

    if not lines:
        return []

    chunks: list[ContextChunk] = []
    total = len(lines)
    start = 0
    while start < total:
        end = min(start + batch_size, total)
        if music_boundaries:
            end = _lyric_boundary(lines, start, end, total)
        lb_start = max(0, start - lookback)
        la_end = min(total, end + lookahead)
        chunks.append(
            ContextChunk(
                lookback=lines[lb_start:start],
                batch=lines[start:end],
                lookahead=lines[end:la_end],
                batch_start_index=start,
            )
        )
        start = end
    return chunks
