"""Translation quality checking and validation."""

import logging

from services.scheduler.cancellation import abort_requested
from translator._helpers import ENGLISH_MARKER_WORDS
from translator.errors import TranslationAbortedError

logger = logging.getLogger(__name__)


def _memory_enabled():
    """Whether the translation memory is switched on for this install."""
    try:
        from config import get_settings

        return bool(getattr(get_settings(), "translation_memory_enabled", True))
    except Exception:  # noqa: BLE001 — never let a settings read stop a translation
        logger.debug("could not read translation_memory_enabled", exc_info=True)
        return False


def _remembered_scores(source_lang, target_lang, source_lines, translated_lines):
    """Per line: the score this pass already gave *this* text, or None.

    One query for the whole file — the point is to avoid buying a judgement
    twice, which a per-line database round trip would partly give back.

    A stored score counts only when the remembered translation is the one in
    hand. A score describes a translation, not a source line, so a line the
    model rendered differently this time has to be judged on its own.
    """
    if not _memory_enabled() or not source_lines:
        return [None] * len(source_lines)
    try:
        from db.translation import lookup_quality_scores

        remembered = lookup_quality_scores(source_lang, target_lang, list(source_lines))
    except Exception:  # noqa: BLE001 — the memory is an optimisation, never a gate
        logger.debug("translation memory lookup failed; scoring every line", exc_info=True)
        return [None] * len(source_lines)

    return [
        score if (score is not None and text == current) else None
        for (text, score), current in zip(remembered, translated_lines)
    ]


def _remember_score(source_lang, target_lang, source_text, translated_text, score):
    """Persist the pass's verdict on this exact translation."""
    if not _memory_enabled():
        return
    try:
        from db.translation import store_translation_cache

        store_translation_cache(
            source_lang, target_lang, source_text, translated_text, quality_score=score
        )
    except Exception:  # noqa: BLE001 — a memory write must not fail a translation
        logger.debug("could not record the quality score for a line", exc_info=True)


def _eval_mode_and_batch():
    """Read the evaluator mode for the quality pass.

    ``translation_quality_mode`` picks how the initial scoring is billed:
    ``"per_line"`` (default, one request per line — precise, slow) or
    ``"batched"`` (one request per chunk of ``batch_size`` lines — ~15x
    fewer requests, with a strict reply-shape check and per-line fallback).
    Retries stay per line in both modes. An unusable stored value falls back
    to the default behavior.

    Returns:
        (mode: str, batch: int)
    """
    try:
        from db.config import get_config_entry

        mode = (get_config_entry("translation_quality_mode") or "per_line").strip().lower()
        if mode not in ("per_line", "batched"):
            mode = "per_line"
        batch_val = get_config_entry("batch_size")
        batch = int(batch_val) if batch_val is not None else 15
        batch = max(1, min(50, batch))
        return mode, batch
    except Exception:
        return "per_line", 15


def _evaluate_and_retry_lines(
    source_lines,
    translated_lines,
    source_lang,
    target_lang,
    fallback_chain,
    glossary_entries,
    threshold,
    max_retries,
):
    """Evaluate per-line translation quality and retry low-quality lines.

    For each source/translated pair, calls the LLM evaluator to get a 0-100
    score. Lines scoring below threshold are re-translated (same fallback chain)
    up to max_retries times. The best-scoring translation is kept.

    Args:
        source_lines: Original source subtitle lines
        translated_lines: Initial translations (same length)
        source_lang: ISO 639-1 source language code
        target_lang: ISO 639-1 target language code
        fallback_chain: Backend names in priority order
        glossary_entries: Optional glossary for retries
        threshold: Minimum acceptable score (lines below get retried)
        max_retries: Maximum retry attempts per line

    Returns:
        (final_lines: list[str], scores: list[int])
        final_lines -- best translation for each line
        scores -- per-line quality scores (0-100)
    """
    from translation import get_translation_manager
    from translation.queue_state import current_job_id, get_queue_state

    manager = get_translation_manager()
    final_lines = list(translated_lines)
    scores = [0] * len(source_lines)
    remembered = _remembered_scores(source_lang, target_lang, source_lines, translated_lines)
    reused = 0

    # This pass runs after every batch is translated, so done_lines is already
    # at total: without a phase the UI reads 100% / 0s remaining for the whole
    # scoring pass while requests keep going (prod 2026-11-25).
    job_id = current_job_id()
    queue = get_queue_state() if job_id else None
    if queue is not None:
        queue.update_progress(job_id, phase="quality", eval_done=0)

    eval_mode, eval_batch = _eval_mode_and_batch()

    # A stored verdict that already passes needs no model call; the rest get
    # scored per line (default) or one request per chunk ("batched").
    pending = []
    for idx in range(len(source_lines)):
        if remembered[idx] is not None and remembered[idx] >= threshold:
            scores[idx] = remembered[idx]
            reused += 1
        else:
            pending.append(idx)

    scored: dict[int, int] = {}
    start = 0
    while start < len(pending):
        # One LLM round trip per line (per chunk when batched), plus up to two
        # more per weak line, all sequential — for a 600-line subtitle this
        # loop *is* the tick. Without a check here the scheduler's stop
        # request is only seen once the whole file is done: prod 2026-09-17
        # took 71 minutes to reach its next check point against a 900 s grace.
        if abort_requested():
            raise TranslationAbortedError(
                f"asked to stop after scoring {len(scored)} of {len(pending)} line(s); "
                "the batches themselves were written to the translation memory before "
                "this pass, so a re-run starts from them rather than from nothing"
            )
        group = pending[start : start + eval_batch]
        if eval_mode == "batched" and len(group) > 1:
            batch = manager.evaluate_lines_quality(
                [(source_lines[i], translated_lines[i]) for i in group],
                source_lang,
                target_lang,
                fallback_chain,
            )
            if batch is not None and len(batch) == len(group):
                scored.update(zip(group, batch))
                start += len(group)
                continue
            logger.info(
                "Batched quality eval unusable for %d line(s); falling back to per-line",
                len(group),
            )
        for i in group:
            if abort_requested():
                raise TranslationAbortedError(
                    f"asked to stop while scoring line {i}; "
                    "the batches themselves were written to the translation memory before "
                    "this pass, so a re-run starts from them rather than from nothing"
                )
            scored[i] = manager.evaluate_line_quality(
                source_lines[i], translated_lines[i], source_lang, target_lang, fallback_chain
            )
        start += len(group)

    # Retry order stays cue order; a fix is always a single-line re-ask plus
    # a single-line re-eval, so batching buys nothing on that path.
    processed = 0
    for idx in range(len(source_lines)):
        if abort_requested():
            raise TranslationAbortedError(
                f"asked to stop after scoring {processed} of {len(source_lines)} line(s); "
                "the batches themselves were written to the translation memory before "
                "this pass, so a re-run starts from them rather than from nothing"
            )
        src = source_lines[idx]
        trans = translated_lines[idx]

        if idx not in scored:
            # This exact translation already went through this pass AND
            # passed it. Asking the model to judge it a second time buys the
            # same answer. A remembered FAIL must NOT be reused: the retry
            # below would be skipped, the known-bad line shipped again on
            # every run, and _remember_score re-persisted it — the memory
            # poisoning loop this pass used to have.
            processed += 1
            if queue is not None:
                queue.update_progress(job_id, eval_done=processed)
            continue

        score = scored[idx]
        best_trans = trans
        best_score = score

        retry = 0
        while score < threshold and retry < max_retries:
            if abort_requested():
                raise TranslationAbortedError(
                    f"asked to stop while retrying line {idx}; "
                    "the batches themselves were written to the translation memory before "
                    "this pass, so a re-run starts from them rather than from nothing"
                )
            retry += 1
            logger.info(
                "Quality retry %d/%d for line %d (score=%d < threshold=%d): %r",
                retry,
                max_retries,
                idx,
                score,
                threshold,
                src[:60],
            )
            try:
                result = manager.translate_with_fallback(
                    [src], source_lang, target_lang, fallback_chain, glossary_entries
                )
                if result.success and result.translated_lines:
                    # A retry must clear the SAME content guards as a normal
                    # batch (manager._verify_batch: chat filler, wrong script,
                    # untranslated echo). Without this the retry path was the
                    # one hole in the guard: a chatty reply ("Sure! Here are
                    # the lines…") or an echoed source became ``best_trans``,
                    # entered the subtitle file, and was stored by
                    # _remember_score with a numeric score — after which the
                    # memory replays it forever as a vetted line.
                    from translator.manager import _verify_batch

                    try:
                        _verify_batch(
                            result,
                            1,
                            f"Quality retry (line {idx})",
                            target_lang=target_lang,
                            source_lines=[src],
                        )
                    except RuntimeError as guard_exc:
                        logger.info(
                            "Quality retry %d rejected for line %d: %s", retry, idx, guard_exc
                        )
                        break
                    # A retry that answers with whitespace is worse than the
                    # line in hand, whatever the evaluator says about the
                    # (empty) text — never let it become the best.
                    new_trans = result.translated_lines[0]
                    if not new_trans.strip():
                        break
                    new_score = manager.evaluate_line_quality(
                        src, new_trans, source_lang, target_lang, fallback_chain
                    )
                    if new_score > best_score:
                        best_trans = new_trans
                        best_score = new_score
                    score = new_score
                else:
                    break
            except TranslationAbortedError:
                # A stop request is not a retry failure. Re-raised explicitly
                # so a check added inside this try later cannot be turned into
                # a silent "break" by the handler below.
                raise
            except Exception as exc:
                logger.debug("Quality retry %d failed for line %d: %s", retry, idx, exc)
                break

        final_lines[idx] = best_trans
        scores[idx] = best_score
        # The pass has now judged this text. Writing it back is what makes the
        # skip above legitimate: the batch was cached before this pass ran, so
        # without this the memory would keep serving the unchecked line.
        _remember_score(source_lang, target_lang, src, best_trans, best_score)
        processed += 1
        if queue is not None:
            queue.update_progress(job_id, eval_done=processed)

    if reused:
        logger.info(
            "Quality: reused %d of %d stored verdict(s); %d line(s) scored",
            reused,
            len(source_lines),
            len(source_lines) - reused,
        )

    return final_lines, scores


def _compute_quality_stats(scores, threshold):
    """Compute aggregate quality metrics from per-line scores.

    Args:
        scores: List of per-line quality scores (0-100)
        threshold: Threshold used during evaluation

    Returns:
        Dict with avg_quality, min_quality, low_quality_lines keys.
        Returns empty dict when scores list is empty.
    """
    if not scores:
        return {}
    avg = round(sum(scores) / len(scores), 1)
    low = sum(1 for s in scores if s < threshold)
    return {
        "avg_quality": avg,
        "min_quality": min(scores),
        "low_quality_lines": low,
        "quality_threshold": threshold,
    }


def _write_quality_sidecar(subtitle_path, scores):
    """Write per-line quality scores to a JSON sidecar file.

    The sidecar file is named <subtitle_path>.quality.json and contains
    a JSON array of integer scores in the same order as the subtitle cues.
    Errors are logged but do not interrupt the translation pipeline.

    Args:
        subtitle_path: Absolute path to the translated subtitle file
        scores: Per-line quality scores (0-100) in cue order
    """
    if not scores:
        return
    import json as _json

    sidecar_path = subtitle_path + ".quality.json"
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            _json.dump(scores, f)
        logger.debug("Wrote quality sidecar: %s (%d scores)", sidecar_path, len(scores))
    except Exception as exc:
        logger.warning("Failed to write quality sidecar %s: %s", sidecar_path, exc)


def _check_translation_quality(original_texts, translated_texts, target_lang=None):
    """Check translation quality and return warnings.

    ``target_lang``: ISO code of the language being translated INTO. The
    English-marker heuristic must be skipped when the target IS English —
    en->en never happens, but ja->en, zh->en, de->en etc. legitimately
    produce English text, and the old unconditional check flagged every
    English-target translation as suspicious.

    Returns list of warning strings (empty if quality seems OK).
    """
    warnings = []

    identical = sum(1 for o, t in zip(original_texts, translated_texts) if o.strip() == t.strip())
    if identical > len(original_texts) * 0.5:
        warnings.append(
            f"{identical}/{len(original_texts)} lines identical to original (possibly untranslated)"
        )

    for i, (orig, trans) in enumerate(zip(original_texts, translated_texts)):
        if len(orig) > 5 and len(trans) > 0:
            ratio = len(trans) / len(orig)
            if ratio > 3.0 or ratio < 0.2:
                warnings.append(f"Line {i}: suspicious length ratio {ratio:.1f}x")
                break  # Only report first occurrence

    # Check for common English words in translation. Meaningless when the
    # target language is English itself.
    target_is_english = (target_lang or "").lower().split("-")[0].split("_")[0] == "en"
    if translated_texts and not target_is_english:
        sample = " ".join(translated_texts[:20]).lower().split()
        eng_count = sum(1 for w in sample if w in ENGLISH_MARKER_WORDS)
        if len(sample) > 10 and eng_count / len(sample) > 0.3:
            warnings.append(f"High English word ratio in translation ({eng_count}/{len(sample)})")

    return warnings


def validate_translation_output(original_texts, translated_texts, format="ass"):
    """Validate translation output for common issues.

    Returns (is_valid, errors) tuple.
    """
    errors = []
    if len(translated_texts) != len(original_texts):
        errors.append(f"Line count mismatch: {len(original_texts)} vs {len(translated_texts)}")
        return False, errors
    total_orig = sum(len(t) for t in original_texts)
    total_trans = sum(len(t) for t in translated_texts)
    if total_orig > 0 and total_trans > total_orig * 1.5:
        errors.append(f"Output too long: {total_trans / total_orig:.1f}x")
    empty = sum(1 for t in translated_texts if not t.strip())
    if empty > len(translated_texts) * 0.3:
        errors.append(f"Too many empty lines: {empty}/{len(translated_texts)}")
    return len(errors) == 0, errors
