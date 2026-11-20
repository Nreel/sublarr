"""Google Cloud Translation v3 backend.

Uses the official Google Cloud Translation v3 SDK for enterprise-grade
translation with native glossary support. Requires a Google Cloud project
with the Translation API enabled and service account credentials.
"""

import logging
import os
import time
from datetime import UTC, datetime
from decimal import Decimal

from translation.base import TranslationBackend, TranslationResult
from translation.concurrency import get_concurrency
from translation.cost_tracker import calculate_char_cost_micro_usd
from translation.price_sheet import get_char_price
from translator.events import write_translation_event

logger = logging.getLogger(__name__)

# Import guard: google-cloud-translate is optional
try:
    from google.cloud import translate_v3

    _HAS_GOOGLE = True
except ImportError:
    _HAS_GOOGLE = False
    translate_v3 = None
    logger.warning(
        "google-cloud-translate package not installed -- Google backend unavailable. "
        "Install with: pip install google-cloud-translate>=3.10.0"
    )


class GoogleTranslateBackend(TranslationBackend):
    """Google Cloud Translation v3 backend.

    Uses the official v3 SDK with project-level authentication via service
    account credentials (JSON file or GOOGLE_APPLICATION_CREDENTIALS env var).

    Config values are loaded from config_entries (backend.google.*)
    by the TranslationManager.
    """

    name = "google"
    display_name = "Google Cloud Translation"
    supports_glossary = True  # Native API support
    supports_batch = True
    max_batch_size = 1024
    # Class-level defaults (same pattern as azure_translator/mymemory): the
    # concurrency slot and event/cost writer read these on every batch, and
    # instances built without __init__ (tests, out-of-tree callers) must
    # still have the attributes.
    cost_per_1m_chars = Decimal("20.00")
    timeout_s = 60.0

    config_fields = [
        {
            "key": "project_id",
            "label": "Project ID",
            "type": "text",
            "required": True,
            "default": "",
            "help": "Google Cloud project ID with Translation API enabled",
        },
        {
            "key": "credentials_path",
            "label": "Credentials Path",
            "type": "text",
            "required": False,
            "default": "",
            "help": "Path to service account JSON file, or set GOOGLE_APPLICATION_CREDENTIALS env var",
        },
        {
            "key": "location",
            "label": "Location",
            "type": "text",
            "required": False,
            "default": "global",
            "help": "Google Cloud region (default: global)",
        },
    ]

    def __init__(self, **config):
        super().__init__(**config)
        # Per-million-char price (see price_sheet.CHAR_PRICES_USD per 1M chars);
        # the registry name is "google", so the price key must match it.
        self.cost_per_1m_chars = get_char_price(self.name)
        self.timeout_s = 60.0

    @property
    def _project_id(self) -> str:
        return self.config.get("project_id", "")

    @property
    def _credentials_path(self) -> str:
        return self.config.get("credentials_path", "")

    @property
    def _location(self) -> str:
        return self.config.get("location", "global")

    @property
    def _parent(self) -> str:
        return f"projects/{self._project_id}/locations/{self._location}"

    def _create_client(self) -> "translate_v3.TranslationServiceClient":
        """Create a Google Cloud Translation client.

        Sets GOOGLE_APPLICATION_CREDENTIALS env var if credentials_path
        is configured before creating the client.
        """
        if not _HAS_GOOGLE:
            raise RuntimeError(
                "google-cloud-translate package not installed. "
                "Install with: pip install google-cloud-translate>=3.10.0"
            )

        # Set credentials path in environment if configured
        if self._credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._credentials_path

        return translate_v3.TranslationServiceClient()

    def translate_batch(
        self,
        lines: list[str],
        source_lang: str,
        target_lang: str,
        glossary_entries: list[dict] | None = None,
        series_context: str | None = None,
        *,
        lookback: list[str] | None = None,
        lookahead: list[str] | None = None,
        job_id: str | None = None,
    ) -> TranslationResult:
        """Translate a batch of subtitle lines via Google Cloud Translation API.

        Uses the v3 translate_text endpoint which supports batch translation
        natively (up to 1024 segments per request).

        ``series_context``, ``lookback`` and ``lookahead`` are accepted for a
        uniform backend interface but IGNORED — Google Translation v3 is a
        rule-/statistics-based REST API with no prompt concept.
        """
        # Non-LLM backend: drop prompt-only arguments.
        del series_context, lookback, lookahead
        from translation.llm_base import JobCancelledError
        from translation.queue_state import get_queue_state

        if not lines:
            return TranslationResult(
                translated_lines=[],
                backend_name=self.name,
                success=True,
            )

        if job_id and get_queue_state().is_cancelled(job_id):
            raise JobCancelledError(f"Job {job_id} was cancelled")

        started_at = datetime.now(UTC)
        started_mono = time.monotonic()
        status = "ok"
        error_type: str | None = None
        error_msg: str | None = None
        translated_lines: list[str] = []
        chars_in = sum(len(line) for line in lines)
        chars_out: int | None = None

        try:
            # Azure, DeepL, LibreTranslate and the LLM backends all hold a
            # BackendConcurrency slot around their request; Google alone ran
            # unthrottled, so its latency metric (queue_state._JobState.
            # last_latency_ms <- write_translation_event) was permanently 0
            # and the /translation/queue view lied about the active backend.
            with get_concurrency().slot(self.name, timeout_s=self.timeout_s):
                client = self._create_client()

                response = client.translate_text(
                    request={
                        "parent": self._parent,
                        "contents": lines,
                        "mime_type": "text/plain",
                        "source_language_code": source_lang,
                        "target_language_code": target_lang,
                    }
                )

                translated_lines = [t.translated_text for t in response.translations]
                chars_out = sum(len(t) for t in translated_lines)

        except JobCancelledError:
            status = "cancelled"
            error_type = "JobCancelledError"
            error_msg = "Job cancelled before/during request"
            raise
        except RuntimeError as e:
            # Package not installed
            status = "error"
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error("Google Translation failed: %s", e)
            return TranslationResult(
                translated_lines=[],
                backend_name=self.name,
                error=str(e),
                success=False,
            )
        except Exception as e:
            status = "error"
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error("Google Translation failed: %s", e)
            return TranslationResult(
                translated_lines=[],
                backend_name=self.name,
                error=f"Google Translation error: {e}",
                success=False,
            )
        finally:
            finished_at = datetime.now(UTC)
            latency_ms = int((time.monotonic() - started_mono) * 1000)
            cost = calculate_char_cost_micro_usd(chars_in, self.cost_per_1m_chars)
            write_translation_event(
                backend=self.name,
                source_lang=source_lang,
                target_lang=target_lang,
                lines_count=len(lines),
                chars_in=chars_in,
                chars_out=chars_out,
                cost_micro_usd=cost,
                cache_hit=False,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                error_type=error_type,
                error_msg=error_msg,
                job_id=job_id,
            )
            self._last_latency_ms = latency_ms

        return TranslationResult(
            translated_lines=translated_lines,
            backend_name=self.name,
            response_time_ms=float(latency_ms),
            characters_used=chars_in,
            success=True,
        )

    def health_check(self) -> tuple[bool, str]:
        """Check if Google Cloud Translation is reachable and configured."""
        try:
            client = self._create_client()
            response = client.get_supported_languages(request={"parent": self._parent})
            lang_count = len(response.languages)
            return True, f"OK ({lang_count} languages supported)"
        except RuntimeError as e:
            return False, str(e)
        except Exception as e:
            error_msg = str(e)
            if "DefaultCredentialsError" in type(e).__name__ or "credentials" in error_msg.lower():
                return False, f"Credentials error: {error_msg}"
            return False, f"Health check failed: {error_msg}"

    def get_config_fields(self) -> list[dict]:
        """Return config field definitions for the Settings UI."""
        return self.config_fields

    def get_usage(self) -> dict:
        """Google uses billing-based quota -- no per-request usage tracking."""
        return {}
