"""Blueprints for item search and export endpoints."""

from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List, Sequence, Set

from flask import Blueprint, jsonify, request, send_file

from ..config import COLLECTION_ITEM_TYPES
from ..services.jellyfin import resolve_jellyfin_config, validate_base
from ..services.items import (
    item_matches_filters,
    normalize_item_types,
    normalize_sort_params,
    page_items,
    serialize_item_for_response,
    sort_items_for_response,
)
from ..services.tags import normalize_tags

bp = Blueprint("items", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


def _sanitize_start_index(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _sanitize_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 100
    if parsed > 100:
        return 100
    if parsed < 0:
        return 0
    return parsed


def _prepare_fields() -> List[str]:
    return [
        "TagItems",
        "InheritedTags",
        "Name",
        "Path",
        "ProviderIds",
        "Type",
        "Tags",
        "SortName",
        "PremiereDate",
        "ProductionYear",
    ]


def _filter_and_collect_items(
    base: str,
    api_key: str,
    user_id: str,
    lib_id: str,
    include_types: Sequence[str],
    include_tag_keys: Set[str],
    exclude_tag_keys: Set[str],
    excluded_types: Sequence[str],
    title_query: str,
    sort_by: str,
    sort_order: str,
    limit: int,
) -> List[Dict[str, Any]]:
    fields = _prepare_fields()
    matched_items: List[Dict[str, Any]] = []
    current_start = 0
    fetch_limit = limit if limit > 0 else 100
    title_query_lower = title_query.casefold() if title_query else ""

    while True:
        payload = page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            current_start,
            fetch_limit,
            search_term=title_query if title_query else None,
            exclude_types=excluded_types,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        raw_items = payload.get("Items", [])
        if not raw_items:
            break

        items = raw_items
        if excluded_types:
            excluded_set = set(excluded_types)
            items = [it for it in raw_items if it.get("Type") not in excluded_set]

        for it in items:
            if item_matches_filters(
                it, include_tag_keys, exclude_tag_keys, title_query_lower
            ):
                matched_items.append(serialize_item_for_response(it))

        page_size = len(raw_items)
        current_start += page_size
        total_count = payload.get("TotalRecordCount")
        if (
            total_count is not None
            and isinstance(total_count, int)
            and current_start < total_count
        ):
            if 0 < page_size < fetch_limit:
                fetch_limit = page_size
            continue
        if page_size < fetch_limit:
            break

    return matched_items


@bp.route("/items", methods=["POST"])
def api_items():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = validate_base(base, "/api/items", data.get("base"))
    raw_user_id = data.get("userId")
    raw_lib_id = data.get("libraryId")
    user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
    lib_id = str(raw_lib_id).strip() if raw_lib_id is not None else ""
    include_types = normalize_item_types(data.get("types"))
    include_tags = normalize_tags(data.get("includeTags", ""))
    exclude_tags = normalize_tags(data.get("excludeTags", ""))
    exclude_collections = bool(data.get("excludeCollections"))
    excluded_types: Sequence[str] = COLLECTION_ITEM_TYPES if exclude_collections else ()
    title_query_raw = data.get("titleQuery")
    title_query = str(title_query_raw or "").strip()
    include_tag_keys: Set[str] = {tag.casefold() for tag in include_tags}
    exclude_tag_keys: Set[str] = {tag.casefold() for tag in exclude_tags}
    start = _sanitize_start_index(data.get("startIndex", 0))
    limit = _sanitize_limit(data.get("limit", 100))
    sort_by, sort_order = normalize_sort_params(
        data.get("sortBy"), data.get("sortOrder")
    )
    logger.info(
        "POST /api/items base=%s library=%s user=%s include=%s exclude=%s start=%d limit=%d sort_by=%s sort_order=%s",
        base or "",
        lib_id,
        user_id,
        include_tags,
        exclude_tags,
        start,
        limit,
        sort_by,
        sort_order,
    )
    if error is not None:
        return error

    if not user_id:
        logger.warning("POST /api/items missing required userId (raw=%r)", raw_user_id)
        return jsonify({"error": "userId is required"}), 400
    if not lib_id:
        logger.warning(
            "POST /api/items missing required libraryId (raw=%r)", raw_lib_id
        )
        return jsonify({"error": "libraryId is required"}), 400

    matched_items = _filter_and_collect_items(
        base,
        api_key,
        user_id,
        lib_id,
        include_types,
        include_tag_keys,
        exclude_tag_keys,
        excluded_types,
        title_query,
        sort_by,
        sort_order,
        limit,
    )

    total_matches = len(matched_items)
    filtered_total = total_matches
    sorted_matches = sort_items_for_response(matched_items, sort_by, sort_order)
    if limit > 0:
        slice_end = start + limit
        paged_items = sorted_matches[start:slice_end]
    else:
        paged_items = []
    returned_count = len(paged_items)

    logger.info(
        "/api/items returning %d filtered items out of %d filtered total (excluded_types=%s)",
        returned_count,
        filtered_total,
        list(excluded_types),
    )
    return jsonify(
        {
            "TotalRecordCount": filtered_total,
            "TotalMatchCount": total_matches,
            "ReturnedCount": returned_count,
            "Items": paged_items,
            "SortBy": sort_by,
            "SortOrder": sort_order,
        }
    )


@bp.route("/export", methods=["POST"])
def api_export():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = validate_base(base, "/api/export", data.get("base"))
    raw_user_id = data.get("userId")
    raw_lib_id = data.get("libraryId")
    user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
    lib_id = str(raw_lib_id).strip() if raw_lib_id is not None else ""
    include_types = normalize_item_types(data.get("types"))
    include_tags = normalize_tags(data.get("includeTags", ""))
    exclude_tags = normalize_tags(data.get("excludeTags", ""))
    exclude_collections = bool(data.get("excludeCollections"))
    excluded_types: Sequence[str] = COLLECTION_ITEM_TYPES if exclude_collections else ()
    title_query_raw = data.get("titleQuery")
    title_query = str(title_query_raw or "").strip()
    include_tag_keys: Set[str] = {tag.casefold() for tag in include_tags}
    exclude_tag_keys: Set[str] = {tag.casefold() for tag in exclude_tags}
    title_query_lower = title_query.casefold() if title_query else ""
    sort_by, sort_order = normalize_sort_params(
        data.get("sortBy"), data.get("sortOrder")
    )
    logger.info(
        "POST /api/export base=%s library=%s user=%s include_types=%s include=%s exclude=%s title_query=%s exclude_collections=%s sort_by=%s sort_order=%s",
        base or "",
        lib_id,
        user_id,
        include_types,
        include_tags,
        exclude_tags,
        title_query,
        exclude_collections,
        sort_by,
        sort_order,
    )
    if error is not None:
        return error
    if not user_id:
        logger.warning("POST /api/export missing required userId (raw=%r)", raw_user_id)
        return jsonify({"error": "userId is required"}), 400
    if not lib_id:
        logger.warning(
            "POST /api/export missing required libraryId (raw=%r)", raw_lib_id
        )
        return jsonify({"error": "libraryId is required"}), 400

    fields = _prepare_fields()
    start_index = 0
    fetch_limit = 500
    matched_items: List[Dict[str, Any]] = []
    total_processed = 0

    while True:
        payload = page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start_index,
            fetch_limit,
            search_term=title_query if title_query else None,
            exclude_types=excluded_types,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        raw_items = payload.get("Items", [])
        if not raw_items:
            break
        items = raw_items
        if excluded_types:
            excluded_set = set(excluded_types)
            items = [it for it in raw_items if it.get("Type") not in excluded_set]
        total_processed += len(items)
        for it in items:
            if item_matches_filters(
                it, include_tag_keys, exclude_tag_keys, title_query_lower
            ):
                matched_items.append(serialize_item_for_response(it))
        page_size = len(raw_items)
        start_index += page_size
        total_count = payload.get("TotalRecordCount")
        if (
            total_count is not None
            and isinstance(total_count, int)
            and start_index < total_count
        ):
            if 0 < page_size < fetch_limit:
                fetch_limit = page_size
            continue
        if page_size < fetch_limit:
            break
    filtered_count = len(matched_items)
    logger.info(
        "/api/export processed %d items and retained %d after filtering (excluded_types=%s)",
        total_processed,
        filtered_count,
        list(excluded_types),
    )

    sorted_items = sort_items_for_response(matched_items, sort_by, sort_order)
    rows = [
        {
            "id": item.get("Id", ""),
            "type": item.get("Type", ""),
            "name": item.get("Name", ""),
            "path": item.get("Path", ""),
            "tags": ";".join(sorted(item.get("Tags", []), key=str.lower)),
        }
        for item in sorted_items
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "type", "name", "path", "tags"])
    writer.writeheader()
    writer.writerows(rows)
    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(
        mem, mimetype="text/csv", as_attachment=True, download_name="tags_export.csv"
    )
