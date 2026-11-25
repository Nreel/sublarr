"""Request tuning ported from SubtitleEdit — budget, temperature, endpoint, response format.

Covers :mod:`translation.llm_utils` (token budget, temperature floor, endpoint
completion), :class:`translation.llm_base.LLMBackend` (budget sent, history and
formality in the prompt, retry_temperature reaching the retry), and
:class:`translation.openai_compat.OpenAICompatBackend` (``cache_prompt``,
``response_format`` only on the strict retry plus degradation, the
thinking-switch on a reasoning-only reply, endpoint-leading errors).
"""

import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from translation.llm_base import LLMBackend, LLMResponse
from translation.llm_utils import (
    MIN_CHAT_TEMPERATURE,
    batch_token_budget,
    build_translation_prompt,
    complete_endpoint,
    history_block,
    resolve_chat_temperature,
)
from translation.openai_compat import OpenAICompatBackend

DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLARR_DB_PATH", str(tmp_path / "app.db"))
    from config import reload_settings

    reload_settings()
    from app import create_app

    app = create_app(testing=True)
    from extensions import db as sa_db

    with app.app_context():
        sa_db.create_all()
    yield app


@pytest.fixture(autouse=True)
def _concurrency():
    from translation.concurrency import get_concurrency, reset_for_tests

    reset_for_tests()
    get_concurrency().register("openai_compat", 3)
    get_concurrency().register("tuning_llm", 2)
    yield
    reset_for_tests()


def _openai_backend(**overrides) -> OpenAICompatBackend:
    """OpenAICompatBackend without __init__ side effects (mirrors the compat tests)."""
    import threading

    backend = OpenAICompatBackend.__new__(OpenAICompatBackend)
    config = {"api_key": "sk-test", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"}
    config.update(overrides)
    backend.config = config
    backend._client = None
    backend._client_lock = threading.Lock()
    from translation.price_sheet import get_llm_price

    backend.cost_per_1m_tokens_in, backend.cost_per_1m_tokens_out = get_llm_price(
        "openai_compat", config["model"]
    )
    return backend


def _completion(content: str, finish_reason: str = "stop", **message_fields) -> MagicMock:
    mock = MagicMock()
    mock.model_dump.return_value = {
        "choices": [
            {
                "message": {"content": content, **message_fields},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        "model": "gpt-4o-mini",
    }
    return mock


class _RefusalError(Exception):
    """Server rejection with a status code, as the SDK raises it."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class _TuningLLM(LLMBackend):
    """Fake LLMBackend that records every payload it was about to send."""

    name = "tuning_llm"
    display_name = "Tuning LLM"
    default_model = "tuning-model"
    config_fields = []
    supports_glossary = True
    supports_batch = True
    max_batch_size = 50
    cost_per_1m_tokens_in = Decimal("3.00")
    cost_per_1m_tokens_out = Decimal("15.00")

    def __init__(self, replies: list[str]):
        super().__init__()
        self.replies = replies
        self.payloads: list[dict] = []
        self.messages: list[list[dict]] = []

    def _assemble_messages(self, lines, source_lang, target_lang, glossary_entries, **kwargs):
        messages = super()._assemble_messages(
            lines, source_lang, target_lang, glossary_entries, **kwargs
        )
        self.messages.append(messages)
        return messages

    def _build_request(self, messages, max_tokens):
        return {"messages": messages, "max_tokens": max_tokens, "temperature": 0.3}

    def _call_api(self, payload, timeout_s):
        self.payloads.append(payload)
        content = self.replies[len(self.payloads) - 1]
        return {"content": content}

    def _parse_response(self, raw) -> LLMResponse:
        return LLMResponse(
            translations=[line for line in raw["content"].split("\n") if line],
            tokens_in=10,
            tokens_out=4,
            model="tuning-model",
            finish_reason="stop",
            raw_latency_ms=5,
        )

    def health_check(self):
        return (True, "ok")

    def get_config_fields(self):
        return []


# --------------------------------------------------------------------- #
# Token budget
# --------------------------------------------------------------------- #


class TestTokenBudget:
    def test_budget_formula(self):
        # 200 slack + (32 + 2*2) + (32 + 2*3)
        assert batch_token_budget(["ab", "cde"]) == 200 + 36 + 38

    def test_empty_batch_keeps_slack(self):
        assert batch_token_budget([]) == 200

    def test_budget_is_sent_as_max_tokens(self, app):
        lines = ["one", "two", "three"]
        backend = _TuningLLM(["1: eins\n2: zwei\n3: drei"])
        with app.app_context():
            backend.translate_batch(lines, "en", "de")
        assert backend.payloads[0]["max_tokens"] == batch_token_budget(lines)

    def test_explicit_settings_max_tokens_wins(self, app):
        lines = ["one", "two"]
        backend = _TuningLLM(["1: eins\n2: zwei"])
        with app.app_context(), patch("translation.llm_base._settings_value", return_value=900):
            backend.translate_batch(lines, "en", "de")
        assert backend.payloads[0]["max_tokens"] == 900

    def test_non_numeric_settings_max_tokens_falls_back(self, app):
        lines = ["one", "two"]
        backend = _TuningLLM(["1: eins\n2: zwei"])
        with app.app_context(), patch("translation.llm_base._settings_value", return_value="wide"):
            backend.translate_batch(lines, "en", "de")
        assert backend.payloads[0]["max_tokens"] == batch_token_budget(lines)


# --------------------------------------------------------------------- #
# Temperature
# --------------------------------------------------------------------- #


class TestTemperatureFloor:
    def test_floor_when_nothing_configured(self):
        assert resolve_chat_temperature(None) == MIN_CHAT_TEMPERATURE

    def test_curated_default_is_never_below_the_floor(self):
        assert resolve_chat_temperature(None, curated=0.3) == 0.3
        assert resolve_chat_temperature(None, curated=0.05) == MIN_CHAT_TEMPERATURE

    def test_explicit_user_value_wins_including_zero(self):
        assert resolve_chat_temperature(0.0) == 0.0
        assert resolve_chat_temperature(1.0) == 1.0

    def test_request_always_carries_a_temperature(self):
        # No config key at all: llama.cpp's own 0.8 default must not be reached.
        backend = _openai_backend()
        payload = backend._build_request([{"role": "user", "content": "x"}], max_tokens=100)
        assert payload["temperature"] >= MIN_CHAT_TEMPERATURE

    def test_backend_config_temperature_wins_over_settings(self):
        backend = _openai_backend(temperature="0.7")
        with patch("translation.openai_compat._settings_value", return_value="0.45"):
            payload = backend._build_request([{"role": "user", "content": "x"}], max_tokens=100)
        assert payload["temperature"] == 0.7

    def test_settings_temperature_applies_when_config_is_silent(self):
        backend = _openai_backend()
        with patch("translation.openai_compat._settings_value", return_value="0.45"):
            payload = backend._build_request([{"role": "user", "content": "x"}], max_tokens=100)
        assert payload["temperature"] == 0.45

    def test_retry_temperature_warms_the_reatask_of_a_failed_batch(self, app):
        # The batching layer re-asks a failed batch whole with a warmer
        # temperature; that whole request is the retry, so it is warmed.
        backend = _TuningLLM(["1: eins\n2: zwei\n3: drei"])
        with app.app_context():
            backend.translate_batch(["one", "two", "three"], "en", "de", retry_temperature=0.5)
        assert backend.payloads[0]["temperature"] == 0.5

    def test_retry_temperature_warms_the_strict_retry_inside_the_same_call(self, app):
        backend = _TuningLLM(["1: eins", "1: eins\n2: zwei\n3: drei"])
        with app.app_context():
            backend.translate_batch(["one", "two", "three"], "en", "de", retry_temperature=0.5)
        assert len(backend.payloads) == 2
        assert backend.payloads[1]["temperature"] == 0.5

    def test_no_retry_temperature_keeps_the_configured_temperature(self, app):
        backend = _TuningLLM(["1: eins", "1: eins\n2: zwei\n3: drei"])
        with app.app_context():
            backend.translate_batch(["one", "two", "three"], "en", "de")
        assert len(backend.payloads) == 2
        assert backend.payloads[0]["temperature"] == 0.3
        assert backend.payloads[1]["temperature"] == 0.3


# --------------------------------------------------------------------- #
# cache_prompt / response_format ladder
# --------------------------------------------------------------------- #


class TestRequestBodyFlags:
    def test_cache_prompt_is_sent(self):
        backend = _openai_backend()
        payload = backend._build_request([{"role": "user", "content": "x"}], max_tokens=100)
        assert payload["cache_prompt"] is True

    def test_llama_only_fields_go_via_extra_body_not_sdk_kwargs(self, app):
        """The SDK rejects unknown kwargs before the request leaves (2026-11-24:
        every openai_compat batch died on Completions.create() got an unexpected
        keyword argument 'cache_prompt'). llama.cpp reads them from the body,
        which extra_body merges in."""
        backend = _openai_backend()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _completion("Hallo")
        backend._client = mock_client
        with app.app_context():
            backend.translate_batch(["Hello"], "en", "de")
        sent = mock_client.chat.completions.create.call_args.kwargs
        assert "cache_prompt" not in sent
        assert sent["extra_body"]["cache_prompt"] is True

    def test_first_attempt_never_asks_for_json(self, app):
        backend = _openai_backend()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _completion("Hallo")
        backend._client = mock_client
        with app.app_context():
            backend.translate_batch(["Hello"], "en", "de")
        sent = mock_client.chat.completions.create.call_args.kwargs
        assert "response_format" not in sent

    def test_response_format_only_on_the_strict_retry(self, app):
        backend = _openai_backend()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _completion("Hallo"),  # one line for three: count mismatch
            _completion("1: Hallo\n2: Welt\n3: Dritt"),
        ]
        backend._client = mock_client
        with app.app_context():
            backend.translate_batch(["Hello", "World", "Third"], "en", "de")
        first, retry = [c.kwargs for c in mock_client.chat.completions.create.call_args_list]
        assert "response_format" not in first
        assert retry["response_format"] == {"type": "json_object"}

    def test_rejected_response_format_is_resended_without_and_remembered(self, app):
        backend = _openai_backend()
        mock_client = MagicMock()
        refusal = _RefusalError("400: unsupported response_format json_object", 400)
        mock_client.chat.completions.create.side_effect = [
            _completion("Hallo"),
            refusal,
            _completion("1: Hallo\n2: Welt\n3: Dritt"),
        ]
        backend._client = mock_client
        with app.app_context():
            backend.translate_batch(["Hello", "World", "Third"], "en", "de")
        calls = [c.kwargs for c in mock_client.chat.completions.create.call_args_list]
        assert len(calls) == 3
        assert calls[1]["response_format"] == {"type": "json_object"}
        assert "response_format" not in calls[2]
        assert backend._response_format_rejected is True

        # Later batches of the same file stop asking for it, retry included.
        mock_client.chat.completions.create.side_effect = [
            _completion("Nur eine"),
            _completion("1: Hallo\n2: Welt\n3: Dritt"),
        ]
        mock_client.chat.completions.create.reset_mock()
        with app.app_context():
            backend.translate_batch(["Hello", "World", "Third"], "en", "de")
        for call in mock_client.chat.completions.create.call_args_list:
            assert "response_format" not in call.kwargs

    def test_502_json_validation_failure_is_read_as_a_refusal(self, app):
        """A proxy that validates the reply answers 502 when the model's JSON is
        malformed (prod 2026-11-25: gemma echoed ``\\N``, the server raised
        ``Invalid \\escape`` and the SDK replayed the same doomed request 3x).
        That is a refusal to serve json_object, so the batch is re-asked without
        it and the endpoint stops being asked for the rest of the file.
        """
        backend = _openai_backend()
        mock_client = MagicMock()
        refused = _RefusalError(
            "Error code: 502 - model did not return valid JSON: "
            "Invalid \\escape: line 3 column 40 (char 65)",
            502,
        )
        mock_client.chat.completions.create.side_effect = [
            _completion("Hallo"),
            refused,
            _completion("1: Hallo\n2: Welt\n3: Dritt"),
        ]
        backend._client = mock_client
        with app.app_context():
            backend.translate_batch(["Hello", "World", "Third"], "en", "de")
        calls = [c.kwargs for c in mock_client.chat.completions.create.call_args_list]
        assert len(calls) == 3
        assert calls[1]["response_format"] == {"type": "json_object"}
        assert "response_format" not in calls[2]
        assert backend._response_format_rejected is True

    def test_502_without_parse_wording_is_not_read_as_a_refusal(self, app):
        """An overload 502 says nothing about JSON; the field stays requested."""
        backend = _openai_backend()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _completion("Hallo"),
            _RefusalError("502: gateway overloaded", 502),
        ]
        backend._client = mock_client
        with app.app_context(), pytest.raises(RuntimeError, match="502: gateway overloaded"):
            backend.translate_batch(["Hello", "World", "Third"], "en", "de")
        assert backend._response_format_rejected is False

    def test_non_4xx_is_not_read_as_a_response_format_refusal(self, app):
        backend = _openai_backend()
        mock_client = MagicMock()
        refusal = _RefusalError("500: response_format backend crashed", 500)
        mock_client.chat.completions.create.side_effect = [_completion("Hallo"), refusal]
        backend._client = mock_client
        with app.app_context(), pytest.raises(RuntimeError, match="500: response_format"):
            backend.translate_batch(["Hello", "World", "Third"], "en", "de")
        assert backend._response_format_rejected is False


# --------------------------------------------------------------------- #
# Reasoning-only replies
# --------------------------------------------------------------------- #


class TestThinkingSwitch:
    def test_reasoning_only_reply_is_reasked_with_thinking_off(self):
        backend = _openai_backend()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _completion("", reasoning_content="chain of thought"),
            _completion("Hallo"),
        ]
        backend._client = mock_client
        raw = backend._call_api({"model": "gpt-4o-mini", "messages": []}, timeout_s=120)
        assert raw["choices"][0]["message"]["content"] == "Hallo"
        calls = [c.kwargs for c in mock_client.chat.completions.create.call_args_list]
        assert "chat_template_kwargs" not in calls[0]
        assert calls[1]["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert backend._thinking_disabled is True

    def test_thinking_off_is_kept_for_the_next_batch(self):
        backend = _openai_backend()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _completion("Hallo")
        backend._client = mock_client
        backend._thinking_disabled = True
        payload = backend._apply_attempt_policy(
            backend._build_request([{"role": "user", "content": "x"}], max_tokens=100)
        )
        raw = backend._call_api(payload, timeout_s=120)
        assert raw["choices"][0]["message"]["content"] == "Hallo"
        assert mock_client.chat.completions.create.call_args.kwargs["extra_body"][
            "chat_template_kwargs"
        ] == {"enable_thinking": False}

    def test_rejected_chat_template_kwargs_is_dropped_and_reasked_once(self):
        backend = _openai_backend()
        mock_client = MagicMock()
        refusal = _RefusalError("400: unknown field chat_template_kwargs", 400)
        mock_client.chat.completions.create.side_effect = [
            _completion("", reasoning_content="chain of thought"),
            refusal,
            _completion("Hallo"),
        ]
        backend._client = mock_client
        raw = backend._call_api({"model": "gpt-4o-mini", "messages": []}, timeout_s=120)
        assert raw["choices"][0]["message"]["content"] == "Hallo"
        calls = [c.kwargs for c in mock_client.chat.completions.create.call_args_list]
        assert calls[1]["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert "chat_template_kwargs" not in calls[2]
        assert "chat_template_kwargs" not in calls[2]["extra_body"]
        assert backend._thinking_disabled is False

    def test_content_reply_is_not_mistaken_for_reasoning(self):
        assert (
            OpenAICompatBackend._reply_is_reasoning_only(
                {"choices": [{"message": {"content": "Hallo"}}]}
            )
            is False
        )
        assert (
            OpenAICompatBackend._reply_is_reasoning_only(
                {"choices": [{"message": {"content": "", "reasoning": "thoughts"}}]}
            )
            is True
        )
        assert OpenAICompatBackend._reply_is_reasoning_only({"choices": []}) is False


# --------------------------------------------------------------------- #
# Endpoint completion + error text
# --------------------------------------------------------------------- #


class TestEndpointCompletion:
    def test_bare_host_gets_default_scheme_and_path(self):
        # The default endpoint's scheme is the only scheme there to borrow.
        assert complete_endpoint("localhost:1234", DEFAULT_ENDPOINT) == (
            "https://localhost:1234/v1/chat/completions"
        )
        azure = "http://local.example.com/v1/chat/completions"
        assert (
            complete_endpoint("localhost:1234", azure)
            == "http://localhost:1234/v1/chat/completions"
        )

    def test_origin_with_no_path_gets_default_path(self):
        assert complete_endpoint("http://localhost:1234", DEFAULT_ENDPOINT) == (
            "http://localhost:1234/v1/chat/completions"
        )

    def test_trailing_slash_gets_default_path(self):
        assert complete_endpoint("http://localhost:1234/", DEFAULT_ENDPOINT) == (
            "http://localhost:1234/v1/chat/completions"
        )

    def test_v1_prefix_is_completed(self):
        assert complete_endpoint("http://localhost:1234/v1", DEFAULT_ENDPOINT) == (
            "http://localhost:1234/v1/chat/completions"
        )

    def test_openai_v1_prefix_is_completed_against_its_own_default(self):
        azure = "https://account.openai.azure.com/openai/v1/chat/completions"
        assert complete_endpoint("https://account.openai.azure.com/openai/v1", azure) == azure

    def test_genuine_custom_path_is_untouched(self):
        assert complete_endpoint("http://gw.internal/llm/v1/chat", DEFAULT_ENDPOINT) == (
            "http://gw.internal/llm/v1/chat"
        )

    def test_partial_segment_prefix_is_not_completed(self):
        assert complete_endpoint("http://gw.internal/v", DEFAULT_ENDPOINT) == "http://gw.internal/v"

    def test_https_bare_host_keeps_https_when_scheme_given(self):
        assert complete_endpoint("https://host.test:8443/", DEFAULT_ENDPOINT) == (
            "https://host.test:8443/v1/chat/completions"
        )

    def test_empty_url_falls_back_to_default(self):
        assert complete_endpoint("", DEFAULT_ENDPOINT) == DEFAULT_ENDPOINT

    def test_backend_base_url_is_sdk_prefix_of_completed_endpoint(self):
        backend = _openai_backend(base_url="http://localhost:1234/v1")
        assert backend._chat_endpoint == "http://localhost:1234/v1/chat/completions"
        assert backend._base_url == "http://localhost:1234/v1"

    def test_default_config_base_url_is_unchanged(self):
        backend = _openai_backend(base_url="https://api.openai.com/v1")
        assert backend._base_url == "https://api.openai.com/v1"

    def test_transport_error_leads_with_the_endpoint_used(self):
        backend = _openai_backend(base_url="http://localhost:1234")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("connection refused")
        backend._client = mock_client
        with pytest.raises(RuntimeError) as excinfo:
            backend._call_api({"model": "m", "messages": []}, timeout_s=120)
        assert str(excinfo.value).startswith(
            "POST http://localhost:1234/v1/chat/completions: connection refused"
        )


# --------------------------------------------------------------------- #
# History + formality in the prompt
# --------------------------------------------------------------------- #


class TestHistoryAndFormality:
    def test_history_block_lists_pairs_and_marks_context_only(self):
        block = history_block([("Hello", "Hallo")])
        assert block.startswith("Recent translations (context only")
        assert "Hello -> Hallo" in block
        assert "do NOT re-translate" in block
        assert history_block([]) == ""

    def test_openai_prompt_places_history_before_the_numbered_lines(self):
        backend = _openai_backend()
        messages = backend._assemble_messages(
            ["Hello senpai", "World"],
            "en",
            "de",
            glossary_entries=[{"source_term": "senpai", "target_term": "Sempai"}],
            history=[("Onii-sama", "Bruder")],
        )
        prompt = messages[0]["content"]
        glossary_idx = prompt.find("Glossary:")
        history_idx = prompt.find("Recent translations")
        body_idx = prompt.find("1: Hello")
        assert glossary_idx != -1 and history_idx != -1 and body_idx != -1
        assert glossary_idx < history_idx < body_idx
        assert "Onii-sama -> Bruder" in prompt

    def test_llm_base_system_prompt_carries_history_before_the_lines(self):
        backend = _TuningLLM(["1: eins"])
        messages = backend._assemble_messages(
            ["one"],
            "en",
            "de",
            glossary_entries=[{"source": "senpai", "target": "Sempai"}],
            history=[("Hello", "Hallo")],
        )
        system = next(m["content"] for m in messages if m["role"] == "system")
        user = next(m["content"] for m in messages if m["role"] == "user")
        assert system.find("Glossary:") < system.find("Recent translations")
        assert "Hello -> Hallo" in system
        assert "Hello" not in user

    def test_formal_register_clause_from_settings(self):
        fake = SimpleNamespace(
            get_prompt_template=lambda s, t: "Translate these lines.\n\n",
            translation_formality="formal",
        )
        with patch("config.get_settings", return_value=fake):
            prompt = build_translation_prompt(["Hello"], "en", "de")
        assert 'Use formal address (e.g. German "Sie"' in prompt
        assert prompt.index("Use formal address") < prompt.index("Hello")

    def test_informal_register_clause_from_settings(self):
        fake = SimpleNamespace(
            get_prompt_template=lambda s, t: "Translate these lines.\n\n",
            translation_formality="informal",
        )
        with patch("config.get_settings", return_value=fake):
            prompt = build_translation_prompt(["Hello"], "en", "de")
        assert 'Use informal address (e.g. German "du"' in prompt

    def test_unset_register_sends_no_clause(self):
        fake = SimpleNamespace(
            get_prompt_template=lambda s, t: "Translate these lines.\n\n",
        )
        with patch("config.get_settings", return_value=fake):
            prompt = build_translation_prompt(["Hello"], "en", "de")
        assert "address" not in prompt

    def test_llm_base_system_prompt_carries_register(self):
        backend = _TuningLLM(["1: eins"])

        def knob(name):
            return "formal" if name == "translation_formality" else None

        with patch("translation.llm_base._settings_value", side_effect=knob):
            messages = backend._assemble_messages(["one"], "en", "de", None)
        system = next(m["content"] for m in messages if m["role"] == "system")
        assert 'Use formal address (e.g. German "Sie"' in system


# --------------------------------------------------------------------- #
# Signature threading
# --------------------------------------------------------------------- #


class TestSignatureThreading:
    def test_translate_with_fallback_takes_history_and_retry_temperature(self):
        from translation import get_translation_manager

        manager = get_translation_manager()
        params = inspect.signature(manager.translate_with_fallback).parameters
        assert params["history"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["retry_temperature"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["history"].default is None
        assert params["retry_temperature"].default is None

    def test_llm_backend_translate_batch_takes_the_extras(self):
        params = inspect.signature(LLMBackend.translate_batch).parameters
        assert params["history"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["retry_temperature"].kind is inspect.Parameter.KEYWORD_ONLY
