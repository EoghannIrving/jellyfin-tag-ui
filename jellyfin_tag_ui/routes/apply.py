"""Blueprint for tag application operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

import requests  # type: ignore[import-untyped]

from ..jellyfin_client import format_http_error
from ..services.jellyfin import resolve_jellyfin_config, validate_base
from ..services.tags import jf_update_tags

bp = Blueprint("apply", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/apply", methods=["POST"])
def api_apply():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = validate_base(base, "/api/apply", data.get("base"))
    changes = data.get("changes") or []
    user_id = data.get("userId")
    logger.info(
        "POST /api/apply base=%s user=%s changes=%d",
        base or "",
        user_id,
        len(changes),
    )
    if error is not None:
        return error

    if not user_id:
        logger.warning("POST /api/apply missing required userId")
        return jsonify({"error": "userId is required"}), 400

    results: List[Dict[str, Any]] = []
    for change in changes:
        item_id = change.get("id")
        adds = [t for t in (change.get("add") or []) if t]
        removes = [t for t in (change.get("remove") or []) if t]
        logger.info(
            "Applying tag changes for item %s add=%s remove=%s",
            item_id,
            adds,
            removes,
        )
        result: Dict[str, Any] = {
            "id": item_id,
            "added": [],
            "removed": [],
            "errors": [],
        }
        if not item_id:
            result["errors"].append("Missing item id")
            results.append(result)
            continue
        if not (adds or removes):
            logger.debug("No tag changes provided for item %s", item_id)
            results.append(result)
            continue

        try:
            final_tags = jf_update_tags(
                base,
                api_key,
                item_id,
                adds,
                removes,
                user_id=user_id,
            )
            result["added"] = adds
            result["removed"] = removes
            result["tags"] = final_tags
        except requests.HTTPError as exc:
            logger.exception("Failed to update tags for item %s", item_id)
            result["errors"].append(format_http_error(exc))
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to update tags for item %s", item_id)
            result["errors"].append(str(exc))
        results.append(result)
    logger.info("/api/apply finished processing %d changes", len(results))
    return jsonify({"updated": results})
