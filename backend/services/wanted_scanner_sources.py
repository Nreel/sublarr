"""Per-source scan mixin for WantedScanner.

Extracted from services/wanted_scanner_core.py. Owns the three
by-source scan entry points (Sonarr instances, Radarr instances,
standalone folders) plus the shared auto-extract trigger and the
incremental ``since`` filter semantics.

Every method uses ``self._progress``, ``self._socketio`` and the core
repositories/clients via module-level imports — nothing Flask-specific,
so the mixin composes cleanly into :class:`WantedScanner`.
"""

import logging
import time

from config import get_settings
from db.wanted import batch_upsert_context, get_wanted_paths_for_title

# Aliased import: tests patch "services.wanted_scanner_sources._extract_embedded_sub".
from services.embedded_extractor import extract_embedded_sub as _extract_embedded_sub
from services.scheduler.cancellation import abort_requested
from services.wanted_item_scanner import scan_radarr_movie, scan_sonarr_series

logger = logging.getLogger(__name__)


def _episode_file_stats(series: dict) -> tuple:
    """Sonarr's episode-file fingerprint of a series (count, size on disk).

    Both live in the ``/series`` response, so the incremental scan can see a
    new or re-imported episode file without asking for the episode files.
    """
    stats = series.get("statistics") or {}
    return (stats.get("episodeFileCount"), stats.get("sizeOnDisk"))


def _lookup_target_language(item_id: int) -> str | None:
    """Return the wanted_item's target_language, or None if it isn't found.

    Module-level helper so tests can patch it independently of the
    scanner instance.
    """
    try:
        from db.wanted import get_wanted_item

        row = get_wanted_item(item_id)
        if not row:
            return None
        lang = row.get("target_language")
        return lang or None
    except Exception:
        logger.exception("subtitle_automation: target_language lookup failed")
        return None


def _enqueue_automation(*, wanted_item_id: int, file_path: str, target_language: str) -> None:
    """Wrapper around the queue repository so tests can stub it cheaply."""
    from db.repositories.subtitle_automation_queue import (
        SubtitleAutomationQueueRepository,
    )

    repo = SubtitleAutomationQueueRepository()
    repo.enqueue(
        wanted_item_id=wanted_item_id,
        file_path=file_path,
        target_language=target_language,
    )


class _WantedScanSourcesMixin:
    """Sonarr/Radarr/standalone scan loops composed into WantedScanner."""

    @staticmethod
    def _default_instance_name(kind: str) -> str:
        """Name of the instance ``get_sonarr_client()``/``get_radarr_client()`` use.

        A single-title scan (webhook, /wanted/scan?type=series) writes rows
        through the unnamed client, which is the first instance. Without the
        name those rows are tagged "" and the empty-source guard — which asks
        how many rows belong to an instance — cannot see them, so a source
        answering ``200 []`` while starting pruned exactly those rows.
        """
        try:
            from config import get_radarr_instances, get_sonarr_instances

            instances = get_sonarr_instances() if kind == "sonarr" else get_radarr_instances()
            if instances:
                return instances[0].get("name") or "Default"
        except Exception:
            logger.debug("%s instance name lookup failed", kind, exc_info=True)
        return ""

    def _episode_files_changed(self, key, series) -> bool:
        """True when a series' episode files moved since it was last scanned.

        Sonarr's ``SeriesResource`` has no ``lastInfoSync``: the filter used to
        read that absent field and fall back to ``added``, so new episodes and
        re-imports of an already-added series were invisible to every
        incremental scan and had to wait for the full pass (one scan in six).
        ``statistics`` moves exactly when files move.

        A series never seen before is NOT rescanned here — the boot scan or the
        periodic full pass covers it — so the first incremental pass after a
        restart only records baselines instead of re-walking the library.
        """
        stats = series.get("statistics") or {}
        if not stats:
            return False
        previous = self._episode_fingerprints.get(key)
        return previous is not None and previous != _episode_file_stats(series)

    def _resumed(self, key, all_paths) -> bool:
        """True when an earlier, stopped part of this full pass already scanned ``key``.

        Its paths still count as seen, so the pass that finishes prunes
        against everything the parts covered together (#248).
        """
        done = self._pass_done
        if done is None or key not in done:
            return False
        all_paths.update(done[key])
        return True

    def _mark_done(self, key, paths) -> None:
        """Record ``key`` as scanned — unless the stop came while it ran.

        A series stopped mid-way upserts nothing (``scan_sonarr_series``), so
        it must be scanned again by the next part.
        """
        if self._pass_done is not None and not abort_requested():
            self._pass_done[key] = frozenset(paths)

    def _scan_all_sonarr(self, settings, since=None):
        """Scan all Sonarr instances. Returns (added, updated, paths)."""
        total_added = 0
        total_updated = 0
        all_paths = set()

        try:
            from config import get_sonarr_instances
            from sonarr_client import get_sonarr_client

            instances = get_sonarr_instances()
            for inst in instances:
                instance_name = inst.get("name", "Default")
                sonarr = get_sonarr_client(instance_name=instance_name)
                if sonarr:
                    a, u, paths = self._scan_sonarr_instance(sonarr, settings, instance_name, since)
                    total_added += a
                    total_updated += u
                    all_paths.update(paths)
        except Exception as e:
            logger.error("Wanted scan: Sonarr error: %s", e)
            # A failed source contributes no paths — pruning against this pass
            # would delete that source's entire wanted queue (prod 2026-08-30:
            # a boot-time scan raced an unready Postgres and 9,2k items were
            # wiped). The flag makes the cleanup step below skip this pass.
            self._scan_had_errors = True

        return total_added, total_updated, all_paths

    def _source_answered_empty(self, source: str, instance_name: str, items) -> bool:
        """An empty list from a source that owns wanted rows is an outage.

        Sonarr and Radarr answer ``200 []`` while they are still starting —
        no exception, so the failed-source guard never fires — and on
        2026-09-04 (and 2026-09-01) the boot-time full scan pruned every
        Sonarr row against that empty answer: 11 862 items re-created as
        fresh rows, 619 queued translations dropped. Treat it exactly like a
        raised error: flag the scan, prune nothing, freeze the watermark.
        A genuinely empty source (fresh install, everything removed) owns no
        rows and passes through.
        """
        if items:
            return False
        from db.wanted import get_wanted_count_for_instance

        known = get_wanted_count_for_instance(instance_name)
        if not known:
            return False
        logger.error(
            "Wanted scan: %s (%s) returned 0 items but %d wanted rows belong to it — "
            "treating the source as unavailable, nothing will be pruned "
            "(a source that is still starting answers with an empty list)",
            source,
            instance_name,
            known,
        )
        self._scan_had_errors = True
        return True

    def _scan_sonarr_instance(self, sonarr, settings, instance_name, since=None):
        """Scan a single Sonarr instance."""
        if settings.wanted_anime_only:
            series_list = sonarr.get_anime_series()
        else:
            series_list = sonarr.get_series()
        if self._source_answered_empty("Sonarr", instance_name, series_list):
            return 0, 0, set()

        if since:
            since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
            series_list = [
                s
                for s in series_list
                if (s.get("added") or "") >= since_iso
                or self._episode_files_changed(("sonarr", instance_name, s.get("id")), s)
            ]
            logger.debug(
                "Incremental Sonarr scan: %d series modified since %s",
                len(series_list),
                since_iso,
            )

        total_added = 0
        total_updated = 0
        all_paths = set()

        # Progress is cumulative across instances: the bar spans the whole
        # pass, so this instance adds its item count to the running total
        # instead of restarting it.
        base = self._progress["current"]
        added_base = self._progress["added"]
        updated_base = self._progress["updated"]
        self._progress["total"] = base + len(series_list)
        self._progress["phase"] = "scanning"
        if self._socketio:
            self._socketio.emit("wanted_scan_progress", dict(self._progress))

        yield_ms = getattr(settings, "scan_yield_ms", 0)
        for idx, series in enumerate(series_list, 1):
            series_id = series.get("id")
            if not series_id:
                continue
            key = ("sonarr", instance_name, series_id)
            if self._resumed(key, all_paths):
                continue
            if abort_requested():
                break
            failed = False
            try:
                with batch_upsert_context():
                    a, u, paths = scan_sonarr_series(
                        sonarr,
                        series_id,
                        settings,
                        series,
                        instance_name,
                        auto_extract_fn=self._maybe_auto_extract,
                    )
            except Exception as exc:
                # One title must not cost the rest of the instance — and every
                # later instance — its scan. The outer try in _scan_all_sonarr
                # is for source-level failures; a bug or a transient DB error
                # in a single series would abort the sweep and freeze the
                # watermark for it. Its rows stay: they are absent from this
                # pass's path set, so the pass-end cleanup would delete them.
                failed = True
                a = u = 0
                paths = get_wanted_paths_for_title(sonarr_series_id=series_id)
                logger.warning(
                    "Wanted scan: %s (%s) failed — %s; skipped, its rows are kept",
                    series.get("title") or series_id,
                    instance_name,
                    exc,
                )
            total_added += a
            total_updated += u
            all_paths.update(paths)
            if not failed:
                self._mark_done(key, paths)
                self._episode_fingerprints[key] = _episode_file_stats(series)
            self._progress.update(
                {
                    "current": base + idx,
                    "added": added_base + total_added,
                    "updated": updated_base + total_updated,
                    "current_item": series.get("title") or str(series_id),
                }
            )
            if self._socketio:
                self._socketio.emit("wanted_scan_progress", dict(self._progress))
            if yield_ms > 0:
                time.sleep(yield_ms / 1000.0)

        return total_added, total_updated, all_paths

    def _scan_all_radarr(self, settings, since=None):
        """Scan all Radarr instances. Returns (added, updated, paths)."""
        total_added = 0
        total_updated = 0
        all_paths = set()

        try:
            from config import get_radarr_instances
            from radarr_client import get_radarr_client

            instances = get_radarr_instances()
            for inst in instances:
                instance_name = inst.get("name", "Default")
                radarr = get_radarr_client(instance_name=instance_name)
                if radarr:
                    a, u, paths = self._scan_radarr_instance(radarr, settings, instance_name, since)
                    total_added += a
                    total_updated += u
                    all_paths.update(paths)
        except Exception as e:
            logger.error("Wanted scan: Radarr error: %s", e)
            # See the Sonarr twin above — never prune against a failed source.
            self._scan_had_errors = True

        return total_added, total_updated, all_paths

    def _scan_radarr_instance(self, radarr, settings, instance_name, since=None):
        """Scan a single Radarr instance."""
        if settings.wanted_anime_movies_only:
            movies = radarr.get_anime_movies()
        else:
            movies = radarr.get_movies()
        if self._source_answered_empty("Radarr", instance_name, movies):
            return 0, 0, set()

        if since:
            since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
            movies = [
                m
                for m in movies
                if ((m.get("movieFile") or {}).get("dateAdded") or m.get("added") or "")
                >= since_iso
            ]
            logger.debug(
                "Incremental Radarr scan: %d movies modified since %s",
                len(movies),
                since_iso,
            )

        total_added = 0
        total_updated = 0
        all_paths = set()

        # Cumulative across instances, exactly as the Sonarr twin above.
        base = self._progress["current"]
        added_base = self._progress["added"]
        updated_base = self._progress["updated"]
        self._progress["total"] = base + len(movies)
        self._progress["phase"] = "scanning"
        if self._socketio:
            self._socketio.emit("wanted_scan_progress", dict(self._progress))

        yield_ms = getattr(settings, "scan_yield_ms", 0)
        for idx, movie in enumerate(movies, 1):
            key = ("radarr", instance_name, movie.get("id"))
            if self._resumed(key, all_paths):
                continue
            if abort_requested():
                break
            failed = False
            try:
                with batch_upsert_context():
                    a, u, paths = scan_radarr_movie(
                        radarr,
                        movie,
                        settings,
                        instance_name,
                        auto_extract_fn=self._maybe_auto_extract,
                    )
            except Exception as exc:
                # See the Sonarr twin above: a single movie must not end the
                # instance sweep, and its rows must survive the pass-end
                # cleanup that prunes everything this pass did not see.
                failed = True
                a = u = 0
                paths = get_wanted_paths_for_title(radarr_movie_id=movie.get("id"))
                logger.warning(
                    "Wanted scan: %s (%s) failed — %s; skipped, its rows are kept",
                    movie.get("title") or movie.get("id"),
                    instance_name,
                    exc,
                )
            total_added += a
            total_updated += u
            all_paths.update(paths)
            if not failed:
                self._mark_done(key, paths)
            self._progress.update(
                {
                    "current": base + idx,
                    "added": added_base + total_added,
                    "updated": updated_base + total_updated,
                    "current_item": movie.get("title") or str(movie.get("id")),
                }
            )
            if self._socketio:
                self._socketio.emit("wanted_scan_progress", dict(self._progress))
            if yield_ms > 0:
                time.sleep(yield_ms / 1000.0)

        return total_added, total_updated, all_paths

    def _scan_all_standalone(self):
        """Scan standalone folders. Returns (added, updated, paths)."""
        try:
            from config import is_standalone_mode

            if not is_standalone_mode():
                return 0, 0, set()
        except Exception as e:
            logger.error("Wanted scan: Standalone error: %s", e)
            return 0, 0, set()

        try:
            from standalone.scanner import StandaloneScanner

            if not hasattr(self, "_standalone_scanner"):
                self._standalone_scanner = StandaloneScanner()

            # scan_all_folders walks the enabled folders internally; tick the
            # cumulative pass progress per folder without changing its
            # semantics — one watched folder is its unit, like a series or
            # movie is for the Sonarr/Radarr loops.
            base = self._progress["current"]
            self._progress["phase"] = "scanning"
            try:
                from db.standalone import get_watched_folders

                self._progress["total"] = base + len(get_watched_folders(enabled_only=True))
            except Exception:
                logger.debug("Could not count standalone folders for progress", exc_info=True)
            scan_folder = self._standalone_scanner._scan_folder
            done = 0

            def _ticked_folder(folder):
                nonlocal done
                done += 1
                current = base + done
                # A coalesced extra pass re-walks the folders: grow the total
                # instead of pushing current past it.
                self._progress.update(
                    {
                        "current": current,
                        "total": max(self._progress["total"], current),
                        "current_item": folder.get("path") or folder.get("name") or "standalone",
                    }
                )
                if self._socketio:
                    self._socketio.emit("wanted_scan_progress", dict(self._progress))
                return scan_folder(folder)

            self._standalone_scanner._scan_folder = _ticked_folder
            try:
                summary = self._standalone_scanner.scan_all_folders()
            finally:
                del self._standalone_scanner._scan_folder
            added = summary.get("wanted_added", 0)

            scanned_paths = set()
            try:
                from db import get_db

                db = get_db()
                rows = db.execute(
                    "SELECT file_path FROM wanted_items WHERE instance_name='standalone'"
                ).fetchall()
                scanned_paths = {row[0] for row in rows}
            except Exception as e:
                logger.debug("Could not collect standalone scanned paths: %s", e)

            return added, 0, scanned_paths
        except Exception as e:
            logger.error("Wanted scan: Standalone error: %s", e)
            return 0, 0, set()

    def _maybe_auto_extract(self, item_id: int, file_path: str) -> None:
        """Trigger embedded subtitle extraction for a newly-discovered item.

        0.71.0 routing:
          - If `subtitle_automation_enabled` is on AND we can resolve the
            target_language, enqueue to `subtitle_automation_queue` for the
            drain worker to process asynchronously. Scanner stays fast.
          - Else if `wanted_auto_extract` (legacy) is on, extract inline
            synchronously as before.
          - Else no-op.

        Enqueue failures are logged but never propagate — they must not
        crash the scanner.
        """
        if item_id is None:
            logger.warning("[Auto-Extract] Skipped — item_id is None for %s", file_path)
            return
        try:
            settings = get_settings()
        except Exception:
            logger.warning("[Auto-Extract] settings unavailable for item %d", item_id)
            return

        if getattr(settings, "subtitle_automation_enabled", False) and getattr(
            settings, "subtitle_automation_queue_enabled", True
        ):
            target_lang = _lookup_target_language(item_id)
            if target_lang:
                try:
                    _enqueue_automation(
                        wanted_item_id=item_id,
                        file_path=file_path,
                        target_language=target_lang,
                    )
                    logger.info(
                        "[Auto-Extract] enqueued item %d (%s) for lang=%s",
                        item_id,
                        file_path,
                        target_lang,
                    )
                    return
                except Exception as exc:
                    logger.warning(
                        "[Auto-Extract] enqueue failed for item %d: %s — "
                        "falling through to legacy path",
                        item_id,
                        exc,
                    )
            # Fall through to legacy path if target_lang missing or enqueue
            # raised — better to try inline than to drop the work silently.

        if not getattr(settings, "wanted_auto_extract", False):
            return
        try:
            auto_translate = getattr(settings, "wanted_auto_translate", False)
            logger.info("[Auto-Extract] inline item %d -> %s", item_id, file_path)
            _extract_embedded_sub(item_id, file_path, auto_translate=auto_translate)
        except Exception as exc:
            logger.warning("[Auto-Extract] inline failed for item %d: %s", item_id, exc)
