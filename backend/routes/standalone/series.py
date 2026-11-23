"""Standalone series endpoints: list, detail, poster, delete, scan, metadata refresh."""

from __future__ import annotations

import logging

from flask import current_app, jsonify, redirect, send_file

from extensions import limiter
from routes.standalone import bp

logger = logging.getLogger(__name__)


@bp.route("/series", methods=["GET"])
def list_series():
    """List all standalone series with episode counts and wanted counts.
    ---
    get:
      security:
        - apiKeyAuth: []
      tags:
        - Standalone
      summary: List standalone series
      description: Returns all standalone series with episode counts and the number of wanted subtitle items.
      responses:
        200:
          description: List of standalone series
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
        500:
          description: Server error
    """
    from db.standalone import get_standalone_series
    from services.standalone_manager import enrich_series_list

    try:
        series_list = get_standalone_series()
        return jsonify(enrich_series_list(series_list))
    except Exception as e:
        logger.error("Failed to list standalone series: %s", e)
        return jsonify({"error": "Failed to list standalone series"}), 500


@bp.route("/series/<int(signed=True):series_id>", methods=["GET"])
def get_series(series_id):
    """Get a single standalone series with its files and wanted status.
    ---
    get:
      security:
        - apiKeyAuth: []
      tags:
        - Standalone
      summary: Get standalone series detail
      description: Returns a single standalone series with its associated wanted items.
      parameters:
        - in: path
          name: series_id
          required: true
          schema:
            type: integer
      responses:
        200:
          description: Series with wanted items
          content:
            application/json:
              schema:
                type: object
        404:
          description: Series not found
        500:
          description: Server error
    """
    from db.standalone import get_standalone_series
    from services.standalone_manager import enrich_series_detail

    try:
        series = get_standalone_series(series_id)
        if not series:
            return jsonify({"error": "Series not found"}), 404

        return jsonify(enrich_series_detail(series, series_id))
    except Exception as e:
        logger.error("Failed to get standalone series %d: %s", series_id, e)
        return jsonify({"error": "Failed to get standalone series"}), 500


@bp.route("/series/<int(signed=True):series_id>/poster", methods=["GET"])
@limiter.limit("120/minute")
def series_poster(series_id):
    """Serve the local poster image for a standalone series.

    Returns the local poster.jpg/poster.png found in the series folder
    during scanning. Falls back to 404 if no local poster is stored.
    """
    from db.standalone import get_standalone_series
    from services.standalone_manager import resolve_poster_path

    series = get_standalone_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404

    poster_path, error, status = resolve_poster_path(
        series, folder_key="folder_path", use_parent=False
    )
    if error:
        return jsonify({"error": error}), status

    if poster_path.startswith(("http://", "https://")):
        return redirect(poster_path)

    try:
        return send_file(poster_path)
    except Exception as e:
        logger.error("Failed to serve poster for series %d: %s", series_id, e)
        return jsonify({"error": "Failed to serve poster"}), 500


@bp.route("/series/<int(signed=True):series_id>", methods=["DELETE"])
def delete_series(series_id):
    """Delete a standalone series and its wanted items.
    ---
    delete:
      security:
        - apiKeyAuth: []
      tags:
        - Standalone
      summary: Delete standalone series
      description: Deletes a standalone series and cascades to remove associated wanted items.
      parameters:
        - in: path
          name: series_id
          required: true
          schema:
            type: integer
      responses:
        200:
          description: Series deleted
          content:
            application/json:
              schema:
                type: object
                properties:
                  success:
                    type: boolean
        404:
          description: Series not found
        500:
          description: Server error
    """
    from db.standalone import get_standalone_series
    from services.standalone_manager import delete_series_cascade

    series = get_standalone_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404

    try:
        delete_series_cascade(series_id)
        return jsonify({"success": True})
    except Exception as e:
        logger.error("Failed to delete standalone series %d: %s", series_id, e)
        return jsonify({"error": "Failed to delete standalone series"}), 500


@bp.route("/series/<int(signed=True):series_id>/scan", methods=["POST"])
def scan_series(series_id):
    """Trigger a re-scan of a single standalone series.
    ---
    post:
      security:
        - apiKeyAuth: []
      tags:
        - Standalone
      summary: Re-scan standalone series
      description: Triggers a re-scan of file contents for a single standalone series.
      parameters:
        - in: path
          name: series_id
          required: true
          schema:
            type: integer
      responses:
        200:
          description: Scan started
          content:
            application/json:
              schema:
                type: object
                properties:
                  message:
                    type: string
                  series_id:
                    type: integer
        404:
          description: Series not found
        409:
          description: Scan already running
        500:
          description: Scan failed
        502:
          description: Scan broke (bad Sonarr response, folder unreadable)
    """
    from db.standalone import get_standalone_series
    from db.wanted import record_series_scan_failure
    from services.media_ids import resolve_series_ref
    from services.standalone_manager import scan_series_or_fallback

    ref = resolve_series_ref(series_id)

    try:
        if ref.is_standalone:
            if not get_standalone_series(ref.id):
                return jsonify({"error": "Series not found"}), 404
            summary = scan_series_or_fallback(ref.id)
        else:
            # A positive id here is a Sonarr series. The standalone scanner keys its
            # rows by positive DB ids, so this route used to look the request id up
            # in standalone_series and 404 every Sonarr re-scan (and every negative
            # wire id, whose row is -id). The signed-aware scanner handles both.
            from services.wanted_scanner import get_scanner

            scanner = get_scanner()
            if scanner.is_scanning:
                return jsonify({"error": "Scan already running"}), 409
            summary = scanner.scan_series(series_id)
    except Exception as e:
        logger.exception("Failed to scan series %s: %s", series_id, e)
        record_series_scan_failure(
            ref.id, standalone=ref.is_standalone, message=f"scan crashed: {e}"
        )
        return jsonify({"error": "Internal server error"}), 500

    scan_error = (summary or {}).get("error")
    if scan_error:
        # The scanner swallows failures into a summary dict, which used to be
        # answered 200: the UI said "Re-scan started" while nothing had run, and
        # /health stayed silent because no item carried an error. Charge the
        # series' open items so the failure lands under "Failed & unmatched items".
        # ``ref.id`` is the id the wanted rows are keyed by: the standalone row id
        # (positive) or the Sonarr series id.
        record_series_scan_failure(ref.id, standalone=ref.is_standalone, message=str(scan_error))
        logger.warning("Series re-scan %s failed: %s", series_id, scan_error)
        return jsonify({"error": str(scan_error), "series_id": series_id}), 502

    response = {"message": "Scan completed", "series_id": series_id}
    if summary:
        response["summary"] = summary
    return jsonify(response), 200


@bp.route("/series/<int(signed=True):series_id>/refresh-metadata", methods=["POST"])
def refresh_series_metadata(series_id):
    """Re-resolve metadata for a standalone series in the background.

    Schedules a TMDB/AniList/TVDB lookup off the request thread and
    returns 202 immediately so the Flask worker pool stays free even
    when external APIs are slow or rate-limiting. The UI polls the
    series detail endpoint to pick up the refreshed data.
    ---
    post:
      security:
        - apiKeyAuth: []
      tags:
        - Standalone
      summary: Refresh series metadata (async)
      description: Schedules an asynchronous metadata refresh for a standalone series. Returns 202 once accepted; the result lands on the next series detail fetch.
      parameters:
        - in: path
          name: series_id
          required: true
          schema:
            type: integer
      responses:
        202:
          description: Refresh accepted
          content:
            application/json:
              schema:
                type: object
                properties:
                  success:
                    type: boolean
                  series_id:
                    type: integer
                  message:
                    type: string
        404:
          description: Series not found
        500:
          description: Server error
    """
    from db.standalone import get_standalone_series
    from services.standalone_manager import refresh_series_metadata_async

    series = get_standalone_series(series_id)
    if not series:
        return jsonify({"error": "Series not found"}), 404

    try:
        app = current_app._get_current_object()
        refresh_series_metadata_async(app, series_id)
        return jsonify(
            {
                "success": True,
                "series_id": series_id,
                "message": "Metadata refresh scheduled",
            }
        ), 202
    except Exception as e:
        logger.error("Failed to schedule metadata refresh for series %d: %s", series_id, e)
        return jsonify({"error": "Failed to schedule metadata refresh"}), 500
