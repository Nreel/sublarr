"""GET /api/v1/health/library — library health overview for the Health page."""

import logging

from flask import jsonify

from routes.system import bp

logger = logging.getLogger(__name__)


@bp.route("/health/library", methods=["GET"])
def health_library():
    """Library health overview.

    Deliberately not response-cached: this is the live "where does it hurt"
    view, and a cached body hides failures recorded after the cache was
    written. The Health page polls it once a minute; the read is bounded
    (7-day window, per-section row caps).
    ---
    get:
      tags:
        - System
      summary: Library health overview
      description: >
        Aggregated "where does it hurt" view: wanted items carrying an error
        (failed outright, classified with a failure kind, or holding a
        recorded error note — including unmatched/unsourceable episodes),
        per-provider health derived from circuit-breaker states and provider
        statistics, and translation-pipeline health (per-backend failure
        counters and the most recent failed translation calls). Per-title
        roll-ups live on /wanted.
      security:
        - apiKeyAuth: []
      responses:
        200:
          description: Health overview
          content:
            application/json:
              schema:
                type: object
                properties:
                  totals:
                    type: object
                    additionalProperties:
                      type: integer
                  problems:
                    type: array
                    items:
                      type: object
                  providers:
                    type: array
                    items:
                      type: object
                  translation:
                    type: object
                    properties:
                      failures_7d:
                        type: integer
                      stuck_items:
                        type: integer
                      backends:
                        type: array
                        items:
                          type: object
                      recent_errors:
                        type: array
                        items:
                          type: object
                      pipeline_errors:
                        type: array
                        items:
                          type: object
    """
    from services.health_overview import get_library_health

    return jsonify(get_library_health())
