"""Blueprint for tag discovery endpoints."""

from __future__ import annotations

import logging

import time

from flask import Blueprint, jsonify, request

from ..services.jellyfin import resolve_jellyfin_config, validate_base
from ..services.items import normalize_item_types
from ..services.tags import (
    ensure_tag_cache_refresh,
    get_tag_cache_snapshot,
    get_tag_progress,
    is_refresh_in_progress,
    is_tag_cache_stale,
)

bp = Blueprint("tags", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/tags", methods=["POST"])
def api_tags():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    validated_base, error = validate_base(base, "/api/tags", data.get("base"))
    raw_lib_id = data.get("libraryId")
    raw_user_id = data.get("userId")
    lib_id = str(raw_lib_id).strip() if raw_lib_id is not None else ""
    user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
    include_types = normalize_item_types(data.get("types"))
    logger.info(
        "POST /api/tags base=%s library=%s user=%s include_types=%s",
        validated_base or "",
        lib_id,
        user_id,
        include_types,
    )
    if error is not None:
        return error
    assert validated_base is not None
    base = validated_base

    if not lib_id:
        logger.warning("POST /api/tags missing required libraryId (raw=%r)", raw_lib_id)
        return jsonify({"error": "libraryId is required"}), 400

    entry = get_tag_cache_snapshot(base, lib_id, user_id, include_types)
    needs_refresh = not entry or is_tag_cache_stale(entry)
    refreshing = is_refresh_in_progress(base, lib_id, user_id, include_types)
    if needs_refresh and not refreshing:
        ensure_tag_cache_refresh(base, api_key, user_id, lib_id, include_types)
        refreshing = True

    wait_deadline = time.time() + 5
    while time.time() < wait_deadline:
        entry = get_tag_cache_snapshot(base, lib_id, user_id, include_types)
        if entry and entry.tags:
            break
        refreshing = is_refresh_in_progress(base, lib_id, user_id, include_types)
        if not refreshing:
            if needs_refresh:
                ensure_tag_cache_refresh(base, api_key, user_id, lib_id, include_types)
                refreshing = True
            else:
                break
        time.sleep(0.5)

    if entry and entry.tags:
        logger.info(
            "POST /api/tags returning %d tags via %s (cached=%s)",
            len(entry.tags),
            entry.source,
            entry.loading,
        )
        return jsonify(
            {
                "tags": entry.tags,
                "source": entry.source,
                "cached": True,
                "loading": entry.loading,
                "lastUpdated": entry.updated,
            }
        )

    message = (
        entry.error
        if entry and entry.error
        else "Gathering tags, please try again shortly."
    )
    logger.info(
        "POST /api/tags cache pending for lib=%s user=%s include_types=%s",
        lib_id,
        user_id,
        include_types,
    )
    return jsonify({"status": "pending", "message": message}), 202


@bp.route("/tags/status", methods=["POST"])
def api_tag_status():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    raw_lib_id = data.get("libraryId")
    raw_user_id = data.get("userId")
    lib_id = str(raw_lib_id).strip() if raw_lib_id is not None else ""
    user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
    include_types = normalize_item_types(data.get("types"))
    entry = get_tag_cache_snapshot(base, lib_id, user_id, include_types)
    progress = get_tag_progress(base, lib_id, user_id, include_types)
    response = {
        "loading": bool(entry and entry.loading),
        "processed": progress.get("processed", 0),
        "pages": progress.get("pages", 0),
        "lastUpdated": entry.updated if entry else None,
    }
    return jsonify(response)
