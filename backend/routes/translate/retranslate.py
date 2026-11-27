"""Re-translation endpoints — /retranslate/status, /retranslate/<id>, /retranslate/batch."""

import logging
import os

from flask import current_app, jsonify

from events import emit_event
from extensions import socketio
from routes.translate import bp
from routes.translate._helpers import _is_translation_enabled, _run_job
from security_utils import is_safe_path
from services.background_tasks import submit_background

logger = logging.getLogger(__name__)


@bp.route("/retranslate/status", methods=["GET"])
def retranslate_status():
    """Get re-translation status: current config hash and outdated file count.
    ---
    get:
      tags:
        - Translate
      summary: Get re-translation status
      description: Returns the current translation config hash and count of files translated with an older config.
      security:
        - apiKeyAuth: []
      responses:
        200:
          description: Re-translation status
          content:
            application/json:
              schema:
                type: object
                properties:
                  current_hash:
                    type: string
                  outdated_count:
                    type: integer
                  ollama_model:
                    type: string
                  target_language:
                    type: string
    """
    from config import get_settings
    from db.jobs import get_outdated_jobs_count

    s = get_settings()
    current_hash = s.get_translation_config_hash()
    # Per-backend comparison (see _is_outdated): a plain-hash comparison
    # against the default backend's hash counted every non-default-backend
    # job as outdated forever.
    outdated = get_outdated_jobs_count(
        lambda backend_name: s.get_translation_config_hash(backend_name=backend_name)
    )

    return jsonify(
        {
            "current_hash": current_hash,
            "outdated_count": outdated,
            "ollama_model": s.ollama_model,
            "target_language": s.target_language,
        }
    )


@bp.route("/retranslate/<job_id>", methods=["POST"])
def retranslate_single(job_id):
    """Re-translate a single item (deletes old sub, forces re-translation).
    ---
    post:
      tags:
        - Translate
      summary: Re-translate single item
      description: Deletes existing translated subtitle and forces re-translation with current config. Accepts job ID or wanted item ID.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: job_id
          required: true
          schema:
            type: string
          description: Translation job ID (uuid hex) or wanted item ID (integer)
      responses:
        202:
          description: Re-translation started
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  job_id:
                    type: string
                  file_path:
                    type: string
        404:
          description: Item or file not found
    """
    from config import get_settings
    from db.jobs import create_job, get_job, update_job
    from db.wanted import get_wanted_item

    wanted_item = None
    # Job IDs are uuid hex strings; wanted item IDs are integers. The old
    # <int:...> converter made /retranslate/<uuid-hex> a permanent 404 —
    # re-translating a completed job (the primary UI action) was dead.
    job = get_job(job_id)
    if not job:
        # Try as wanted item ID
        try:
            wanted_item = get_wanted_item(int(job_id))
        except ValueError:
            wanted_item = None
        if not wanted_item:
            return jsonify({"error": "Item not found"}), 404
        from services.standalone_library import wanted_item_path_refusal

        refusal = wanted_item_path_refusal(wanted_item)
        if refusal:
            return jsonify({"error": refusal}), 400
        file_path = wanted_item["file_path"]
    else:
        file_path = job["file_path"]

    # Security first: ensure file_path is under the configured media_path.
    # Checked before existence, so a 404 never confirms a path outside
    # media_path (same ordering as /translate).
    if not is_safe_path(file_path, get_settings().media_path):
        return jsonify({"error": "file_path must be under the configured media_path"}), 403

    if not os.path.exists(file_path):
        return jsonify({"error": f"File not found: {file_path}"}), 404

    if not _is_translation_enabled():
        return jsonify({"error": "Translation is disabled in configuration"}), 503

    # The language to replace: the wanted row's own, else the one the profile
    # governing the file resolves to — never the hidden global default (#254).
    from translator.target_resolution import (
        TRANSLATE_TO_KEY,
        resolve_translation_target,
        target_sidecar_patterns,
    )

    if wanted_item and wanted_item.get("target_language"):
        from config_language_data import normalize_language_code

        # Canonicalize legacy aliases ("ger" -> "de"): the sidecar delete
        # patterns and the translate_to stamp below key off this code.
        target_code = normalize_language_code(wanted_item["target_language"])
    else:
        target_code = resolve_translation_target(file_path, (job or {}).get("arr_context")).code

    # Re-translate with force. Stale target sidecars are removed only AFTER
    # the new translation succeeds (inside _run): deleting them here meant a
    # failed re-translation left the file with no target subtitle at all —
    # the previous good translation destroyed by a transient backend error.
    context = dict((job or {}).get("arr_context") or {})
    if wanted_item:
        from wanted_search.process import _build_arr_context

        context.update(_build_arr_context(wanted_item))
    context[TRANSLATE_TO_KEY] = target_code
    new_job = create_job(file_path, force=True, arr_context=context)
    _app = current_app._get_current_object()

    def _run():
        with _app.app_context():
            result = _run_job(new_job)
            if result and result.get("success"):
                # Remove target sidecars the forced re-translation did not
                # overwrite (e.g. the file switched .en.srt -> .en.ass).
                # After success only: see the note above the create_job call.
                base = os.path.splitext(file_path)[0]
                fresh = result.get("output_path")
                for fmt in ["ass", "srt"]:
                    for pattern in target_sidecar_patterns(target_code, fmt):
                        stale = base + pattern
                        if os.path.exists(stale) and stale != fresh:
                            os.remove(stale)
                            logger.info("Re-translate: removed stale %s", stale)
            # When called with a wanted-item ID (not an existing job ID), the
            # wanted row must be resolved on success — otherwise it sits in
            # "wanted" forever even though its target subtitle now exists on
            # disk (this was reachable in prod: /retranslate never touched
            # wanted_items at all). Reuses the same finalize helper the
            # /wanted/batch-translate path already relies on, so both entry
            # points flag MT output and set provisional status identically.
            if wanted_item:
                from services.retranslation import _finalize_retranslation

                _finalize_retranslation(wanted_item["id"], wanted_item, target_code, result)
            emit_event(
                "translation_complete",
                {
                    "file_path": file_path,
                    "job_id": new_job["id"],
                },
            )

    # Prefer the configured job queue — it is sized by the translation
    # concurrency limit; the shared background pool bypassed it (same fix as
    # /jobs/<id>/retry).
    queue = getattr(current_app, "job_queue", None)
    if queue is not None:
        try:
            queue.enqueue(_run, new_job, job_id=new_job["id"])
        except Exception as exc:
            update_job(new_job["id"], "failed", error="Queue unavailable")
            logger.warning("Re-translate enqueue failed for %s: %s", file_path, exc)
            return jsonify({"error": "Failed to queue re-translation"}), 503
    else:
        try:
            submit_background(_run)
        except Exception:
            update_job(new_job["id"], "failed", error="Failed to start")
            logger.exception("Re-translate submit failed for %s", file_path)
            return jsonify({"error": "Failed to start re-translation"}), 503

    return jsonify(
        {
            "status": "started",
            "job_id": new_job["id"],
            "file_path": file_path,
        }
    ), 202


@bp.route("/retranslate/batch", methods=["POST"])
def retranslate_batch():
    """Re-translate all outdated items (async with WebSocket progress).
    ---
    post:
      tags:
        - Translate
      summary: Batch re-translate outdated items
      description: >
        Re-translates all items that were translated with an older config hash.
        Progress is emitted via WebSocket (retranslation_progress event).
      security:
        - apiKeyAuth: []
      responses:
        200:
          description: Nothing to re-translate
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  count:
                    type: integer
        202:
          description: Batch re-translation started
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  total:
                    type: integer
    """
    from config import get_settings
    from db.jobs import get_outdated_jobs, record_stat, update_job
    from routes.batch_state import (
        begin_run,
        retranslate_batch_state,
        retranslate_lock,
    )
    from services.translation_jobs import update_stats
    from translator import translate_file
    from translator.target_resolution import resolve_translation_target, target_sidecar_patterns

    if not _is_translation_enabled():
        return jsonify({"error": "Translation is disabled in configuration"}), 503

    s = get_settings()
    # The stamped hash embeds the backend that produced each job; outdated
    # is therefore decided per backend (see JobRepository._is_outdated).
    # Fetch every candidate, not the repository default page of 100: with
    # more than 100 outdated jobs the run silently processed 100, the
    # progress total lied about the rest, and the UI looped forever
    # showing a stale count.
    outdated = get_outdated_jobs(
        lambda backend_name: s.get_translation_config_hash(backend_name=backend_name),
        limit=10_000,
    )

    if not outdated:
        return jsonify({"status": "nothing_to_do", "count": 0})

    with retranslate_lock:
        if retranslate_batch_state["running"]:
            return jsonify({"error": "Re-translation batch already running"}), 409
        retranslate_batch_state.update(
            {
                "running": True,
                "total": len(outdated),
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "current_file": None,
            }
        )
        begin_run(retranslate_batch_state)

    total = len(outdated)
    _app = current_app._get_current_object()

    def _run_retranslate():
        with _app.app_context():
            processed = 0
            succeeded = 0
            failed = 0

            from services.standalone_library import wanted_item_path_refusal

            try:
                for job in outdated:
                    if retranslate_batch_state["cancel_event"].is_set():
                        break
                    file_path = job["file_path"]
                    context = job.get("arr_context") or {}
                    if wanted_item_path_refusal({**context, "file_path": file_path}):
                        processed += 1
                        failed += 1
                        record_stat(success=False)
                        continue
                    if not os.path.exists(file_path):
                        processed += 1
                        failed += 1
                        record_stat(success=False)
                        continue

                    # The language this file's profile translates into (#254).
                    target = resolve_translation_target(file_path, context)

                    try:
                        result = translate_file(
                            file_path,
                            force=True,
                            arr_context=context or None,
                            target_language=target.code,
                            target_language_name=target.name,
                        )
                    except Exception as e:
                        processed += 1
                        failed += 1
                        record_stat(success=False)
                        logger.warning("Re-translate batch: error on %s: %s", file_path, e)
                        result = None

                    if result is not None:
                        processed += 1
                        # Daily stats must see these runs too: before this
                        # the batch path updated job rows but never
                        # daily_stats, so re-translation spend was invisible
                        # in /stats while real API/LLM cost accrued.
                        update_stats(result)
                        if result["success"]:
                            succeeded += 1
                            stats = result.get("stats") or {}
                            output_path = result.get("output_path")
                            # Remove stale target sidecars only AFTER the new
                            # translation succeeded: deleting before the run
                            # meant a failed re-translation destroyed the
                            # only good subtitle on disk.
                            base = os.path.splitext(file_path)[0]
                            for fmt in ["ass", "srt"]:
                                for pattern in target_sidecar_patterns(target.code, fmt):
                                    stale = base + pattern
                                    if os.path.exists(stale) and stale != output_path:
                                        os.remove(stale)
                            # Refresh the original outdated job row so it
                            # leaves the outdated set. translate_file stamps
                            # the current config_hash into result["stats"] on
                            # success; without writing it back to the job,
                            # get_outdated_jobs keeps returning this same job
                            # forever and outdated_count never decrements
                            # (bug found 2026-07-08). Mirrors
                            # services.translation_jobs.run_job's update_job
                            # call.
                            job_id = job.get("id")
                            if job_id:
                                update_job(job_id, "completed", result=result)
                            # A successful, non-skipped translation must be
                            # flagged the same way every other translate-
                            # completion site does (retranslate_single,
                            # wanted_search) -- otherwise it produces no
                            # History entry at all (bug found 2026-07-08).
                            if output_path and not stats.get("skipped"):
                                from services.mt_provisional import record_mt_output

                                out_fmt = stats.get("format") or (
                                    "ass" if output_path.endswith(".ass") else "srt"
                                )
                                record_mt_output(file_path, output_path, target.code, out_fmt)
                        else:
                            failed += 1

                    with retranslate_lock:
                        retranslate_batch_state.update(
                            {
                                "processed": processed,
                                "succeeded": succeeded,
                                "failed": failed,
                                "current_file": file_path,
                            }
                        )

                    socketio.emit(
                        "retranslation_progress",
                        {
                            "processed": processed,
                            "total": total,
                            "succeeded": succeeded,
                            "failed": failed,
                            "current_file": file_path,
                        },
                    )

                emit_event(
                    "translation_complete",
                    {
                        "count": processed,
                        "succeeded": succeeded,
                        "failed": failed,
                    },
                )
            finally:
                with retranslate_lock:
                    retranslate_batch_state.update(
                        {"running": False, "current_file": None, "started_at": None}
                    )

    try:
        submit_background(_run_retranslate)
    except Exception:
        # Runner never started: release the guard flag, or /retranslate/batch
        # is bricked with 409 until restart.
        with retranslate_lock:
            retranslate_batch_state.update(
                {
                    "running": False,
                    "started_at": None,
                    "total": 0,
                    "processed": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "current_file": None,
                }
            )
        logger.exception("Re-translate batch: submit to background worker failed")
        return jsonify({"error": "Failed to start re-translation batch"}), 503

    return jsonify(
        {
            "status": "started",
            "total": total,
        }
    ), 202


@bp.route("/retranslate/batch/cancel", methods=["POST"])
def cancel_retranslate_batch():
    """Stop the running re-translation batch.
    ---
    post:
      tags:
        - Translate
      summary: Cancel re-translation batch
      description: >
        Sets the cancellation event checked between jobs of the running
        re-translation batch. The in-flight job finishes first; the rest are
        never started. Nothing about schedules changes.
      security:
        - apiKeyAuth: []
      responses:
        202:
          description: Cancellation requested
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
        409:
          description: No re-translation batch running
    """
    from routes.batch_state import request_cancel, retranslate_batch_state, retranslate_lock

    with retranslate_lock:
        if not request_cancel(retranslate_batch_state):
            return jsonify({"error": "Re-translation batch is not running"}), 409
    return jsonify({"status": "cancelling"}), 202
