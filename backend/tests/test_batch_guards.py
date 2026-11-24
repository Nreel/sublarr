"""Batch guards ported from SubtitleEdit, and what the manager does with them.

SubtitleEdit's per-batch guards report an index, not a verdict on the whole
batch: TranslationEchoGuard decides per line whether the line was worth
translating at all, TranslationShiftGuard catches two sources sharing one
translation, the value check catches an abstained ("...") or JSON-leaked line,
and the runaway check compares a line against the batch's own median
expansion. The manager acts on the index — it cuts before the bad line, re-asks
a handful of echoed lines on their own, and shrinks the size it tries next
(BatchSizeGovernor). Before 2026-11-24 every one of these killed the batch and
halved it, paying twice for the lines that had already come back right.
"""

from __future__ import annotations

import pytest

from translation.base import TranslationResult
from translator.manager import (
    BatchFailure,
    BatchSizeGovernor,
    _translate_batch_or_split,
    _translate_in_batches,
    _translation_history,
    _verify_batch,
)
from translator.output_guard import (
    find_duplicated_translation,
    find_echo_indices,
    find_malformed_value,
    find_runaway_lines,
    needs_translation,
)

# Lines long enough to clear the echo gate (>=3 words, >=10 letters, >=3
# distinct ordinary words) and long enough to measure an expansion ratio.
LONG_LINES = [
    "The quick brown fox jumps over the fence",
    "Nobody inside the house heard the engine start",
    "She kept the keys under the third flower pot",
    "The neighbour's dog barks at every passing car",
    "We should call the landlord about the leaking roof",
    "He wrote the address on the back of the ticket",
]


def _result(lines, success=True, error=None):
    return TranslationResult(
        success=success, translated_lines=list(lines), backend_name="fake", error=error
    )


@pytest.fixture
def no_cache(monkeypatch):
    """The memory is not what these tests are about; swallow the writes."""
    import translator.manager as mod

    cached: list[list[str]] = []
    monkeypatch.setattr(
        mod, "_store_translations_in_cache", lambda src, out, *a, **k: cached.append(list(out))
    )
    return cached


@pytest.fixture
def no_context(monkeypatch):
    from config import get_settings

    monkeypatch.setattr(get_settings(), "translation_context_enabled", False, raising=False)


class TestNeedsTranslation:
    def test_a_normal_sentence_qualifies(self):
        assert needs_translation("The quick brown fox jumps over the fence")

    def test_a_short_line_does_not(self):
        assert not needs_translation("Papa!")
        assert not needs_translation("")

    def test_a_spaceless_script_qualifies_on_letters_alone(self):
        assert needs_translation("私は 今日 公園へ 行きます")
        assert needs_translation("你好今天天气很好")
        assert needs_translation("안녕하세요반갑습니다")

    def test_markup_does_not_count_as_content(self):
        assert not needs_translation("<i>{\\i1}</i>")


class TestFindEchoIndices:
    def test_an_unchanged_qualifying_line_is_an_echo(self):
        out = [f"Übersetzung {i + 1} der zeile" for i in range(len(LONG_LINES))]
        out[0] = LONG_LINES[0]
        assert find_echo_indices(LONG_LINES, out) == [0]

    def test_case_and_line_breaks_still_count_as_an_echo(self):
        source = LONG_LINES[0]
        echo = source.upper().replace(" ", "\n")
        assert find_echo_indices([source], [echo]) == [0]

    def test_a_line_of_names_is_not_an_echo(self):
        # Capital-initial words that are not all-caps are names: a batch of
        # them legitimately reads the same in both languages.
        names = ["John Peter Mary Alexandra Elizabeth"]
        assert find_echo_indices(names, list(names)) == []

    def test_an_all_caps_line_is_an_echo(self):
        shout = ["TURN AROUND RIGHT NOW"]
        assert find_echo_indices(shout, list(shout)) == [0]

    def test_mismatched_line_counts_are_not_compared(self):
        # A merged or split block is a line-count problem, not an echo.
        assert find_echo_indices(LONG_LINES[:3], LONG_LINES[:2]) == []


class TestFindDuplicatedTranslation:
    def test_two_sources_one_translation_is_a_shift(self):
        sources = LONG_LINES[:3]
        out = [
            "Identical output line for both",
            "Identical output line for both",
            "Third answer line",
        ]
        assert find_duplicated_translation(sources, out) == 1

    def test_the_same_source_twice_is_not_a_shift(self):
        sources = [LONG_LINES[0], LONG_LINES[0]]
        out = ["Ein und derselbe Satz", "Ein und derselbe Satz"]
        assert find_duplicated_translation(sources, out) is None

    def test_start_index_skips_the_first_line(self):
        sources = [LONG_LINES[0], LONG_LINES[1]]
        out = ["Ein Satz", "Ein Satz"]
        assert find_duplicated_translation(sources, out, start_index=2) is None

    def test_empty_output_is_not_gated(self):
        assert find_duplicated_translation(LONG_LINES[:2], ["", ""]) is None


class TestFindMalformedValue:
    @pytest.mark.parametrize("placeholder", ["...", "…", "-", "[]"])
    def test_an_abstained_line_is_a_placeholder(self, placeholder):
        assert find_malformed_value("A real source line here", placeholder)

    def test_a_placeholder_for_an_empty_source_is_quiet(self):
        assert find_malformed_value("", "...") is None

    def test_a_prompt_example_is_a_leak(self):
        assert find_malformed_value("A real source line", "<translation of line 3>")

    @pytest.mark.parametrize(
        "leak",
        ['{"1":"ok", "2":"Hello"}', 'Hello"}', "a }]}", "Hello”}", "He said “ok”}"],
    )
    def test_json_structure_is_a_leak(self, leak):
        assert find_malformed_value("A real source line", leak)

    def test_a_normal_translation_is_accepted(self):
        assert find_malformed_value("A real source line", "Eine echte Quellzeile.") is None


class TestFindRunawayLines:
    def test_the_median_expansion_sets_the_bar_not_the_outlier(self):
        sources = ["A" * 20, "B" * 30, "C" * 20]
        out = ["a" * 24, "b" * 36, "c" * 300]
        assert find_runaway_lines(sources, out) == 2

    def test_a_batch_that_expands_uniformly_is_not_flagged(self):
        sources = ["A" * 20, "B" * 30, "C" * 25]
        out = ["a" * 26, "b" * 39, "c" * 33]
        assert find_runaway_lines(sources, out) is None

    def test_short_sources_are_not_measurable(self):
        assert find_runaway_lines(["hi", "yo"], ["hallo", "yo"]) is None

    def test_the_absolute_ceiling_catches_a_line_over_80_characters(self):
        # One pair cannot set its own bar (the median is that pair's ratio),
        # so the batch needs a normal pair to measure expansion against.
        sources = ["A" * 20, "B" * 20]
        out = ["a" * 24, "b" * 120]
        assert find_runaway_lines(sources, out) == 1


class TestVerifyBatch:
    def _fail(self, lines, expected, sources=None, **kwargs):
        with pytest.raises(BatchFailure) as excinfo:
            _verify_batch(_result(lines), expected, "Batch 1", source_lines=sources, **kwargs)
        return excinfo.value

    def test_a_count_mismatch_reports_the_count_kind(self):
        failure = self._fail(["one", "two"], 3)
        assert failure.kind == "count"
        assert failure.bad_index is None

    def test_a_filler_line_reports_its_index(self):
        failure = self._fail(["Hallo.", "Okay, please provide the subtitle lines."], 2)
        assert failure.kind == "filler"
        assert failure.bad_index == 1

    def test_batch_failure_is_a_runtime_error(self):
        """Callers that catch RuntimeError keep working."""
        assert issubclass(BatchFailure, RuntimeError)

    def test_a_shift_reports_its_index(self):
        failure = self._fail(["Same line here", "Same line here", "Third"], 3, LONG_LINES[:3])
        assert failure.kind == "shift"
        assert failure.bad_index == 1

    def test_a_placeholder_reports_its_index(self):
        failure = self._fail(["Ok", "...", "Fine"], 3, ["Line one", "Line two here", "Line three"])
        assert failure.kind == "malformed"
        assert failure.bad_index == 1

    def test_a_runaway_reports_its_index(self):
        sources = ["A" * 20, "B" * 30, "C" * 20]
        failure = self._fail(["a" * 24, "b" * 36, "c" * 300], 3, sources)
        assert failure.kind == "runaway"
        assert failure.bad_index == 2

    def test_a_lone_identical_line_is_accepted(self):
        line = LONG_LINES[0]
        _verify_batch(_result([line]), 1, "Batch 1", source_lines=[line])

    def test_a_few_echoes_report_indices_without_a_bad_index(self):
        out = [f"Übersetzung {i + 1} der zeile" for i in range(len(LONG_LINES))]
        out[0] = LONG_LINES[0]
        failure = self._fail(out, len(LONG_LINES), LONG_LINES)
        assert failure.kind == "echo"
        assert failure.bad_index is None
        assert failure.echo_indices == [0]

    def test_a_batch_mostly_echoed_reports_the_first_echo(self):
        out = list(LONG_LINES)
        out[1] = "Keine Person im Haus hat den Motor starten hören"
        failure = self._fail(out, len(LONG_LINES), LONG_LINES)
        assert failure.kind == "echo"
        assert failure.bad_index == 0
        assert failure.echo_indices == [0, 2, 3, 4, 5]
        assert "untranslated" in str(failure)


class _Stub:
    """Minimal backend: records every request and answers from ``respond``.

    Declares only the pre-2026-11 signature, so the manager's probes for
    ``retry_temperature``/``history`` come back False and these tests stay
    about the split, not about parameter forwarding.
    """

    def __init__(self, respond=None):
        self.requests: list[list[str]] = []
        self.respond = respond

    def translate_with_fallback(
        self,
        lines,
        source_lang,
        target_lang,
        fallback_chain,
        glossary_entries=None,
        *,
        lookback=None,
        lookahead=None,
    ):
        self.requests.append(list(lines))
        if self.respond is not None:
            return self.respond(list(lines), len(self.requests))
        return _result([f"T_{line}" for line in lines])


def _translated(lines, _n=None):
    return _result([f"T_{line}" for line in lines])


class TestFewEchoes:
    def test_a_few_echoed_lines_are_re_asked_and_kept(self, no_cache):
        """No split, one single-line request, the batch is cached as returned."""

        def respond(lines, n):
            if n == 1:
                return _result([lines[0]] + [f"T_{line}" for line in lines[1:]])
            return _translated(lines)

        stub = _Stub(respond=respond)
        lines, result = _translate_batch_or_split(
            stub, LONG_LINES[:4], "de", "en", ["fake"], None, True, "1"
        )
        assert stub.requests == [LONG_LINES[:4], LONG_LINES[:1]]
        assert lines == [f"T_{line}" for line in LONG_LINES[:4]]
        assert result.success
        assert no_cache == [[f"T_{line}" for line in LONG_LINES[:4]]]

    def test_a_re_ask_that_keeps_the_line_is_still_accepted(self, no_cache):
        """A name or call-out legitimately reads the same; the copy is kept."""

        def respond(lines, n):
            if len(lines) == 1:
                return _result(list(lines))
            return _result([lines[0]] + [f"T_{line}" for line in lines[1:]])

        stub = _Stub(respond=respond)
        lines, _ = _translate_batch_or_split(
            stub, LONG_LINES[:3], "en", "de", ["fake"], None, False, "1"
        )
        assert lines == [LONG_LINES[0]] + [f"T_{line}" for line in LONG_LINES[1:3]]
        assert stub.requests == [LONG_LINES[:3], LONG_LINES[:1]]

    def test_a_hard_re_ask_failure_falls_through_to_the_split(self, no_cache):
        def respond(lines, n):
            if len(lines) == 1:
                return _result([], success=False, error="backend went away")
            if n == 1:
                return _result([lines[0]] + [f"T_{line}" for line in lines[1:]])
            return _translated(lines)

        stub = _Stub(respond=respond)
        lines, _ = _translate_batch_or_split(
            stub, LONG_LINES[:4], "de", "en", ["fake"], None, False, "1"
        )
        # The re-ask error carries no index, so the batch halves; each half is
        # translated by the stub's later requests.
        assert [len(r) for r in stub.requests] == [4, 1, 2, 2]
        assert all(line.startswith("T_") for line in lines)


class TestSplitAtBadIndex:
    def test_the_cut_is_before_the_bad_line(self, no_cache):
        """Halving would cut the good prefix in half; the index cuts before it."""

        def respond(lines, n):
            if n == 1:
                return _result(
                    [
                        *[f"T_{line}" for line in lines[:3]],
                        "...",
                        *[f"T_{line}" for line in lines[4:]],
                    ]
                )
            return _translated(lines)

        stub = _Stub(respond=respond)
        lines, _ = _translate_batch_or_split(
            stub, LONG_LINES[:6], "de", "en", ["fake"], None, False, "1"
        )
        assert [len(r) for r in stub.requests] == [6, 3, 3]
        assert lines == [f"T_{line}" for line in LONG_LINES[:6]]

    def test_a_shift_is_capped_at_half_the_batch(self, no_cache):
        """A shifted batch is wrong wherever the copy started, so cutting at
        the index alone (here index 5) would leave a wrong 5-line prefix."""
        stub = _Stub(
            respond=lambda lines, n: (
                _result(
                    [
                        "Satz eins hier drin",
                        "Satz zwei hier drin",
                        "Satz drei hier drin",
                        "Satz vier hier drin",
                        "Satz fünf hier drin",
                        "Satz eins hier drin",
                    ]
                )
                if n == 1
                else _translated(lines)
            )
        )
        lines, _ = _translate_batch_or_split(
            stub, LONG_LINES[:6], "de", "en", ["fake"], None, False, "1"
        )
        assert [len(r) for r in stub.requests[:3]] == [6, 3, 3]
        assert len(lines) == 6

    def test_a_backend_error_without_an_index_still_halves(self, no_cache):
        stub = _Stub(
            respond=lambda lines, n: (
                _result([], success=False, error="connection reset")
                if n == 1
                else _translated(lines)
            )
        )
        lines, _ = _translate_batch_or_split(
            stub, LONG_LINES[:6], "de", "en", ["fake"], None, False, "1"
        )
        assert [len(r) for r in stub.requests[:3]] == [6, 3, 3]
        assert lines == [f"T_{line}" for line in LONG_LINES[:6]]

    def test_a_warmer_retry_before_the_split(self, no_cache):
        """SubtitleEdit RetryTemperatureBump: one warmer request for the whole
        batch costs less than the request tree a split creates."""

        class _WarmerStub:
            def __init__(self):
                self.requests: list[list[str]] = []
                self.temperatures: list[float | None] = []

            def translate_with_fallback(
                self,
                lines,
                source_lang,
                target_lang,
                fallback_chain,
                glossary_entries=None,
                *,
                lookback=None,
                lookahead=None,
                retry_temperature=None,
            ):
                self.requests.append(list(lines))
                self.temperatures.append(retry_temperature)
                if retry_temperature is None:
                    return _result([], success=False, error="cold sampler")
                return _result([f"T_{line}" for line in lines])

        stub = _WarmerStub()
        lines, _ = _translate_batch_or_split(
            stub, LONG_LINES[:6], "de", "en", ["fake"], None, True, "1"
        )
        assert [len(r) for r in stub.requests] == [6, 6]
        assert stub.temperatures == [None, 0.5]
        assert lines == [f"T_{line}" for line in LONG_LINES[:6]]
        assert no_cache == [[f"T_{line}" for line in LONG_LINES[:6]]]

    def test_a_single_line_that_fails_still_fails_the_file(self, no_cache):
        stub = _Stub(respond=lambda lines, n: _result([], success=False, error="connection reset"))
        with pytest.raises(RuntimeError, match="batch 1"):
            _translate_batch_or_split(stub, LONG_LINES[:1], "de", "en", ["fake"], None, False, "1")


class TestBatchSizeGovernor:
    def test_a_clean_file_never_touches_the_size(self):
        governor = BatchSizeGovernor()
        assert governor.limit(40) == 40
        governor.on_success()
        assert governor.limit(40) == 40

    def test_a_cut_shrinks_and_later_cuts_never_grow_it(self):
        governor = BatchSizeGovernor()
        governor.on_cut(12)
        assert governor.limit(40) == 12
        governor.on_cut(20)
        assert governor.limit(40) == 12
        governor.on_cut(4)
        assert governor.limit(40) == 4

    def test_it_grows_only_after_two_clean_batches(self):
        governor = BatchSizeGovernor()
        governor.on_cut(10)
        governor.on_success()
        assert governor.limit(40) == 10
        governor.on_success()
        assert governor.limit(40) == 15

    def test_a_failure_resets_the_streak(self):
        governor = BatchSizeGovernor()
        governor.on_cut(8)
        governor.on_success()
        governor.on_cut(6)
        governor.on_success()
        assert governor.limit(40) == 6
        governor.on_success()
        assert governor.limit(40) == 9

    def test_growth_never_exceeds_the_configured_size(self):
        governor = BatchSizeGovernor()
        governor.on_cut(20)
        governor.on_success()
        governor.on_success()
        assert governor.limit(24) == 24


class TestBatchLoopContext:
    class _Recording:
        def __init__(self):
            self.requests: list[tuple[list[str], dict]] = []

        def translate_with_fallback(
            self,
            lines,
            source_lang,
            target_lang,
            fallback_chain,
            glossary_entries=None,
            *,
            lookback=None,
            lookahead=None,
            history=None,
        ):
            self.requests.append((list(lines), {"history": history}))
            return _result([f"T_{line}" for line in lines])

    def test_later_batches_receive_the_finished_translations(self, no_cache, no_context):
        """The history is what carries names across a batch boundary."""
        recording = self._Recording()
        lines = [f"line{i}" for i in range(12)]
        translated, _ = _translate_in_batches(
            recording, lines, "en", "de", ["fake"], None, batch_size=4
        )
        assert translated == [f"T_{line}" for line in lines]
        assert [len(req[0]) for req in recording.requests] == [4, 4, 4]
        assert recording.requests[0][1]["history"] is None
        assert recording.requests[1][1]["history"] == [(f"line{i}", f"T_line{i}") for i in range(4)]
        assert recording.requests[2][1]["history"] == [(f"line{i}", f"T_line{i}") for i in range(8)]

    def test_history_is_capped_and_deduplicated(self):
        sources = [f"line{i}" for i in range(30)]
        translated = [f"T_{line}" for line in sources]
        pairs = _translation_history(sources, translated, limit=12)
        assert len(pairs) == 12
        assert pairs[0][0] == "line18"
        repeated = ["same line", "other line", "same line"]
        assert _translation_history(repeated, ["A", "B", "A2"]) == [
            ("other line", "B"),
            ("same line", "A2"),
        ]
