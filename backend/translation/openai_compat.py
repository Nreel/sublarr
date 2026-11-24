"""OpenAI-compatible translation backend.

Inherits from LLMBackend (Phase A1 telemetry) — the shared orchestration
(concurrency, retry on line-count mismatch, cost+event write) lives in
:mod:`translation.llm_base`. This module supplies the three provider hooks.

Supports any OpenAI-compatible endpoint via configurable base_url:
OpenAI, Azure OpenAI, LM Studio, vLLM, and other compatible services.
"""

from __future__ import annotations

import logging
import threading
from decimal import Decimal

from translation.llm_base import LLMBackend, LLMResponse, _settings_value
from translation.llm_utils import (
    build_translation_prompt,
    complete_endpoint,
    resolve_chat_temperature,
)
from translation.price_sheet import get_llm_price
from translation.prompt_safety import escape_for_prompt

logger = logging.getLogger(__name__)

# Chat-completions path the OpenAI SDK appends to ``base_url`` itself, and the
# endpoint a half-given URL (``localhost:1234``, ``http://host:1234/``) is
# completed to. A bare host is what the server's own docs show, not what the
# wire needs.
CHAT_COMPLETIONS_PATH = "/chat/completions"
DEFAULT_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"

# Curated default for a backend whose config carries no temperature. Kept
# above llm_utils.MIN_CHAT_TEMPERATURE: the floor exists so nothing is ever
# forwarded to llama.cpp's own 0.8 default.
CURATED_TEMPERATURE = 0.3


def _as_float(value: object) -> float | None:
    """Coerce a config/settings value to float, or ``None`` when it is not one."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _http_status(exc: Exception) -> int | None:
    """Status code of an SDK/transport error, when it carried one."""
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _response_format_rejection(exc: Exception) -> bool:
    """Whether a 4xx was the server refusing ``response_format``.

    llama.cpp's server and plain vLLM reject the field outright; OpenAI and
    Azure accept it. A rejection is per-endpoint, not per-batch, so it is
    remembered for the rest of the file rather than retried line after line.
    """
    status = _http_status(exc)
    if status is not None and not 400 <= status < 500:
        return False
    text = str(exc).lower()
    return "response_format" in text or "json_object" in text


def _endpoint_error(endpoint: str, exc: Exception) -> RuntimeError:
    """Wrap a transport/HTTP failure so the URL used leads.

    SubtitleEdit #12907 — the error text must name the API URL the request
    actually went to. "Connection refused" with no URL is unreadable when the
    operator has several endpoints configured, and the config value is not the
    URL that was used: it is the completed one.
    """
    return RuntimeError(f"POST {endpoint}: {exc}")


# Import guard: openai is optional
try:
    from openai import OpenAI

    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    logger.warning(
        "openai package not installed -- OpenAI-compatible backend unavailable. "
        "Install with: pip install openai>=1.0.0"
    )


class OpenAICompatBackend(LLMBackend):
    """OpenAI-compatible LLM translation backend.

    Uses the OpenAI Python SDK with configurable base_url to support
    OpenAI, Azure OpenAI, LM Studio, vLLM, and other compatible services.

    Config values are loaded from config_entries (backend.openai_compat.*)
    by the TranslationManager.
    """

    name = "openai_compat"
    display_name = "OpenAI-Compatible (OpenAI, Azure, LM Studio, vLLM)"
    supports_glossary = True  # Via prompt injection (same as Ollama)
    supports_batch = True
    max_batch_size = 25

    # Per-endpoint learnings. A server that refused one field refuses it for
    # every batch of the file, so the answer is remembered instead of probed
    # again line after line. Class-level defaults keep a backend constructed
    # with ``__new__`` (the tests) usable.
    _response_format_rejected = False
    _thinking_disabled = False

    # LLMBackend class-level contract. Prices are overridden per-instance in
    # __init__ via the price sheet (depends on the selected model).
    default_model = "gpt-4o-mini"
    cost_per_1m_tokens_in = Decimal("0")
    cost_per_1m_tokens_out = Decimal("0")
    timeout_s = 120

    config_fields = [
        {
            "key": "api_key",
            "label": "API Key",
            "type": "password",
            "required": True,
            "default": "",
            "help": "API key for the OpenAI-compatible service",
        },
        {
            "key": "base_url",
            "label": "Base URL",
            "type": "text",
            "required": True,
            "default": "https://api.openai.com/v1",
            "help": "API base URL (e.g. https://api.openai.com/v1, http://localhost:1234/v1)",
        },
        {
            "key": "model",
            "label": "Model",
            "type": "text",
            "required": True,
            "default": "gpt-4o-mini",
            "help": "Model name (e.g. gpt-4o-mini, gpt-4o, local model name)",
        },
        {
            "key": "temperature",
            "label": "Temperature",
            "type": "number",
            "required": False,
            "default": "0.3",
            "help": "Lower = more deterministic (0.0-1.0)",
        },
        {
            "key": "request_timeout",
            "label": "Timeout (seconds)",
            "type": "number",
            "required": False,
            "default": "120",
            "help": "Request timeout for API calls",
        },
        {
            "key": "max_retries",
            "label": "Max Retries",
            "type": "number",
            "required": False,
            "default": "3",
            "help": "Number of retry attempts on failure",
        },
    ]

    def __init__(self, **config):
        super().__init__(**config)
        self._client = None
        self._client_lock = threading.Lock()
        # Look up instance-level prices from the price sheet. Overrides the
        # class defaults (0, 0) so cost_tracker produces real numbers.
        self.cost_per_1m_tokens_in, self.cost_per_1m_tokens_out = get_llm_price(
            self.name, self._model
        )

    @property
    def _api_key(self) -> str:
        return self.config.get("api_key", "")

    @property
    def _chat_endpoint(self) -> str:
        """Full chat-completions URL this backend posts to.

        Configured ``base_url`` is completed by
        :func:`translation.llm_utils.complete_endpoint`: a bare ``host:port``
        gets the default scheme and path, an origin with no path (or just
        ``/``) gets the default path, ``/v1``/``/openai/v1`` are completed to
        the default's full path, and a genuine custom path is left alone.
        Error text and health checks name this URL, because it is the one the
        request actually used.
        """
        configured = self.config.get("base_url", "https://api.openai.com/v1")
        return complete_endpoint(configured, DEFAULT_CHAT_ENDPOINT)

    @property
    def _base_url(self) -> str:
        """Base URL for the OpenAI SDK — the completed endpoint minus its tail.

        The SDK appends ``/chat/completions`` to ``base_url`` itself, so the
        completed endpoint is turned back into the prefix. A custom path that
        is not a chat-completions endpoint is passed through untouched.
        """
        endpoint = self._chat_endpoint
        if endpoint.endswith(CHAT_COMPLETIONS_PATH):
            return endpoint[: -len(CHAT_COMPLETIONS_PATH)]
        return endpoint

    @property
    def _model(self) -> str:
        return self.config.get("model", "gpt-4o-mini")

    @property
    def model(self) -> str:
        return self._model

    @property
    def _temperature(self) -> float:
        """Configured temperature, falling back to the curated default."""
        try:
            return float(self.config.get("temperature", CURATED_TEMPERATURE))
        except (ValueError, TypeError):
            return CURATED_TEMPERATURE

    def _resolve_temperature(self) -> float:
        """Temperature to send: backend config -> settings -> curated -> floor.

        Never left out of the request: llama.cpp answers a chat request with no
        ``temperature`` at its own default of 0.8, and at 0.8 one glossary term
        comes back spelled two ways inside the same episode. An explicit 0.0
        from the operator is honoured as-is; only silence is floored.
        """
        configured = _as_float(self.config.get("temperature"))
        if configured is not None:
            return resolve_chat_temperature(configured, curated=CURATED_TEMPERATURE)
        from_settings = _as_float(_settings_value("temperature"))
        if from_settings is not None:
            return resolve_chat_temperature(from_settings, curated=CURATED_TEMPERATURE)
        return resolve_chat_temperature(None, curated=CURATED_TEMPERATURE)

    @property
    def _request_timeout(self) -> int:
        try:
            return int(self.config.get("request_timeout", 120))
        except (ValueError, TypeError):
            return 120

    @property
    def _max_retries(self) -> int:
        try:
            return int(self.config.get("max_retries", 3))
        except (ValueError, TypeError):
            return 3

    def _get_client(self) -> OpenAI:
        """Get or create the OpenAI client (lazy initialization, thread-safe)."""
        if not _HAS_OPENAI:
            raise RuntimeError(
                "openai package not installed. Install with: pip install openai>=1.0.0"
            )
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = OpenAI(
                        api_key=self._api_key,
                        base_url=self._base_url,
                        timeout=self._request_timeout,
                        # Honour the configured max_retries knob. It used to
                        # be a dead property: the client pinned 0 on a
                        # "retries handled ourselves" comment, but nothing
                        # retried transport errors — llm_base only re-asks on
                        # line-count/content mismatches. One 503 from the
                        # endpoint was booked as a backend health failure and
                        # pushed the breaker toward OPEN.
                        max_retries=self._max_retries,
                    )
        return self._client

    # ------------------------------------------------------------------ #
    # LLMBackend hooks
    # ------------------------------------------------------------------ #

    def _assemble_messages(
        self,
        lines: list[str],
        source_lang: str,
        target_lang: str,
        glossary_entries: list[dict] | None,
        series_context: str | None = None,
        strict: bool = False,
        *,
        lookback: list[str] | None = None,
        lookahead: list[str] | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> list[dict]:
        """Build the OpenAI-style messages list.

        Uses the same numbered/glossary prompt format as Ollama
        (via :func:`build_translation_prompt`) so LLMs trained on that
        shape behave consistently. We put the full prompt in a single user
        message — the system-vs-user split doesn't add value here and keeps
        parity with Ollama's generate-mode.

        Lookback/lookahead context (Phase A4) is prepended to the prompt as
        a clearly marked "context only" block when provided, so generic
        OpenAI-compatible endpoints benefit from narrative context even
        though the main prompt shape stays compatible with Ollama's format.
        ``history`` is the finished ``(source, translation)`` pairs and goes
        inside the prompt, immediately before the lines to translate — the
        glossary and template ahead of it repeat verbatim batch after batch,
        which is the part a server reuses from its KV prefix.
        """
        prompt = build_translation_prompt(
            lines,
            source_lang,
            target_lang,
            glossary_entries,
            strict=strict,
            history=history,
        )
        prefix_parts = []
        if series_context:
            # P3: series_context comes from upstream metadata (Sonarr/Radarr
            # `overview`), which is attacker-controllable. Escape before
            # injecting into the prompt to deny prompt-injection / batch-break.
            prefix_parts.append(f"Context: {escape_for_prompt(series_context)}")
        if lookback:
            safe_lookback = [escape_for_prompt(line) for line in lookback]
            prefix_parts.append(
                "Previous lines (for context only, do NOT translate or repeat):\n"
                + "\n".join(safe_lookback)
            )
        if lookahead:
            safe_lookahead = [escape_for_prompt(line) for line in lookahead]
            prefix_parts.append(
                "Following lines (for context only, do NOT translate or repeat):\n"
                + "\n".join(safe_lookahead)
            )
        if strict:
            prefix_parts.append(
                f"STRICT: return exactly {len(lines)} numbered lines, "
                f"no commentary, no extra lines."
            )
        if prefix_parts:
            prompt = "\n\n".join(prefix_parts) + "\n\n" + prompt
        return [{"role": "user", "content": prompt}]

    def _build_request(self, messages: list[dict], max_tokens: int) -> dict:
        """Build the chat/completions payload.

        ``cache_prompt`` asks llama.cpp to reuse the KV prefix of an identical
        prompt head — the batches of one file share the instruction block, so
        the reuse is what makes a 40-batch episode cheap. Generic
        OpenAI-compatible servers ignore fields they do not know, so the extra
        key costs nothing there.
        """
        return {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self._resolve_temperature(),
            "cache_prompt": True,
        }

    def _apply_attempt_policy(
        self,
        payload: dict,
        *,
        strict: bool = False,
        retry_temperature: float | None = None,
    ) -> dict:
        """Provider ladder for the attempt about to be sent.

        ``strict`` marks the retry after a line-count/alignment failure: only
        there is ``response_format`` sent, because a first attempt that asks
        for JSON from a server which cannot serve it fails the whole batch
        instead of failing one line. A server that refused it is remembered and
        never asked again in this file. ``enable_thinking`` is switched off once
        a reply came back as reasoning only — the answer was behind a field the
        parser never reads, so the batch came back empty.
        """
        payload = super()._apply_attempt_policy(
            payload, strict=strict, retry_temperature=retry_temperature
        )
        if strict and not self._response_format_rejected:
            payload["response_format"] = {"type": "json_object"}
        if self._thinking_disabled:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def _sdk_create(self, body: dict) -> dict:
        """One ``chat.completions.create`` call, returned as a plain dict.

        llama.cpp-only fields (``cache_prompt``, ``chat_template_kwargs``) are
        not part of the OpenAI parameter list — the SDK rejects unknown kwargs
        before the request is sent (``Completions.create() got an unexpected
        keyword argument 'cache_prompt'``, 2026-11-24). They go through
        ``extra_body``, which merges them into the JSON body the server
        receives; generic OpenAI-compatible servers ignore unknown fields
        there, so the extra keys cost nothing.
        """
        client = self._get_client()
        body = dict(body)
        extra_body = {
            key: body.pop(key) for key in ("cache_prompt", "chat_template_kwargs") if key in body
        }
        completion = client.chat.completions.create(**body, extra_body=extra_body)
        # The SDK returns a pydantic model; convert to dict for parse step.
        if hasattr(completion, "model_dump"):
            return completion.model_dump()
        # Fallback for MagicMock-based tests: build a shape-compatible dict.
        choice = completion.choices[0]
        return {
            "choices": [
                {
                    "message": {
                        "content": choice.message.content,
                        "reasoning_content": getattr(choice.message, "reasoning_content", None),
                        "reasoning": getattr(choice.message, "reasoning", None),
                    },
                    "finish_reason": getattr(choice, "finish_reason", None),
                }
            ],
            "usage": getattr(completion, "usage", None),
            "model": getattr(completion, "model", self._model),
        }

    @staticmethod
    def _reply_is_reasoning_only(raw: dict) -> bool:
        """Whether the reply came back with no content but a thinking field.

        llama.cpp and vLLM answer a thinking model with the reasoning in
        ``reasoning_content`` (or ``reasoning``) and an empty ``content``. The
        content is what the parser reads, so such a reply is an empty batch —
        not a bad translation, a missing one.
        """
        choices = raw.get("choices") or []
        if not choices:
            return False
        choice = choices[0]
        message = (
            choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
        )
        if isinstance(message, dict):
            content = message.get("content")
            reasoning = message.get("reasoning_content") or message.get("reasoning")
        else:
            content = getattr(message, "content", None)
            reasoning = getattr(message, "reasoning_content", None) or getattr(
                message, "reasoning", None
            )
        if not isinstance(content, str):
            content = ""
        return not content.strip() and bool(reasoning)

    def _call_api(self, payload: dict, timeout_s: int) -> dict:
        """Execute chat/completions via the OpenAI SDK.

        Three degradations are handled here because only the endpoint can
        answer them:

        * a server that rejects ``response_format`` (see
          :meth:`_apply_attempt_policy`) is re-asked once without it, and the
          refusal is remembered for the rest of the file;
        * a thinking model whose reply is reasoning only is re-asked once with
          ``chat_template_kwargs: {"enable_thinking": false}``, kept for the
          following batches; if the server rejects that field too, it is
          dropped and the batch is re-asked plainly once;
        * every transport/HTTP failure is re-raised with the endpoint leading
          (:func:`_endpoint_error`), because the configured value is not
        necessarily the URL the request went to.
        """
        endpoint = self._chat_endpoint
        body = dict(payload)
        try:
            raw = self._sdk_create(body)
        except Exception as exc:
            if "response_format" in body and _response_format_rejection(exc):
                body.pop("response_format")
                self._response_format_rejected = True
                logger.info(
                    "%s rejected response_format=json_object — resent without it for the rest of the file",
                    endpoint,
                )
                try:
                    return self._sdk_create(body)
                except Exception as retry_exc:
                    raise _endpoint_error(endpoint, retry_exc) from retry_exc
            raise _endpoint_error(endpoint, exc) from exc

        if self._reply_is_reasoning_only(raw) and not self._thinking_disabled:
            self._thinking_disabled = True
            thinking_off = {**body, "chat_template_kwargs": {"enable_thinking": False}}
            try:
                return self._sdk_create(thinking_off)
            except Exception as exc:
                status = _http_status(exc)
                if status is None or not 400 <= status < 500:
                    raise _endpoint_error(endpoint, exc) from exc
                self._thinking_disabled = False
                logger.info("%s rejected chat_template_kwargs — re-asking without it", endpoint)
                try:
                    return self._sdk_create(body)
                except Exception as retry_exc:
                    raise _endpoint_error(endpoint, retry_exc) from retry_exc
        return raw

    def _call_openai(self, prompt: str) -> str:
        """Raw single-prompt call used by the quality evaluator.

        ``TranslationManager._call_backend_raw`` looks for exactly this
        method name (mirroring Ollama's ``_call_ollama``). Without it
        ``evaluate_line_quality`` returned None for every
        OpenAI-compatible backend — the quality gate silently never ran
        for LM Studio / vLLM / Azure-OpenAI setups.
        """
        payload = self._build_request([{"role": "user", "content": prompt}], max_tokens=64)
        payload["temperature"] = 0.0
        raw = self._call_api(payload, self._request_timeout)
        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError("openai_compat: no choices in evaluation response")
        message = choices[0].get("message") or {}
        return message.get("content") or ""

    def _parse_response(self, raw: dict) -> LLMResponse:
        """Extract translations + usage stats from the completion response."""
        try:
            choice = raw["choices"][0]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"OpenAI response missing 'choices': {raw!r}") from e

        message = choice.get("message") or {}
        content = message.get("content")
        if content is None:
            raise RuntimeError(f"OpenAI response missing 'message.content': {raw!r}")

        text = content.strip()
        # Splitting only — numbering, stray break markers and wrapped lines are
        # repaired centrally by LLMBackend._attempt.
        translations = text.split("\n") or [text]

        usage = raw.get("usage") or {}
        # usage may be a pydantic-ish object; accommodate both shapes.
        if isinstance(usage, dict):
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
        else:
            tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
            tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)

        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None

        return LLMResponse(
            translations=translations,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=raw.get("model", self._model),
            finish_reason=finish_reason,
            raw_latency_ms=0,  # OpenAI doesn't report server-side latency
        )

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def health_check(self) -> tuple[bool, str]:
        """Check if the OpenAI-compatible service is reachable and model available."""
        try:
            client = self._get_client()
            models_response = client.models.list()
            model_ids = [m.id for m in list(models_response)[:10]]
            if self._model in model_ids:
                return True, f"OK (model '{self._model}' available)"
            # Model might still work even if not in first 10
            return (
                True,
                f"OK (connected; model '{self._model}' not in first 10 listed: {model_ids})",
            )
        except RuntimeError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Health check failed: {e}"

    def get_config_fields(self) -> list[dict]:
        """Return config field definitions for the Settings UI."""
        return self.config_fields
