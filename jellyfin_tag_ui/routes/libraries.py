"""Blueprint exposing Jellyfin library information."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ..jellyfin_client import jf_get
from ..services.jellyfin import resolve_jellyfin_config, validate_base

bp = Blueprint("libraries", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/libraries", methods=["POST"])
def api_libraries():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = validate_base(base, "/api/libraries", data.get("base"))
    logger.info("POST /api/libraries base=%s", base or "")
    if error is not None:
        return error
    libs = jf_get(f"{base}/Library/VirtualFolders", api_key)
    logger.info("/api/libraries fetched %d libraries", len(libs))
    return jsonify(libs)
