"""Blueprint exposing Jellyfin user information."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ..jellyfin_client import jf_get
from ..services.jellyfin import resolve_jellyfin_config, validate_base

bp = Blueprint("users", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/users", methods=["POST"])
def api_users():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = validate_base(base, "/api/users", data.get("base"))
    logger.info("POST /api/users base=%s", base or "")
    if error is not None:
        return error
    users = jf_get(f"{base}/Users", api_key)
    logger.info("/api/users fetched %d users", len(users))
    return jsonify(users)
