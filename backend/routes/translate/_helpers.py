"""Translate helpers — shared constants and non-route functions."""

import logging

import requests

from services.translation_jobs import run_job, update_stats

logger = logging.getLogger(__name__)


def _as_bool(value) -> bool:
    """Coerce a JSON/form value to a bool; "false"/"0"/"no"/"" are False.

    Form-encoded and curl ``-d`` callers send booleans as strings, and
    ``bool("false")`` is True — a user posting ``force=false`` used to get
    their existing subtitles overwritten.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


# --- Phase 28-01: LLM Backend Presets ---

BACKEND_TEMPLATES = [
    {
        "name": "deepseek_v3",
        "display_name": "DeepSeek V3",
        "backend_type": "openai_compat",
        "description": "Excellent quality, very low cost (~$0.07/1M tokens). Requires API key.",
        "config_defaults": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "context_window": 64000,
        },
    },
    {
        "name": "gemini_flash",
        "display_name": "Gemini 1.5 Flash",
        "backend_type": "openai_compat",
        "description": "Fast, cheap Google model with huge context window. Requires API key.",
        "config_defaults": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-1.5-flash",
            "context_window": 128000,
        },
    },
    {
        "name": "claude_haiku",
        "display_name": "Claude 3 Haiku",
        "backend_type": "openai_compat",
        "description": "Fast Anthropic model, good quality/cost ratio. Requires API key.",
        "config_defaults": {
            "base_url": "https://api.anthropic.com/v1",
            "model": "claude-3-haiku-20240307",
            "context_window": 32000,
        },
    },
    {
        "name": "mistral_medium",
        "display_name": "Mistral Medium",
        "backend_type": "openai_compat",
        "description": "Balanced quality and cost from Mistral AI. Requires API key.",
        "config_defaults": {
            "base_url": "https://api.mistral.ai/v1",
            "model": "mistral-medium-latest",
            "context_window": 32000,
        },
    },
    {
        "name": "lm_studio",
        "display_name": "LM Studio (local)",
        "backend_type": "openai_compat",
        "description": "Run any GGUF model locally. No API key needed. Start LM Studio server first.",
        "config_defaults": {
            "base_url": "http://localhost:1234/v1",
            "model": "local-model",
            "context_window": 8000,
        },
    },
    # --- Recommended general-purpose local models ---
    {
        "name": "qwen25_14b_instruct",
        "display_name": "Qwen2.5 14B Instruct (local)",
        "backend_type": "ollama",
        "category": "community",
        "description": (
            "Solid all-round instruction-tuned model. Runs fully local via "
            "Ollama, no API key. ~9 GB — needs a machine with the RAM/VRAM "
            "headroom to load it."
        ),
        "config_defaults": {
            "model": "qwen2.5:14b-instruct",
            "temperature": "0.3",
        },
        "ollama_pull": "qwen2.5:14b-instruct",
        "install_hint": (
            "# Pull via Ollama:\n"
            "ollama pull qwen2.5:14b-instruct\n\n"
            "# Or use the Install button above — Sublarr pulls it automatically."
        ),
        "tags": ["instruct", "general", "local", "9GB"],
        "languages": ["multi"],
        "size_gb": 9.0,
    },
    {
        "name": "llama31_8b_instruct",
        "display_name": "Llama 3.1 8B Instruct (local)",
        "backend_type": "ollama",
        "category": "community",
        "description": (
            "Lighter instruction-tuned alternative — fits in ~5 GB. "
            "Runs fully local via Ollama, no API key."
        ),
        "config_defaults": {
            "model": "llama3.1:8b-instruct",
            "temperature": "0.3",
        },
        "ollama_pull": "llama3.1:8b-instruct",
        "install_hint": (
            "# Pull via Ollama:\n"
            "ollama pull llama3.1:8b-instruct\n\n"
            "# Or use the Install button above — Sublarr pulls it automatically."
        ),
        "tags": ["instruct", "general", "local", "5GB"],
        "languages": ["multi"],
        "size_gb": 5.0,
    },
]


def _is_translation_enabled() -> bool:
    """Return True iff the translation feature is enabled in config.

    The dual /translate/disable + ``translation_enabled`` config flag had a
    silent gap: clicking Disable cancelled queued jobs and toggled the
    flag, but every translation-initiating endpoint still ran on new
    requests because nothing on the read side honoured the flag. Each
    initiating route now calls this helper after input validation and
    returns 503 when it returns False — same vocabulary as the Whisper
    feature gate (see translator._helpers._is_whisper_enabled).
    """
    try:
        from db.config import get_config_entry

        value = get_config_entry("translation_enabled")
        if value is None:
            # No DB override → fall back to the Pydantic default.
            from config import get_settings

            return bool(getattr(get_settings(), "translation_enabled", False))
        return value.lower() in ("true", "1", "yes")
    except Exception as exc:
        # On any lookup failure default to False so a corrupt config never
        # silently re-enables a feature the user explicitly disabled. But
        # say so: a transient DB error here turns EVERY translate endpoint
        # into a 503, and without a log line that looks like a mystery
        # "Translation is disabled" response with the UI still showing the
        # toggle on.
        logger.warning("translation_enabled lookup failed, failing closed: %s", exc)
        return False


def _update_stats(result):
    """Compat shim — implementation moved to
    :func:`services.translation_jobs.update_stats`."""
    return update_stats(result)


def _run_job(job_data):
    """Compat shim — implementation moved to
    :func:`services.translation_jobs.run_job`.

    Kept because routes and tests reference/patch the historical
    ``routes.translate...._run_job`` paths, and the redis job queue
    pickles this callable by module path.
    """
    return run_job(job_data)


def _build_arr_context(data):
    """Build arr_context from the request payload.

    Id keys are forwarded individually - Radarr movies and standalone titles
    need their ids too, or ``get_profile_for_item`` falls to the DEFAULT
    profile and the file is translated toward the global target with the
    wrong backend/glossary (the old builder required BOTH Sonarr ids and
    silently dropped everything else).

    Languages are forwarded only when the caller supplies them. Stamping the
    GLOBAL settings languages onto every job was a lie that persisted in the
    job row: the queue-state UI showed ``settings.target_language`` for jobs
    actually resolving to a profile target, and retries re-forwarded it.
    Absent means "resolve from the wanted row / profile", which is exactly
    what ``translate_file`` then does.
    """
    context = {}
    for key in (
        "sonarr_series_id",
        "sonarr_episode_id",
        "radarr_movie_id",
        "standalone_series_id",
        "standalone_movie_id",
    ):
        value = data.get(key)
        if value:
            context[key] = value
    for key in ("source_language", "target_language"):
        value = data.get(key)
        if value:
            context[key] = str(value)
    return context


def _validate_callback_url(url):
    """Validate callback URL to prevent SSRF attacks.

    Delegates to the canonical ``security_utils.validate_service_url`` so the
    bypass surface is identical to every other outbound-URL check: it
    normalises decimal/octal/hex-encoded IPv4 and IPv4-mapped IPv6 before
    the loopback/link-local/metadata checks fire (the hand-rolled
    ``ipaddress.ip_address`` form here accepted ``http://2130706433/`` =
    127.0.0.1) and resolves DNS hostnames to re-check every A/AAAA answer.

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    from security_utils import validate_service_url

    return validate_service_url(url)


def _send_callback(url, data):
    """Send a callback notification (fire-and-forget)."""
    try:
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        logger.warning("Callback to %s failed: %s", url, e)
