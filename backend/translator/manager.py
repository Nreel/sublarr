"""Translation manager orchestration: glossary, cache, batching, fallback."""

import inspect
import logging
import sys
from types import SimpleNamespace

from services.scheduler.cancellation import abort_requested
from translation import get_translation_manager
from translation.context_windower import build_chunks
from translator._helpers import (
    _get_cache_config,
    _resolve_backend_for_context,
)
from translator.cache import _apply_translation_cache, _store_translations_in_cache
from translator.errors import TranslationAbortedError
from translator.output_guard import (
    find_chat_filler,
    find_duplicated_translation,
    find_echo_indices,
    find_malformed_value,
    find_runaway_lines,
    find_script_mismatch,
)

logger = logging.getLogger(__name__)


def _pkg():
    """Return the translator package module (for patchable symbol lookup)."""
    return sys.modules["translator"]


def _translate_with_manager(lines, source_lang, target_lang, arr_context=None, series_id=None):
    """Translate lines using TranslationManager with profile-based backend selection.

    Resolves the backend and fallback chain from the language profile associated
    with the arr_context, loads glossary entries if a series_id is provided,
    and delegates to TranslationManager.translate_with_fallback().

    Args:
        lines: List of subtitle text lines to translate
        source_lang: ISO 639-1 source language code
        target_lang: ISO 639-1 target language code
        arr_context: Optional dict with sonarr_series_id or radarr_movie_id
        series_id: Optional Sonarr series ID for glossary lookup

    Returns:
        tuple[list[str], TranslationResult]: Translated lines and result metadata

    Raises:
        RuntimeError: If all backends in the fallback chain fail
        ValueError: If source and target language are the same — a
            same-language "translation" is an LLM round-trip that degrades
            the subtitle and poisons the translation memory (prod
            2026-08-30). Callers must not request it; raising loudly here
            makes any future caller bug visible instead of destructive.
    """
    from config_language_data import normalize_language_code

    def _primary_subtag(raw: str) -> str:
        """Reduce a tag to the language itself, dropping any region or script.

        normalize_language_code is a table lookup and hands an unknown tag back
        unchanged, so ``en-US`` never equalled ``en`` and slipped past this
        guard (found 2026-09-03 by probing the deployed 1.14.0-rc.4). The
        table knows ``pt-br`` and a handful like it; everything else has to be
        cut here. The trade-off is deliberate: a script conversion such as
        zh-Hans → zh-Hant is refused too, because that is not what this
        pipeline does — it would be an LLM round-trip on an identical
        language, which is exactly what this guard exists to stop.
        """
        return normalize_language_code(raw or "").replace("_", "-").split("-")[0]

    _src_norm = _primary_subtag(source_lang)
    _tgt_norm = _primary_subtag(target_lang)
    if _src_norm and _src_norm == _tgt_norm:
        raise ValueError(f"refusing same-language translation ({source_lang} → {target_lang})")

    _backend_name, fallback_chain = _resolve_backend_for_context(arr_context, target_lang)

    glossary_entries = _load_glossary_entries(series_id, target_lang)

    # --- Translation memory cache lookup ---
    cache_enabled, similarity_threshold = _get_cache_config()

    if cache_enabled and lines:
        cached_results, uncached_indices, uncached_lines = _apply_translation_cache(
            lines, source_lang, target_lang, similarity_threshold
        )
        cache_hits = sum(1 for r in cached_results if r is not None)
        if cache_hits:
            logger.debug(
                "Translation memory: %d/%d lines from cache, %d need LLM",
                cache_hits,
                len(lines),
                len(uncached_lines),
            )
    else:
        cached_results = [None] * len(lines)
        uncached_indices = list(range(len(lines)))
        uncached_lines = list(lines)

    # If every line was served from cache, skip LLM entirely
    if not uncached_lines:
        from translation.base import TranslationResult

        synthetic = TranslationResult(
            success=True,
            translated_lines=cached_results,
            backend_name="translation_memory",
            error=None,
        )
        return cached_results, synthetic

    # Translate only the uncached lines via LLM, in batch_size chunks
    manager = get_translation_manager()
    _get_settings = _pkg().get_settings
    batch_size = getattr(_get_settings(), "batch_size", 15) or 15

    all_translated, result = _translate_in_batches(
        manager,
        uncached_lines,
        source_lang,
        target_lang,
        fallback_chain,
        glossary_entries,
        batch_size,
        cache_enabled=cache_enabled,
    )

    # Merge cached + freshly translated lines in original order
    output = list(cached_results)
    for out_idx, translated in zip(uncached_indices, all_translated):
        output[out_idx] = translated

    # No bulk write here any more. `_translate_in_batches` stores each batch
    # the moment it is verified, so a run that dies partway keeps what it
    # finished. Writing again here would store every line a second time.

    return output, result


def _load_glossary_entries(series_id, target_lang=None):
    """Load glossary entries (global + per-series) if glossary is enabled.

    Pending suggestions (``approved == 0``) are left out here, not later:
    DeepL and Google build native glossaries from these entries without
    looking at the flag, and before 2026-11 both paths here dropped it, so a
    pending suggestion was applied as if it had been accepted.

    Args:
        series_id: Optional Sonarr series ID for per-series glossary
        target_lang: Target language; entries written for another language
            are left out, entries without a language always apply

    Returns:
        list[dict] | None: Glossary entries or None if disabled/unavailable
    """
    _get_settings = _pkg().get_settings
    if not getattr(_get_settings(), "glossary_enabled", True):
        return None

    try:
        if series_id:
            from db.translation import get_merged_glossary_for_series

            entries = get_merged_glossary_for_series(series_id, target_lang)
        else:
            from db.translation import get_global_glossary

            entries = [
                {
                    "source_term": e["source_term"],
                    "target_term": e["target_term"],
                    "approved": e.get("approved", 1),
                }
                for e in get_global_glossary(target_lang)
            ]
        entries = [e for e in entries if e.get("approved", 1) != 0]
        if entries:
            max_terms = getattr(_get_settings(), "glossary_max_terms", 100)
            entries = entries[:max_terms]
            logger.debug("Loaded %d glossary entries (series %s)", len(entries), series_id)
            return entries
    except Exception as e:
        # Not fatal, but a translation without its glossary drifts on terms.
        logger.warning("Failed to load glossary: %s", e)

    return None


def _cache_batch(cache_enabled, source_lines, result, source_lang, target_lang):
    """Write one verified batch to the translation memory.

    The backend name comes off this batch's own result rather than the file's
    last one: with a fallback chain, batches in a single file can legitimately
    come from different backends, and the memory records which produced what.
    """
    if not cache_enabled:
        return
    _store_translations_in_cache(
        list(source_lines),
        list(result.translated_lines),
        source_lang,
        target_lang,
        backend=getattr(result, "backend_name", None),
    )


class BatchFailure(RuntimeError):  # noqa: N818 — name is SubtitleEdit's, callers branch on .kind
    """One batch came back unusable, and where it went wrong is known.

    ``bad_index`` is the 0-based line inside the batch that triggered the
    failure (None when the failure describes the batch as a whole). The
    splitting path cuts before it rather than halving, so a batch that dies
    on line 30 of 60 retries lines 1-29 as a whole instead of cutting the
    good prefix in half — SubtitleEdit's per-batch guards report an index,
    and halving throws away the lines that were already fine.

    ``kind`` is one of ``count``, ``filler``, ``script``, ``echo``,
    ``shift``, ``malformed``, ``runaway``. ``echo_indices`` lists every
    echoed line for ``kind="echo"``.
    """

    def __init__(self, message, *, kind="", bad_index=None, echo_indices=None):
        super().__init__(message)
        self.kind = kind
        self.bad_index = bad_index
        self.echo_indices = list(echo_indices or [])


class BatchSizeGovernor:
    """Shrink the batch after a failure, grow it back after clean ones.

    Ported from SubtitleEdit's BatchSizeGovernor. Semantics, verbatim:

      * ``limit(configured)`` — the working size once a cut has happened,
        otherwise the configured size.
      * ``on_cut(next)`` — take the smaller of the current working size and
        the size the split produced; success streak resets.
      * ``on_success()`` — after ``SuccessesBeforeGrowing`` (2) batches that
        came back clean, grow by half the working size. One clean batch is
        not evidence: a model that fails every third request must not be
        handed the full size back on a single good reply.

    A file that never fails never touches the governor: ``_working`` stays 0
    and every chunk keeps the configured size.
    """

    _SUCCESSES_BEFORE_GROWING = 2

    def __init__(self):
        self._working = 0
        self._successes = 0

    def limit(self, configured):
        return min(self._working, configured) if self._working > 0 else configured

    def on_cut(self, next_count):
        self._working = min(self._working, next_count) if self._working > 0 else next_count
        self._successes = 0

    def on_success(self):
        if self._working <= 0:
            return
        self._successes += 1
        if self._successes < self._SUCCESSES_BEFORE_GROWING:
            return
        self._working += max(1, self._working // 2)
        self._successes = 0


def _accepts_kwarg(fn, name):
    """Whether ``fn`` takes ``name`` (explicitly or through **kwargs).

    The backend call sites below forward SubtitleEdit's retry temperature,
    translation history and music-aware chunk boundaries. Those parameters
    land in ``translation/`` independently of this file, and test stubs of
    ``translate_with_fallback`` declare the older signature; probing keeps a
    forward-compatible call from raising TypeError on a stub.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


# SubtitleEdit RetryTemperatureBump: a batch that failed is asked once more,
# warmer, before the file is split. +0.3 on the request's own temperature,
# capped at 1.0 — a batch that only failed because the sampler was pinned
# cold comes back intact far more often than it comes back intact at halves.
_RETRY_BUMP = 0.3
_RETRY_TEMPERATURE_CAP = 1.0

# Batch sizes the governor is allowed to work with. Above 50 the model's
# line count drifts (the 882 count failures of 2026-07..08 came from batches
# this large); at 1 the chat-filler era wrote 1124 replies into the memory.
_MIN_BATCH_LINES = 1
_MAX_BATCH_LINES = 50
# Finished translations handed to the next batch as context (SubtitleEdit
# keeps the last translated lines rather than the last source lines).
_HISTORY_LINES = 12


def _retry_temperature(current=None):
    base = 0.2 if current is None else current
    return min(_RETRY_TEMPERATURE_CAP, base + _RETRY_BUMP)


def _verify_batch(result, expected_count, batch_label, target_lang=None, source_lines=None):
    """Verify one backend result before it may reach the file or the cache.

    Checks line count, rejects chat filler, rejects output in the wrong
    writing system, and — with ``source_lines`` — rejects a batch whose lines
    shifted, abstained, leaked the prompt's own JSON, ballooned, or came back
    as their own input. The count check alone cannot catch a conversational
    reply in a single-line batch (that reply is exactly one line — how 1124
    chat replies reached the prod translation memory during the batch_size=1
    era), and neither check catches the model echoing its input: a Chinese
    source sent through an "English → German" prompt comes back Chinese, one
    line per line. Between two Latin languages the script check is blind too.

    Ported gates (SubtitleEdit, 2026-11-24): TranslationShiftGuard for a
    translation shared by two different sources, the placeholder/prompt-leak
    value check, the runaway check on the batch's median expansion, and
    TranslationEchoGuard per line instead of a whole-batch share.

    Echo handling differs from the other gates on purpose: a lone identical
    line is kept (SubtitleEdit accepts it — names and calls read the same in
    both languages), a batch with only a few echoes is reported as
    ``kind="echo"`` without a bad index so the manager re-asks those lines
    individually, and a batch that came back mostly unchanged is reported
    with the first echo as the split point.

    Raises:
        BatchFailure: If the count is off, a line is filler, the script is
            wrong, a translation shifted or abstained, a line ballooned or the
            batch came back untranslated. Nothing is cached.
    """
    if len(result.translated_lines) != expected_count:
        raise BatchFailure(
            f"{batch_label} returned {len(result.translated_lines)} lines, "
            f"expected {expected_count}. Aborting to prevent cache pollution.",
            kind="count",
        )
    suspects = find_chat_filler(result.translated_lines)
    if suspects:
        idx, text = suspects[0]
        raise BatchFailure(
            f"{batch_label} returned chat filler instead of a translation "
            f"(line {idx + 1}: {text[:80]!r}). Aborting to prevent cache pollution.",
            kind="filler",
            bad_index=idx,
        )
    if target_lang:
        wrong_script = find_script_mismatch(result.translated_lines, target_lang)
        if wrong_script:
            raise BatchFailure(
                f"{batch_label} came back in the wrong script ({wrong_script}). "
                "Aborting to prevent cache pollution.",
                kind="script",
            )

    sources = (
        list(source_lines) if source_lines is not None else [None] * len(result.translated_lines)
    )

    shifted = find_duplicated_translation(sources, result.translated_lines)
    if shifted is not None:
        raise BatchFailure(
            f"{batch_label} gave two different source lines the same translation "
            f"(line {shifted + 1}). Aborting to prevent cache pollution.",
            kind="shift",
            bad_index=shifted,
        )

    for idx, out in enumerate(result.translated_lines):
        malformed = find_malformed_value(sources[idx], out)
        if malformed:
            raise BatchFailure(
                f"{batch_label} returned a malformed value — {malformed}. "
                "Aborting to prevent cache pollution.",
                kind="malformed",
                bad_index=idx,
            )

    runaway = find_runaway_lines(sources, result.translated_lines)
    if runaway is not None:
        raise BatchFailure(
            f"{batch_label} returned a runaway translation (line {runaway + 1}: "
            f"{result.translated_lines[runaway][:60]!r}). Aborting to prevent cache pollution.",
            kind="runaway",
            bad_index=runaway,
        )

    if source_lines is None:
        return

    echoes = find_echo_indices(source_lines, result.translated_lines)
    if not echoes:
        # A batch that only carries names and titles may come back entirely
        # unchanged and be correct; that is what the ordinary-word gate in
        # find_echo_indices is for.
        return

    if expected_count <= 1:
        logger.debug(
            "Batch %s kept line 1 identical to its source — a lone unchanged line is accepted",
            batch_label,
        )
        return

    allowed = max(1, expected_count // 5)
    if len(echoes) <= allowed:
        raise BatchFailure(
            f"{batch_label} came back untranslated on {len(echoes)} of "
            f"{expected_count} lines (few echoes). Aborting to prevent cache pollution.",
            kind="echo",
            echo_indices=echoes,
        )
    raise BatchFailure(
        f"{batch_label} came back untranslated ({len(echoes)} of "
        f"{expected_count} lines unchanged). Aborting to prevent cache pollution.",
        kind="echo",
        bad_index=echoes[0],
        echo_indices=echoes,
    )


def _translate_batch_or_split(
    manager,
    batch_lines,
    source_lang,
    target_lang,
    fallback_chain,
    glossary_entries,
    cache_enabled,
    label,
    *,
    lookback=None,
    lookahead=None,
    history=None,
    governor=None,
):
    """Translate one batch; on failure cut it and translate the pieces.

    A batch the backend cannot deliver used to end the file. The failures are
    deterministic, so the next run dies at the same place and the episode never
    completes: production logged 882 line-count failures between 2026-07-10 and
    2026-08-24, the same error texts recurring on nine of the last ten days.

    Splitting is not a repair, it removes the opportunity: two source events
    carrying one sentence can only be merged into one output line while they
    sit in the same request. It also costs context, so it happens only after
    two cheaper steps, both ported from SubtitleEdit:

      * RetryTemperatureBump (+0.3, cap 1.0) — the whole batch is asked once
        more, warmer. A batch that failed because the sampler was pinned cold
        comes back intact far more often than it comes back intact in halves.
      * Echo re-ask — a batch with only a few echoed lines (``kind="echo"``
        and no bad index) is not a broken batch. Each echoed line is asked
        again on its own, context-free, one attempt; what comes back is kept
        whatever it is, including an unchanged copy, because a name or a
        call-out legitimately reads the same in both languages.

    Where the split cuts is the bad index, not the middle: lines before the
    offending line were already delivered correctly, and halving pays for them
    twice. ``kind="shift"`` is the exception — a shifted batch is wrong from
    wherever the copy started, so the cut is capped at half the batch.
    ``governor`` records the size of the piece tried next; see
    :class:`BatchSizeGovernor`.

    A single line that still fails raises, as before — a file translated short
    would be worse than one that failed loudly. ``_verify_batch`` screens every
    result on the way back however small the batch got: the batch_size=1 era
    put 1124 chat-filler lines into the production translation memory.

    Returns:
        tuple[list[str], TranslationResult]: translated lines and the result
            of the last successful (sub-)batch.
    """

    def _ask(lines, *, retry_temperature=None, context=True):
        kwargs = {}
        if context:
            kwargs["lookback"] = lookback
            kwargs["lookahead"] = lookahead
            if history and _accepts_kwarg(manager.translate_with_fallback, "history"):
                kwargs["history"] = history
        if retry_temperature is not None and _accepts_kwarg(
            manager.translate_with_fallback, "retry_temperature"
        ):
            kwargs["retry_temperature"] = retry_temperature
        try:
            return manager.translate_with_fallback(
                lines,
                source_lang,
                target_lang,
                fallback_chain,
                glossary_entries,
                **kwargs,
            )
        except TypeError:
            # A wrapper that takes **kwargs and forwards to a backend which
            # accepts none of the extras: drop the extras and ask plainly. The
            # batch still translates, only without history. A temperature the
            # backend cannot take is re-raised — the caller skips the bump
            # rather than asking the same batch twice.
            if retry_temperature is not None or not any(
                k not in ("lookback", "lookahead") for k in kwargs
            ):
                raise
            plain = {k: v for k, v in kwargs.items() if k in ("lookback", "lookahead")}
            return manager.translate_with_fallback(
                lines,
                source_lang,
                target_lang,
                fallback_chain,
                glossary_entries,
                **plain,
            )

    result = _ask(batch_lines)
    failure = None
    if not result.success:
        failure = result.error
    else:
        try:
            _verify_batch(
                result,
                len(batch_lines),
                f"Batch {label}",
                target_lang=target_lang,
                source_lines=batch_lines,
            )
        except RuntimeError as exc:
            # BatchFailure carries the index; a plain RuntimeError (an older
            # or patched verifier) carries none and halves the batch.
            failure = exc

    if failure is None:
        # Cached here, not after the loop: everything up to this point is
        # verified and paid for, and a later failure must not take it.
        _cache_batch(cache_enabled, batch_lines, result, source_lang, target_lang)
        return list(result.translated_lines), result

    if len(batch_lines) <= 1:
        raise RuntimeError(f"Translation failed on batch {label}: {failure}")

    # RetryTemperatureBump, before anything is split: one warmer request for
    # the intact batch costs less than the tree of requests a split creates.
    if _accepts_kwarg(manager.translate_with_fallback, "retry_temperature"):
        try:
            bumped = _ask(batch_lines, retry_temperature=_retry_temperature())
        except TypeError:
            # A wrapper that takes **kwargs and forwards to a backend which
            # has no temperature cannot be warmed; the split is the only
            # route left, so the bump is dropped rather than failing the file.
            bumped = None
        if bumped is not None and bumped.success:
            try:
                _verify_batch(
                    bumped,
                    len(batch_lines),
                    f"Batch {label} (warmer retry)",
                    target_lang=target_lang,
                    source_lines=batch_lines,
                )
            except RuntimeError as exc:
                failure = exc
            else:
                logger.info(
                    "Batch %s came back intact on the warmer retry (temperature %.1f)",
                    label,
                    _retry_temperature(),
                )
                _cache_batch(cache_enabled, batch_lines, bumped, source_lang, target_lang)
                return list(bumped.translated_lines), bumped

    # Few echoes: the batch is good except for a handful of unchanged lines.
    # Re-ask them individually and keep whatever comes back.
    if isinstance(failure, BatchFailure) and failure.kind == "echo" and failure.echo_indices:
        if failure.bad_index is None:
            retranslated = list(result.translated_lines)
            reask_failed = None
            for idx in failure.echo_indices:
                single = _ask([batch_lines[idx]], context=False)
                if not single.success or len(single.translated_lines or []) != 1:
                    reask_failed = single.error or "re-ask returned no single line"
                    break
                retranslated[idx] = single.translated_lines[0]
            if reask_failed is None:
                logger.info(
                    "Batch %s: %d echoed line(s) re-asked individually, kept as returned",
                    label,
                    len(failure.echo_indices),
                )
                _cache_batch(
                    cache_enabled,
                    batch_lines,
                    SimpleNamespace(
                        success=True,
                        translated_lines=retranslated,
                        backend_name=getattr(result, "backend_name", None),
                        error=None,
                    ),
                    source_lang,
                    target_lang,
                )
                return retranslated, result
            failure = reask_failed

    bad_index = getattr(failure, "bad_index", None)
    kind = getattr(failure, "kind", "")
    if bad_index is None:
        cut = len(batch_lines) // 2
    elif bad_index > 1:
        cut = bad_index
    else:
        cut = 1
    if kind == "shift":
        cut = min(cut, len(batch_lines) // 2)
    if governor is not None:
        governor.on_cut(cut)

    first, second = batch_lines[:cut], batch_lines[cut:]
    logger.warning(
        "Batch %s failed (%s) — retrying as %d + %d lines",
        label,
        failure,
        len(first),
        len(second),
    )

    # A split subdivides one chunk into a whole tree of requests, and the
    # loop's own stop check only runs between chunks. Without this one, a
    # batch halving its way down runs on past a stop request for the length of
    # that tree — the delay behind 43 of the 61 abandoned runs in the 30 days
    # to 2026-08-22. Whatever the halves already finished is cached.
    if abort_requested():
        raise TranslationAbortedError(
            f"asked to stop while splitting batch {label}; "
            "the finished batches are cached and the next attempt resumes from them"
        )

    # Each piece gets the other as context, so splitting costs as little
    # coherence as it can. LLM backends that ignore context are unaffected.
    first_lines, _first_result = _translate_batch_or_split(
        manager,
        first,
        source_lang,
        target_lang,
        fallback_chain,
        glossary_entries,
        cache_enabled,
        f"{label}a",
        lookback=lookback,
        lookahead=second or None,
        history=history,
        governor=governor,
    )
    second_lines, second_result = _translate_batch_or_split(
        manager,
        second,
        source_lang,
        target_lang,
        fallback_chain,
        glossary_entries,
        cache_enabled,
        f"{label}b",
        lookback=first or None,
        lookahead=lookahead,
        history=history,
        governor=governor,
    )
    return first_lines + second_lines, second_result


def _clamp_batch_size(n):
    """Keep a batch size inside the range the governor works in (1..50)."""
    return max(_MIN_BATCH_LINES, min(_MAX_BATCH_LINES, int(n)))


def _translation_history(sources, translated, limit=_HISTORY_LINES):
    """Finished (source, translation) pairs the next batch can read as context.

    Newest ``limit`` pairs, deduplicated by source — a line repeated in the
    file should appear once, as its latest translation — returned oldest
    first so the prompt reads chronologically. SubtitleEdit hands the last
    translated lines to each batch for names and register; a raw lookback of
    source lines cannot do that, because the model sees the words it is being
    asked to translate, not what they became.
    """
    pairs = []
    seen = set()
    for src, out in zip(reversed(list(sources)), reversed(list(translated))):
        if src in seen:
            continue
        seen.add(src)
        pairs.append((src, out))
        if len(pairs) >= limit:
            break
    pairs.reverse()
    return pairs


def _translate_in_batches(
    manager,
    lines,
    source_lang,
    target_lang,
    fallback_chain,
    glossary_entries,
    batch_size,
    cache_enabled=True,
):
    """Translate lines via LLM, chunking into batches if needed.

    Each batch is written to the translation memory as soon as it comes back
    verified, rather than the whole file being written once at the end. A run
    that stops partway — a line-count mismatch, a container restart, a
    scheduler timeout — then keeps the batches it finished, and the next
    attempt pays only for the remainder. The memory is the resume mechanism;
    there is no progress column and no partial file on disk.

    Prod 2026-08-16: 176 failed translation jobs against 160 successful in 24
    hours, failures observed as deep as batch 150, every one of them
    discarding everything before it.

    Each chunk is handed the finished translations before it
    (:func:`_translation_history`) and the file's :class:`BatchSizeGovernor`,
    so a batch that failed shrinks the pieces tried next and two clean batches
    grow them back (SubtitleEdit BatchSizeGovernor / RetryTemperatureBump=0.3).

    Args:
        manager: TranslationManager instance
        lines: Lines to translate (uncached subset)
        source_lang: Source language code
        target_lang: Target language code
        fallback_chain: List of backend names to try in order
        glossary_entries: Optional glossary entries for translation
        batch_size: Maximum lines per LLM call, clamped to 1..50 by the
            governor
        cache_enabled: Whether to write finished batches to the translation
            memory. The caller has already resolved this; passing it avoids a
            second config read per file.

    Returns:
        tuple[list[str], TranslationResult]: All translated lines and last result
    """
    # Report the real work to the in-memory queue tracker (registered by
    # services.translation_jobs.run_job). Without this the active view shows
    # backend="" and 0/0 forever, since cache hits never reach a backend and
    # nothing else feeds QueueState.
    from translation.queue_state import current_job_id, get_queue_state

    job_id = current_job_id()
    if job_id and fallback_chain:
        get_queue_state().update_progress(job_id, total_lines=len(lines), backend=fallback_chain[0])

    # SubtitleEdit BatchSizeGovernor: the configured size is the ceiling, a
    # failed batch cuts it, two clean batches grow it back by half. Clamp the
    # whole range to 1..50 — the model's line count drifts above that, and a
    # batch of 1 is where the chat-filler era started, so neither end is a
    # size worth handing to a backend unasked.
    governor = BatchSizeGovernor()
    effective_size = _clamp_batch_size(governor.limit(batch_size))

    if len(lines) <= effective_size:
        # Single batch path: no surrounding lines to provide as context.
        return _translate_batch_or_split(
            manager,
            lines,
            source_lang,
            target_lang,
            fallback_chain,
            glossary_entries,
            cache_enabled,
            "1",
            governor=governor,
        )

    # Multi-batch path: pre-chunk the file with lookback/lookahead context so
    # LLM backends can resolve pronouns and keep terminology consistent across
    # batch boundaries. See translation.context_windower.build_chunks.
    _get_settings = _pkg().get_settings
    settings = _get_settings()
    if getattr(settings, "translation_context_enabled", True):
        lookback_n = getattr(settings, "translation_context_lookback_lines", 10)
        lookahead_n = getattr(settings, "translation_context_lookahead_lines", 5)
    else:
        lookback_n = 0
        lookahead_n = 0

    chunk_kwargs = (
        {"music_boundaries": True} if _accepts_kwarg(build_chunks, "music_boundaries") else {}
    )
    chunks = build_chunks(
        lines,
        batch_size=effective_size,
        lookback=lookback_n,
        lookahead=lookahead_n,
        **chunk_kwargs,
    )

    logger.debug(
        "Translating %d lines in %d chunks (batch_size=%d, lookback=%d, lookahead=%d)",
        len(lines),
        len(chunks),
        effective_size,
        lookback_n,
        lookahead_n,
    )

    all_translated: list[str] = []
    last_result = None

    for i, chunk in enumerate(chunks):
        # The batch boundary is this job's only honest stopping point. The
        # drain worker checks between queue items, but one item is a whole
        # translation — prod measured those at ~16 minutes against a 900s
        # grace, which is why 43 of 61 abandoned runs in the 30 days
        # to 2026-08-22 were subtitle_automation. Everything above this line is
        # already cached, so stopping here costs the remainder, not the file.
        if abort_requested():
            raise TranslationAbortedError(
                f"asked to stop after {i} of {len(chunks)} batches; "
                "the finished batches are cached and the next attempt resumes from them"
            )
        chunk_lines, chunk_result = _translate_batch_or_split(
            manager,
            chunk.batch,
            source_lang,
            target_lang,
            fallback_chain,
            glossary_entries,
            cache_enabled,
            str(i + 1),
            # Empty list -> None so LLM prompt assembly skips context sections
            # entirely for the first (no lookback) and last (no lookahead) chunks.
            lookback=chunk.lookback or None,
            lookahead=chunk.lookahead or None,
            # What the batches before this one produced, so names and register
            # carry across the boundary instead of being re-invented.
            history=_translation_history(lines[: len(all_translated)], all_translated),
            governor=governor,
        )
        all_translated.extend(chunk_lines)
        last_result = chunk_result
        governor.on_success()
        if job_id:
            get_queue_state().update_progress(
                job_id,
                done=len(all_translated),
                backend=chunk_result.backend_name,
            )

    return all_translated, last_result
