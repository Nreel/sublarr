"""Service-listing + CRUD + connection-test endpoints for API keys."""

from __future__ import annotations

import logging
import os

from flask import jsonify, request

from routes.api_keys import bp
from routes.api_keys.helpers import (
    API_KEY_REGISTRY,
    _get_service_info,
    _mask_value,
    _reveal_values,
)
from routes.api_keys.testing import _TEST_DISPATCH

logger = logging.getLogger(__name__)


@bp.route("/", methods=["GET"])
def list_services():
    """List all registered services with their API key status.
    ---
    get:
      tags:
        - API Keys
      summary: List all services
      description: Returns all registered services with key status and masked values.
      security:
        - apiKeyAuth: []
      responses:
        200:
          description: List of services
          content:
            application/json:
              schema:
                type: object
                properties:
                  services:
                    type: array
                    items:
                      type: object
    """
    services = []
    for name in API_KEY_REGISTRY:
        info = _get_service_info(name)
        if info is not None:
            services.append(info)
    return jsonify({"services": services})


@bp.route("/<service>", methods=["GET"])
def get_service(service):
    """Get detailed status for a single service.
    ---
    get:
      tags:
        - API Keys
      summary: Get service detail
      description: Returns key status and masked values for a single service.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: service
          required: true
          schema:
            type: string
      responses:
        200:
          description: Service detail
        404:
          description: Service not found
    """
    info = _get_service_info(service)
    if info is None:
        return jsonify({"error": f"Service '{service}' not found"}), 404
    return jsonify(info)


@bp.route("/<service>/reveal", methods=["GET"])
def reveal_service_keys(service):
    """Return the unmasked key values for a service.
    ---
    get:
      tags:
        - API Keys
      summary: Reveal service keys
      description: >
        Returns the full values the server actually accepts, for the settings UI's
        reveal/copy affordance. Reachable only by callers that already passed the
        API-key or UI-session gate applied to every /api/ route.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: service
          required: true
          schema:
            type: string
      responses:
        200:
          description: Unmasked key values
          content:
            application/json:
              schema:
                type: object
                properties:
                  service:
                    type: string
                  keys:
                    type: array
                    items:
                      type: object
                      properties:
                        name:
                          type: string
                        value:
                          type: string
        404:
          description: Service not found
    """
    info = _reveal_values(service)
    if info is None:
        return jsonify({"error": f"Service '{service}' not found"}), 404
    return jsonify(info)


@bp.route("/<service>", methods=["PUT"])
def update_service_keys(service):
    """Update API keys for a service and invalidate caches.
    ---
    put:
      tags:
        - API Keys
      summary: Update service keys
      description: >
        Saves new key values for a service, invalidates related caches,
        and returns updated service info.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: service
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              additionalProperties:
                type: string
      responses:
        200:
          description: Keys updated
        400:
          description: No data provided
        404:
          description: Service not found
    """
    entry = API_KEY_REGISTRY.get(service)
    if entry is None:
        return jsonify({"error": f"Service '{service}' not found"}), 404

    data = request.get_json() or {}
    if not data:
        return jsonify({"error": "No key data provided"}), 400

    from config import reload_settings
    from db.config import get_all_config_entries, save_config_entry

    saved_keys = []
    for key_name in entry["keys"]:
        if key_name not in data:
            continue
        val = str(data[key_name]).strip()
        # A masked display value ("abcd***wxyz") is not a credential — saving it
        # would replace the real key with a string auth rejects, silently.
        if "***" in val:
            return jsonify(
                {"error": f"'{key_name}' looks masked; paste the full key or use Reveal"}
            ), 400
        save_config_entry(key_name, val)
        saved_keys.append(key_name)

    # Reload settings so new values take effect
    all_overrides = get_all_config_entries()
    reload_settings(all_overrides)

    # Service-specific invalidation
    _invalidate_for_service(service)

    logger.info("API keys updated for service '%s': %s", service, saved_keys)

    info = _get_service_info(service)
    return jsonify(
        {
            "status": "updated",
            "updated_keys": saved_keys,
            "service": info,
        }
    )


@bp.route("/<service>/rotate", methods=["POST"])
def rotate_service_key(service):
    """Generate a new key for a single-credential service.
    ---
    post:
      tags:
        - API Keys
      summary: Rotate service key
      description: >
        Writes a fresh 64-hex key into config_entries and reloads settings so it
        takes effect immediately. The raw value is not returned — read it back via
        /reveal. Refused with 409 for the Sublarr key when SUBLARR_API_KEY is set:
        the environment variable is the deployment credential and would win at the
        next restart, so rotation there would break external integrations.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: service
          required: true
          schema:
            type: string
      responses:
        200:
          description: Key rotated
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                  key:
                    type: string
                  masked_value:
                    type: string
        400:
          description: Service has multiple credentials
        404:
          description: Service not found
        409:
          description: Key is fixed by the environment
    """
    entry = API_KEY_REGISTRY.get(service)
    if entry is None:
        return jsonify({"error": f"Service '{service}' not found"}), 404

    if len(entry["keys"]) != 1:
        return jsonify(
            {"error": f"Service '{service}' has multiple credentials; set them individually"}
        ), 400

    key_name = entry["keys"][0]
    if service == "sublarr" and os.environ.get("SUBLARR_API_KEY"):
        return jsonify(
            {
                "error": (
                    "The Sublarr API key is set via SUBLARR_API_KEY, which wins on restart. "
                    "Change the environment variable and restart instead."
                )
            }
        ), 409

    import secrets

    new_key = secrets.token_hex(32)
    from config import reload_settings
    from db.config import get_all_config_entries, save_config_entry

    save_config_entry(key_name, new_key)
    reload_settings(get_all_config_entries())
    _invalidate_for_service(service)

    logger.info("API key rotated for service '%s'", service)
    return jsonify(
        {
            "status": "rotated",
            "key": key_name,
            "masked_value": _mask_value(new_key),
            "service": _get_service_info(service),
        }
    )


def _invalidate_for_service(service: str):
    """Invalidate singleton caches relevant to a service."""
    try:
        if service == "sonarr":
            from sonarr_client import invalidate_client

            invalidate_client()
        elif service == "radarr":
            from radarr_client import invalidate_client

            invalidate_client()
        elif service == "apprise":
            from notifier import invalidate_notifier

            invalidate_notifier()
        elif service in ("opensubtitles", "jimaku", "subdl"):
            from providers import invalidate_manager

            invalidate_manager()
        elif service == "deepl":
            try:
                from translation import invalidate_translation_manager

                invalidate_translation_manager()
            except ImportError:
                pass
    except Exception as exc:
        logger.warning("Failed to invalidate cache for service '%s': %s", service, exc)


@bp.route("/<service>/test", methods=["POST"])
def test_service(service):
    """Test connection for a service.
    ---
    post:
      tags:
        - API Keys
      summary: Test service connection
      description: Tests the configured API key for a service by performing a connectivity check.
      security:
        - apiKeyAuth: []
      parameters:
        - in: path
          name: service
          required: true
          schema:
            type: string
      responses:
        200:
          description: Test result
          content:
            application/json:
              schema:
                type: object
                properties:
                  success:
                    type: boolean
                  message:
                    type: string
        404:
          description: Service not found
        400:
          description: Service has no test function
    """
    entry = API_KEY_REGISTRY.get(service)
    if entry is None:
        return jsonify({"error": f"Service '{service}' not found"}), 404

    test_fn_name = entry.get("test_fn")
    if test_fn_name is None:
        return jsonify({"error": f"Service '{service}' does not support connection testing"}), 400

    test_fn = _TEST_DISPATCH.get(test_fn_name)
    if test_fn is None:
        return jsonify({"error": "Test function not found"}), 500

    # Provider test functions need the service name
    if test_fn_name == "_test_provider":
        result = test_fn(service)
    else:
        result = test_fn()

    return jsonify(result)
