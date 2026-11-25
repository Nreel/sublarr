"""Job management endpoints — /status/<id>, /jobs, /jobs/<id>/retry."""

import logging
import os

from flask import current_app, jsonify, request

from routes.translate import bp
from routes.translate._helpers import _is_translation_enabled, _run_job
from security_utils import is_safe_path
from services.background_tasks import submit_background

logger = logging.getLogger(__name__)


@bp.route("/status/<job_id>", methods=["GET"])
def job_status(job_id):
    """Get the status of a translation job.
    ---
    get:
      tags:
        - Translate
      summary: Get job status
      description: Returns the current status and result of a translation job.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: job_id
          required: true
          schema:
            type: string
          description: Translation job ID
      responses:
        200:
          description: Job details
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  status:
                    type: string
                    enum: [queued, running, completed, failed]
                  file_path:
                    type: string
                  result:
                    type: object
                    additionalProperties: true
                  error:
                    type: string
        404:
          description: Job not found
    """
    from db.jobs import get_job

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@bp.route("/jobs", methods=["GET"])
def list_jobs():
    """Get paginated job history.
    ---
    get:
      tags:
        - Translate
      summary: List translation jobs
      description: Returns a paginated list of translation jobs with optional status filter.
      security:
        - apiKeyAuth: []
      parameters:
        - in: query
          name: page
          schema:
            type: integer
            default: 1
          description: Page number
        - in: query
          name: per_page
          schema:
            type: integer
            default: 50
            maximum: 200
          description: Items per page
        - in: query
          name: status
          schema:
            type: string
            enum: [queued, running, completed, failed]
          description: Filter by job status
      responses:
        200:
          description: Paginated job list
          content:
            application/json:
              schema:
                type: object
                properties:
                  jobs:
                    type: array
                    items:
                      type: object
                      properties:
                        progress:
                          type: object
                          description: >-
                            Live per-line translation progress from the in-memory
                            QueueState; only present while the job is running.
                          properties:
                            done:
                              type: integer
                            total:
                              type: integer
                            pct:
                              type: number
                            eta_seconds:
                              type: integer
                              nullable: true
                            backend:
                              type: string
                            cost_so_far_micro_usd:
                              type: integer
                            phase:
                              type: string
                              description: >-
                                "translating" while batches are translated,
                                "quality" during the post-translation scoring
                                pass; pct then tracks eval_done, not done.
                            eval_done:
                              type: integer
                              description: >-
                                Lines scored so far during the quality phase.
                  total:
                    type: integer
                  page:
                    type: integer
                  per_page:
                    type: integer
    """
    from db.jobs import get_jobs

    try:
        from utils.pagination import page_args

        page, per_page = page_args(max_per_page=200)
        status_filter = request.args.get("status")
        result = get_jobs(page=page, per_page=per_page, status=status_filter)
        _attach_line_progress(result.get("data", []))
        return jsonify(result)
    except Exception as e:
        logger.exception("GET /jobs failed: %s", e)
        return jsonify({"error": "Internal server error", "detail": "list_jobs_failed"}), 500


def _attach_line_progress(jobs: list) -> None:
    """Merge live per-line progress from QueueState into running job rows.

    ``translator.manager._translate_in_batches`` advances ``done_lines`` per
    finished chunk; the activity tab polls this endpoint, so running jobs carry
    the same progress payload ``GET /translation/queue`` exposes (lingarr-style
    RequestProgress: percent + counters, computed at emit/serialize time, never
    stored in the DB).
    """
    from translation.queue_state import get_queue_state

    snaps = {s["job_id"]: s for s in get_queue_state().active_snapshot()}
    for job in jobs:
        if job.get("status") != "running":
            continue
        snap = snaps.get(job.get("id"))
        if not snap:
            continue
        job["progress"] = {
            "done": snap["progress"]["done"],
            "total": snap["progress"]["total"],
            "pct": snap["progress"]["pct"],
            "eta_seconds": snap["eta_seconds"],
            "backend": snap["backend"],
            "cost_so_far_micro_usd": snap["cost_so_far_micro_usd"],
            "phase": snap["phase"],
            "eval_done": snap["eval_done"],
        }


@bp.route("/jobs/<job_id>", methods=["DELETE"])
def cancel_or_delete_job(job_id):
    """Cancel a queued job or delete a finished one.
    ---
    delete:
      tags:
        - Translate
      summary: Cancel or delete a job
      description: >
        Queued jobs are soft-cancelled (status becomes "cancelled").
        Finished jobs (completed, failed, cancelled) are deleted from history.
        Running jobs cannot be removed and return 409.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: job_id
          required: true
          schema:
            type: string
          description: Job ID to cancel or delete
      responses:
        200:
          description: Job cancelled or deleted
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    enum: [cancelled, deleted]
                  job_id:
                    type: string
        404:
          description: Job not found
        409:
          description: Job is running and cannot be removed
    """
    from db.jobs import cancel_job, delete_job, get_job

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] == "running":
        return jsonify(
            {"error": "Job is running and cannot be cancelled. Wait for it to finish."}
        ), 409

    if job["status"] == "queued":
        if cancel_job(job_id):
            return jsonify({"status": "cancelled", "job_id": job_id})
        # Race: the job left "queued" between the read and the conditional
        # UPDATE. Re-read to decide — running gets a 409, a vanished job a
        # 404, and a terminal status falls through to the delete branch.
        job = get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job["status"] == "running":
            return jsonify(
                {"error": "Job is running and cannot be cancelled. Wait for it to finish."}
            ), 409

    # Terminal statuses (completed, failed, cancelled) — remove from history.
    if not delete_job(job_id):
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"status": "deleted", "job_id": job_id})


@bp.route("/jobs/clear-queued", methods=["POST"])
def clear_queued_jobs_endpoint():
    """Cancel all queued translation jobs.
    ---
    post:
      tags:
        - Translate
      summary: Clear queued jobs
      description: Marks every queued translation job as cancelled. Running jobs are untouched.
      security:
        - apiKeyAuth: []
      responses:
        200:
          description: Number of jobs cancelled
          content:
            application/json:
              schema:
                type: object
                properties:
                  cancelled:
                    type: integer
    """
    from db.jobs import cancel_queued_jobs

    try:
        cancelled = cancel_queued_jobs()
        return jsonify({"cancelled": cancelled})
    except Exception as e:
        logger.exception("POST /jobs/clear-queued failed: %s", e)
        return jsonify({"error": "Internal server error", "detail": "clear_queued_failed"}), 500


@bp.route("/jobs/<job_id>/retry", methods=["POST"])
def retry_job(job_id):
    """Retry a failed job by creating a new translation job.
    ---
    post:
      tags:
        - Translate
      summary: Retry failed job
      description: Creates a new translation job for a previously failed job. Only failed jobs can be retried.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: job_id
          required: true
          schema:
            type: string
          description: Failed job ID to retry
      responses:
        202:
          description: Retry job queued
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  job_id:
                    type: string
                  original_job_id:
                    type: string
                  file_path:
                    type: string
        400:
          description: Job is not in failed status
        404:
          description: Job or file not found
    """
    from config import get_settings
    from db.jobs import create_job, get_job, update_job

    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] != "failed":
        return jsonify({"error": "Only failed jobs can be retried"}), 400

    file_path = job["file_path"]
    if not os.path.exists(file_path):
        return jsonify({"error": f"File not found: {file_path}"}), 404

    # Security: ensure file_path is under the configured media_path
    if not is_safe_path(file_path, get_settings().media_path):
        return jsonify({"error": "file_path must be under the configured media_path"}), 403

    if not _is_translation_enabled():
        return jsonify({"error": "Translation is disabled in configuration"}), 503

    new_job = create_job(file_path, force=True, arr_context=job.get("arr_context"))

    # Prefer the configured job queue: it is sized by the translation
    # concurrency limit (app.py create_job_queue max_workers). Running on the
    # shared background pool bypassed that limit - a retry could stack onto
    # the queue's own backend concurrency and trip provider rate limits.
    queue = getattr(current_app, "job_queue", None)
    if queue is not None:
        try:
            queue.enqueue(_run_job, new_job, job_id=new_job["id"])
        except Exception as exc:
            update_job(new_job["id"], "failed", error=f"Queue unavailable: {exc}")
            logger.warning("Retry enqueue failed for %s: %s", file_path, exc)
            return jsonify({"error": f"Failed to queue retry: {exc}"}), 503
    else:
        _app = current_app._get_current_object()

        def _run_with_ctx():
            with _app.app_context():
                _run_job(new_job)

        try:
            submit_background(_run_with_ctx)
        except Exception as exc:
            update_job(new_job["id"], "failed", error=f"Failed to start retry: {exc}")
            logger.exception("Retry submit failed for %s", file_path)
            return jsonify({"error": f"Failed to start retry: {exc}"}), 503

    return jsonify(
        {
            "status": "queued",
            "job_id": new_job["id"],
            "original_job_id": job_id,
            "file_path": file_path,
        }
    ), 202
