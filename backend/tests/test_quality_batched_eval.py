"""translation_quality_mode="batched": one request per chunk, strict reply-shape
check, per-line fallback, and a visible "quality" phase while the pass runs.
"""

from __future__ import annotations

import pytest

from config import reload_settings
from db import close_db, init_db
from translation.llm_utils import build_evaluation_batch_prompt, parse_quality_scores


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """A database of our own, without disturbing the session's environment."""
    from app import create_app

    monkeypatch.setenv("SUBLARR_DB_PATH", str(tmp_path / "quality_batched.db"))
    monkeypatch.setenv("SUBLARR_LOG_LEVEL", "ERROR")
    reload_settings()
    app = create_app(testing=True)
    with app.app_context():
        init_db()
        yield app
    close_db()


@pytest.fixture()
def use_manager(monkeypatch):
    def _install(manager):
        import translation

        monkeypatch.setattr(translation, "get_translation_manager", lambda: manager)
        return manager

    return _install


def _use_mode(monkeypatch, mode, batch):
    import translator.quality

    monkeypatch.setattr(translator.quality, "_eval_mode_and_batch", lambda: (mode, batch))


def _evaluate(lines, translated, threshold=35, retries=1):
    from translator.quality import _evaluate_and_retry_lines

    return _evaluate_and_retry_lines(
        lines, translated, "en", "de", ["ollama"], None, threshold=threshold, max_retries=retries
    )


class _BatchManager:
    """Counts round trips; batch replies are [score]*len(pairs) or None."""

    def __init__(self, batch_scores=None, per_line_score=90, improved=None):
        self.batch_calls = 0
        self.eval_calls = 0
        self.translate_calls = 0
        self._batch_scores = batch_scores
        self._per_line = per_line_score
        self._improved = improved

    def evaluate_lines_quality(self, pairs, source_lang, target_lang, chain):
        self.batch_calls += 1
        if self._batch_scores is None:
            return None
        return self._batch_scores * len(pairs)

    def evaluate_line_quality(self, src, trans, source_lang, target_lang, chain):
        self.eval_calls += 1
        if self._improved is not None and trans == self._improved:
            return 95
        return self._per_line

    def translate_with_fallback(self, lines, source_lang, target_lang, chain, glossary):
        self.translate_calls += 1
        from translation.base import TranslationResult

        return TranslationResult(
            translated_lines=[self._improved or lines[0]], backend_name="stub", success=True
        )


def test_batch_parser_accepts_exact_count():
    assert parse_quality_scores("95\n80\n50", 3) == [95, 80, 50]
    assert parse_quality_scores("Here: 40 20", 2) == [40, 20]
    assert parse_quality_scores("120", 1) is None  # out-of-range reply rejected, not clamped


def test_batch_parser_refuses_misaligned_counts():
    assert parse_quality_scores("95\n80", 3) is None
    assert parse_quality_scores("95\n80\n50\n70", 3) is None
    assert parse_quality_scores("no numbers", 2) is None


def test_batch_prompt_numbers_every_pair():
    prompt = build_evaluation_batch_prompt([("a", "b"), ("c", "d")], "en", "de")
    assert "1. Original (en): a" in prompt
    assert "2. Original (en): c" in prompt
    assert "exactly 2 integers" in prompt


def test_mode_entry_defaults_and_clamps(monkeypatch):
    import db.config

    monkeypatch.setattr(
        db.config,
        "get_config_entry",
        lambda k: {"translation_quality_mode": "BATCHED ", "batch_size": "999"}.get(k),
    )
    from translator.quality import _eval_mode_and_batch

    assert _eval_mode_and_batch() == ("batched", 50)

    monkeypatch.setattr(db.config, "get_config_entry", lambda k: None)
    assert _eval_mode_and_batch() == ("per_line", 15)

    def _boom(_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db.config, "get_config_entry", _boom)
    assert _eval_mode_and_batch() == ("per_line", 15)


def test_default_mode_costs_one_request_per_line(_isolate_db, use_manager, monkeypatch):
    mgr = use_manager(_BatchManager())
    _use_mode(monkeypatch, "per_line", 15)
    final, scores = _evaluate(["a", "b", "c"], ["x", "y", "z"])
    assert mgr.batch_calls == 0
    assert mgr.eval_calls == 3
    assert scores == [90, 90, 90]
    assert final == ["x", "y", "z"]


def test_batched_mode_scores_chunks_in_one_request(_isolate_db, use_manager, monkeypatch):
    mgr = use_manager(_BatchManager(batch_scores=[70]))
    _use_mode(monkeypatch, "batched", 2)
    final, scores = _evaluate(["a", "b", "c"], ["x", "y", "z"])
    # chunk of 2 -> one batch request; the leftover line is scored per line
    assert mgr.batch_calls == 1
    assert mgr.eval_calls == 1
    assert scores == [70, 70, 90]
    assert final == ["x", "y", "z"]


def test_batched_mode_falls_back_per_line_on_misaligned_reply(
    _isolate_db, use_manager, monkeypatch
):
    mgr = use_manager(_BatchManager(batch_scores=None))  # reply does not parse
    _use_mode(monkeypatch, "batched", 2)
    final, scores = _evaluate(["a", "b", "c"], ["x", "y", "z"])
    assert mgr.batch_calls == 1  # the one chunked attempt that failed
    assert mgr.eval_calls == 3  # every line re-asked individually
    assert scores == [90, 90, 90]
    assert final == ["x", "y", "z"]


def test_batched_mode_retries_stay_per_line(_isolate_db, use_manager, monkeypatch):
    mgr = use_manager(_BatchManager(batch_scores=[20], improved="gut"))
    _use_mode(monkeypatch, "batched", 2)
    final, scores = _evaluate(["a", "b"], ["schlecht", "schlecht"], threshold=35, retries=1)
    assert mgr.translate_calls == 2  # one re-ask per low line
    assert final == ["gut", "gut"]
    assert scores == [95, 95]


def test_pass_marks_quality_phase_and_progress(_isolate_db, use_manager, monkeypatch):
    from translation.queue_state import (
        get_queue_state,
        reset_current_job_id,
        reset_for_tests,
        set_current_job_id,
    )

    reset_for_tests()
    queue = get_queue_state()
    queue.register_job(
        job_id="j1",
        file_path="/x/a.mkv",
        source_lang="en",
        target_lang="de",
        backend="openai_compat",
        total_lines=3,
    )
    queue.update_progress("j1", done=3)
    assert queue.active_snapshot()[0]["phase"] == "translating"
    assert queue.active_snapshot()[0]["progress"]["pct"] == 100.0

    use_manager(_BatchManager(batch_scores=[70]))
    _use_mode(monkeypatch, "batched", 2)
    token = set_current_job_id("j1")
    try:
        _evaluate(["a", "b", "c"], ["x", "y", "z"])
    finally:
        reset_current_job_id(token)

    snap = queue.active_snapshot()[0]
    assert snap["phase"] == "quality"
    assert snap["eval_done"] == 3
