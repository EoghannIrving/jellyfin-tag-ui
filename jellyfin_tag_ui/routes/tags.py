"""Blueprint for tag discovery endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from ..services.jellyfin import resolve_jellyfin_config, validate_base
from ..services.items import normalize_item_types
from ..services.tags import (
    aggregate_tags_from_items,
    collect_paginated_tags,
    sorted_tag_names,
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

    params: Dict[str, Any] = {"ParentId": lib_id, "Recursive": "true"}
    if include_types:
        params["IncludeItemTypes"] = ",".join(include_types)

    if user_id:
        try:
            tag_counts, canonical_names = collect_paginated_tags(
                f"{base}/Users/{user_id}/Items/Tags",
                api_key,
                params,
            )
            names = sorted_tag_names(tag_counts, canonical_names)
            logger.info(
                "/api/tags returning %d tags via users-items-tags endpoint", len(names)
            )
            return jsonify({"tags": names, "source": "users-items-tags"})
        except Exception:
            logger.exception(
                "User-scoped tags endpoint failed; falling back to global endpoint",
            )

    try:
        tag_counts, canonical_names = collect_paginated_tags(
            f"{base}/Items/Tags",
            api_key,
            params,
        )
        names = sorted_tag_names(tag_counts, canonical_names)
        logger.info("/api/tags returning %d tags via items-tags endpoint", len(names))
        return jsonify({"tags": names, "source": "items-tags"})
    except Exception:
        logger.exception(
            "Items-tags endpoint failed; falling back to aggregated pagination"
        )

    try:
        fields = ["TagItems", "Tags", "InheritedTags", "Type"]
        fetch_limit = 500
        tag_counts, canonical_names, total_processed = aggregate_tags_from_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            0,
            fetch_limit,
        )
        logger.info(
            "Aggregated %d items to collect %d unique tags",
            total_processed,
            len(tag_counts),
        )
        return jsonify(
            {
                "tags": sorted_tag_names(tag_counts, canonical_names),
                "source": "aggregated",
            }
        )
    except Exception as exc:
        logger.exception("Aggregated tag fallback failed")
        return jsonify({"error": f"Failed to list tags: {exc}"}), 400
