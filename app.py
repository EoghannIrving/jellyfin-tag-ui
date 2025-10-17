import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import Flask, render_template, request, jsonify, send_file
from flask.typing import ResponseReturnValue
import requests  # type: ignore[import-untyped]
import csv
import io
from dotenv import load_dotenv  # type: ignore[import-not-found]

_ENV_PATH = Path(__file__).resolve().with_name(".env")
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    logging.getLogger(__name__).warning("Missing .env file at %s", _ENV_PATH)

app = Flask(__name__)

COLLECTION_ITEM_TYPES: Tuple[str, ...] = ("BoxSet", "CollectionFolder")

DEFAULT_SORT_BY = "SortName"
DEFAULT_SORT_ORDER = "Ascending"
SORTABLE_FIELDS: Tuple[str, ...] = ("SortName", "PremiereDate")
SORT_ORDERS: Tuple[str, ...] = ("Ascending", "Descending")

UPDATE_FIELDS: Tuple[str, ...] = (
    "Id",
    "Name",
    "SortName",
    "Overview",
    "Genres",
    "Tags",
    "ProviderIds",
    "CommunityRating",
    "CriticRating",
    "OfficialRating",
    "ProductionYear",
    "PremiereDate",
    "EndDate",
    "Taglines",
    "People",
    "Studios",
)


def _configure_logging() -> logging.Logger:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger(__name__)


logger = _configure_logging()


def _normalized_base(raw_base: Any) -> str:
    return str(raw_base or "").strip().rstrip("/")


def resolve_jellyfin_config(data: Mapping[str, Any]) -> Tuple[str, str]:
    """Resolve the Jellyfin base URL and API key for a request."""

    request_base = _normalized_base(data.get("base"))
    env_base = _normalized_base(os.getenv("JELLYFIN_BASE_URL"))
    base = request_base or env_base

    request_api_key = str(data.get("apiKey") or "").strip()
    env_api_key = str(os.getenv("JELLYFIN_API_KEY") or "").strip()
    api_key = request_api_key or env_api_key

    return base, api_key


def _validate_base(
    base: Optional[str], endpoint: str, raw_base: Any = None
) -> Tuple[Optional[str], Optional[ResponseReturnValue]]:
    normalized = _normalized_base(base)
    if not normalized:
        logger.warning(
            "POST %s missing Jellyfin base URL (raw=%r)",
            endpoint,
            raw_base,
        )
        return None, (jsonify({"error": "Jellyfin base URL is required"}), 400)
    return normalized, None


def jf_headers(api_key: str):
    return {"X-Emby-Token": api_key}


def jf_get(url: str, api_key: str, params=None, timeout=30):
    logger.debug("GET %s params=%s", url, params)
    r = requests.get(
        url, headers=jf_headers(api_key), params=params or {}, timeout=timeout
    )
    r.raise_for_status()
    return r.json()


def jf_post(url: str, api_key: str, params=None, json=None, timeout=30):
    logger.debug("POST %s params=%s json=%s", url, params, json)
    r = requests.post(
        url,
        headers=jf_headers(api_key),
        params=params or {},
        json=json,
        timeout=timeout,
    )
    r.raise_for_status()
    if r.text and r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return {}


def jf_put(url: str, api_key: str, params=None, json=None, timeout=30):
    logger.debug("PUT %s params=%s json=%s", url, params, json)
    r = requests.put(
        url,
        headers=jf_headers(api_key),
        params=params or {},
        json=json,
        timeout=timeout,
    )
    r.raise_for_status()
    if r.text and r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return {}


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def normalize_item_types(raw_types: Any) -> List[str]:
    if raw_types is None:
        return []

    if isinstance(raw_types, str):
        candidates: Sequence[Any] = [raw_types]
    elif isinstance(raw_types, Sequence) and not isinstance(
        raw_types, (str, bytes, bytearray)
    ):
        candidates = list(raw_types)
    else:
        candidates = [raw_types]

    normalized: List[str] = []
    for value in candidates:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return normalized


def normalize_sort_params(sort_by: Any, sort_order: Any) -> Tuple[str, str]:
    raw_sort_by = str(sort_by or "").strip()
    normalized_sort_by = (
        raw_sort_by if raw_sort_by in SORTABLE_FIELDS else DEFAULT_SORT_BY
    )

    raw_order = str(sort_order or "").strip()
    lower_order = raw_order.lower()
    if lower_order in {"descending", "desc"}:
        normalized_sort_order = "Descending"
    elif lower_order in {"ascending", "asc"}:
        normalized_sort_order = "Ascending"
    elif raw_order in SORT_ORDERS:
        normalized_sort_order = raw_order
    else:
        normalized_sort_order = DEFAULT_SORT_ORDER

    if normalized_sort_order not in SORT_ORDERS:
        normalized_sort_order = DEFAULT_SORT_ORDER

    return normalized_sort_by, normalized_sort_order


def _filtered_update_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for field in UPDATE_FIELDS:
        if field == "Tags":
            continue
        value = item.get(field)
        if field == "Id" and value:
            payload[field] = value
            continue
        if _is_empty_value(value):
            continue
        payload[field] = value
    return payload


def _is_unsupported_method_error(error: requests.HTTPError) -> bool:
    response = getattr(error, "response", None)
    if response is None:
        return False
    return getattr(response, "status_code", None) in {405, 501}


def jf_put_with_fallback(url: str, api_key: str, json=None, timeout=30):
    try:
        return jf_put(url, api_key, json=json, timeout=timeout)
    except requests.HTTPError as error:
        if _is_unsupported_method_error(error):
            status = getattr(error.response, "status_code", "unknown")
            logger.info(
                "PUT %s unsupported (status=%s); falling back to POST", url, status
            )
            return jf_post(url, api_key, json=json, timeout=timeout)
        raise


def jf_update_tags(
    base: str,
    api_key: str,
    item_id: str,
    add: Sequence[str],
    remove: Sequence[str],
    user_id: Optional[str] = None,
):
    if not item_id:
        raise ValueError("Item ID is required to update tags")

    if user_id:
        fetch_endpoint = f"{base}/Users/{user_id}/Items/{item_id}"
    else:
        fetch_endpoint = f"{base}/Items/{item_id}"
    update_endpoint = f"{base}/Items/{item_id}"
    logger.debug("Fetching item %s for tag update", fetch_endpoint)
    item = jf_get(fetch_endpoint, api_key)

    existing_tags = item_tags(item)
    logger.debug("Existing tags for %s: %s", item_id, existing_tags)

    merged: Dict[str, str] = {
        tag.lower(): tag for tag in existing_tags if isinstance(tag, str) and tag
    }

    for tag in add:
        if tag:
            merged[tag.lower()] = tag

    for tag in remove:
        if tag:
            merged.pop(tag.lower(), None)

    final_tags = sorted(merged.values(), key=str.lower)

    payload = _filtered_update_payload(item)
    payload["Id"] = payload.get("Id") or item_id
    payload["Tags"] = final_tags
    logger.debug(
        "Posting updated tags for %s to %s with payload %s",
        item_id,
        update_endpoint,
        payload,
    )

    jf_put_with_fallback(update_endpoint, api_key, json=payload)
    return final_tags


def normalize_tags(tag_string):
    if not tag_string:
        return []
    raw = [t.strip() for part in tag_string.split(",") for t in part.split(";")]
    return sorted(list({t for t in raw if t}), key=str.lower)


def item_tags(item):
    names = []
    seen = set()

    for tag in item.get("TagItems") or []:
        name = (tag or {}).get("Name")
        if name:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                names.append(name)

    for name in item.get("Tags") or []:
        if isinstance(name, str) and name:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                names.append(name)

    return names


def _serialize_item_for_response(item: Mapping[str, Any]) -> Dict[str, Any]:
    name = item.get("Name", "")
    sort_name = item.get("SortName") or name
    return {
        "Id": item.get("Id", ""),
        "Type": item.get("Type", ""),
        "Name": name,
        "SortName": sort_name,
        "Path": item.get("Path", ""),
        "Tags": item_tags(item),
        "PremiereDate": item.get("PremiereDate"),
        "ProductionYear": item.get("ProductionYear"),
    }


def _name_sort_key(item: Mapping[str, Any]) -> Tuple[str, str, str]:
    sort_name = str(item.get("SortName") or item.get("Name") or "").casefold()
    name = str(item.get("Name") or "").casefold()
    identifier = str(item.get("Id") or "")
    return sort_name, name, identifier


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidate = text
    if text.endswith("Z"):
        candidate = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _release_timestamp(item: Mapping[str, Any]) -> Optional[float]:
    premiere = _parse_iso_datetime(item.get("PremiereDate"))
    if premiere is not None:
        return premiere.timestamp()
    raw_year = item.get("ProductionYear")
    if raw_year is None:
        return None
    try:
        year = int(raw_year)
    except (TypeError, ValueError):
        return None
    try:
        anchor = datetime(year, 1, 1, tzinfo=timezone.utc)
    except ValueError:
        return None
    return anchor.timestamp()


def sort_items_for_response(
    items: Sequence[Mapping[str, Any]], sort_by: Any, sort_order: Any
) -> List[Mapping[str, Any]]:
    normalized_sort_by, normalized_sort_order = normalize_sort_params(
        sort_by, sort_order
    )
    if normalized_sort_by == "PremiereDate":
        descending = normalized_sort_order == "Descending"

        def key(item: Mapping[str, Any]) -> Tuple[float, str, str, str]:
            timestamp = _release_timestamp(item)
            if timestamp is None:
                key_timestamp = float("inf")
            elif descending:
                key_timestamp = -timestamp
            else:
                key_timestamp = timestamp
            name_key = _name_sort_key(item)
            return (key_timestamp, *name_key)

        return sorted(items, key=key)

    sorted_items = sorted(items, key=_name_sort_key)
    if normalized_sort_order == "Descending":
        sorted_items.reverse()
    return sorted_items


def page_items(
    base,
    api_key,
    user_id,
    lib_id,
    include_types,
    fields,
    start_index=0,
    limit=200,
    exclude_types: Optional[Sequence[str]] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
):
    normalized_types = normalize_item_types(include_types)
    params = {
        "ParentId": lib_id,
        "Recursive": "true",
        "Fields": ",".join(fields),
        "StartIndex": start_index,
        "Limit": limit,
    }
    if normalized_types:
        params["IncludeItemTypes"] = ",".join(normalized_types)
    if exclude_types:
        params["ExcludeItemTypes"] = ",".join(exclude_types)
    if sort_by:
        params["SortBy"] = sort_by
    if sort_order:
        params["SortOrder"] = sort_order
    endpoint = f"{base}/Users/{user_id}/Items" if user_id else f"{base}/Items"
    return jf_get(endpoint, api_key, params)


@app.route("/")
def index():
    base_url = os.getenv("JELLYFIN_BASE_URL", "")
    api_key = os.getenv("JELLYFIN_API_KEY", "")
    logger.info(
        "GET / - rendering index (base_url_configured=%s, api_key_configured=%s)",
        bool(base_url),
        bool(api_key),
    )
    return render_template("index.html", base_url=base_url, api_key=api_key)


@app.route("/api/users", methods=["POST"])
def api_users():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = _validate_base(base, "/api/users", data.get("base"))
    logger.info("POST /api/users base=%s", base or "")
    if error is not None:
        return error
    users = jf_get(f"{base}/Users", api_key)
    logger.info("/api/users fetched %d users", len(users))
    return jsonify(users)


@app.route("/api/libraries", methods=["POST"])
def api_libraries():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = _validate_base(base, "/api/libraries", data.get("base"))
    logger.info("POST /api/libraries base=%s", base or "")
    if error is not None:
        return error
    libs = jf_get(f"{base}/Library/VirtualFolders", api_key)
    logger.info("/api/libraries fetched %d libraries", len(libs))
    return jsonify(libs)


@app.route("/api/tags", methods=["POST"])
def api_tags():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = _validate_base(base, "/api/tags", data.get("base"))
    lib_id = data.get("libraryId")
    user_id = data.get("userId")
    include_types = normalize_item_types(data.get("types"))
    logger.info(
        "POST /api/tags base=%s library=%s user=%s include_types=%s",
        base or "",
        lib_id,
        user_id,
        include_types,
    )
    if error is not None:
        return error
    lib_id = data["libraryId"]

    # 1) Preferred: user-scoped tag endpoint (some Jellyfin builds require this)
    if user_id:
        try:
            params = {"ParentId": lib_id, "Recursive": "true"}
            if include_types:
                params["IncludeItemTypes"] = ",".join(include_types)
            res = jf_get(
                f"{base}/Users/{user_id}/Items/Tags",
                api_key,
                params=params,
            )
            names = sorted(
                [x.get("Name", "") for x in res.get("Items", []) if x.get("Name")],
                key=str.lower,
            )
            logger.info(
                "/api/tags returning %d tags via users-items-tags endpoint", len(names)
            )
            return jsonify({"tags": names, "source": "users-items-tags"})
        except Exception:
            logger.exception(
                "User-scoped tags endpoint failed; falling back to global endpoint",
            )

    # 2) Legacy/global endpoint (works on some servers)
    try:
        res = jf_get(
            f"{base}/Items/Tags",
            api_key,
            params={"ParentId": lib_id, "Recursive": "true"},
        )
        names = sorted(
            [x.get("Name", "") for x in res.get("Items", []) if x.get("Name")],
            key=str.lower,
        )
        logger.info("/api/tags returning %d tags via items-tags endpoint", len(names))
        return jsonify({"tags": names, "source": "items-tags"})
    except Exception:
        logger.exception(
            "Items-tags endpoint failed; falling back to aggregated pagination"
        )
        # 3) Robust fallback: aggregate by paging items and collecting TagItems
        try:
            fields = ["TagItems", "Tags", "Type"]
            start = 0
            limit = 500
            tags = set()
            total_processed = 0
            logger.info("Starting aggregated tag collection")
            while True:
                payload = page_items(
                    base, api_key, user_id, lib_id, include_types, fields, start, limit
                )
                items = payload.get("Items", [])
                if not items:
                    break
                total_processed += len(items)
                for it in items:
                    for name in item_tags(it):
                        tags.add(name)
                start += len(items)
                if start >= payload.get("TotalRecordCount", start):
                    break
            logger.info(
                "Aggregated %d items to collect %d unique tags",
                total_processed,
                len(tags),
            )
            return jsonify(
                {"tags": sorted(tags, key=str.lower), "source": "aggregated"}
            )
        except Exception as e2:
            logger.exception("Aggregated tag fallback failed")
            return jsonify({"error": f"Failed to list tags: {e2}"}), 400


@app.route("/api/items", methods=["POST"])
def api_items():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = _validate_base(base, "/api/items", data.get("base"))
    user_id = data.get("userId")
    lib_id = data.get("libraryId")
    include_types = normalize_item_types(data.get("types"))
    include_tags = normalize_tags(data.get("includeTags", ""))
    exclude_tags = normalize_tags(data.get("excludeTags", ""))
    exclude_collections = bool(data.get("excludeCollections"))
    excluded_types: Sequence[str] = COLLECTION_ITEM_TYPES if exclude_collections else ()
    start = max(0, int(data.get("startIndex", 0)))
    limit = int(data.get("limit", 100))
    if limit > 100:
        limit = 100
    if limit < 0:
        limit = 0
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
    user_id = data["userId"]
    lib_id = data["libraryId"]

    fields = [
        "TagItems",
        "Name",
        "Path",
        "ProviderIds",
        "Type",
        "Tags",
        "SortName",
        "PremiereDate",
        "ProductionYear",
    ]
    matched_items: List[Dict[str, Any]] = []
    total_record_count: Optional[int] = None
    current_start = 0
    fetch_limit = limit if limit > 0 else 100

    def _update_total(payload: Mapping[str, Any]) -> None:
        nonlocal total_record_count
        payload_total = payload.get("TotalRecordCount")
        if payload_total is not None:
            total_record_count = int(payload_total)

    def good(item):
        tags = set([t.lower() for t in item_tags(item)])
        if include_tags and not all(t.lower() in tags for t in include_tags):
            return False
        if exclude_tags and any(t.lower() in tags for t in exclude_tags):
            return False
        return True

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
            exclude_types=excluded_types,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        _update_total(payload)
        raw_items = payload.get("Items", [])
        if not raw_items:
            break

        items = raw_items
        if excluded_types:
            excluded_set = set(excluded_types)
            items = [it for it in raw_items if it.get("Type") not in excluded_set]

        for it in items:
            if good(it):
                matched_items.append(_serialize_item_for_response(it))

        current_start += len(raw_items)
        if total_record_count is not None and current_start >= int(total_record_count):
            break

    total = total_record_count if total_record_count is not None else current_start
    total_matches = len(matched_items)
    sorted_matches = sort_items_for_response(matched_items, sort_by, sort_order)
    if limit > 0:
        slice_end = start + limit
        paged_items = sorted_matches[start:slice_end]
    else:
        paged_items = []
    returned_count = len(paged_items)

    logger.info(
        "/api/items returning %d filtered items out of %d total (excluded_types=%s)",
        returned_count,
        total,
        list(excluded_types),
    )
    return jsonify(
        {
            "TotalRecordCount": total,
            "TotalMatchCount": total_matches,
            "ReturnedCount": returned_count,
            "Items": paged_items,
            "SortBy": sort_by,
            "SortOrder": sort_order,
        }
    )


@app.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = _validate_base(base, "/api/export", data.get("base"))
    user_id = data.get("userId")
    lib_id = data.get("libraryId")
    include_types = normalize_item_types(data.get("types"))
    exclude_collections = bool(data.get("excludeCollections"))
    excluded_types: Sequence[str] = COLLECTION_ITEM_TYPES if exclude_collections else ()
    sort_by, sort_order = normalize_sort_params(
        data.get("sortBy"), data.get("sortOrder")
    )
    logger.info(
        "POST /api/export base=%s library=%s user=%s include_types=%s sort_by=%s sort_order=%s",
        base or "",
        lib_id,
        user_id,
        include_types,
        sort_by,
        sort_order,
    )
    if error is not None:
        return error
    user_id = data["userId"]
    lib_id = data["libraryId"]

    fields = [
        "TagItems",
        "Name",
        "Path",
        "ProviderIds",
        "Type",
        "Tags",
        "SortName",
        "PremiereDate",
        "ProductionYear",
    ]
    start = 0
    limit = 500
    collected_items: List[Dict[str, Any]] = []
    total_processed = 0
    while True:
        payload = page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
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
            collected_items.append(_serialize_item_for_response(it))
        start += len(raw_items)
        if start >= payload.get("TotalRecordCount", start):
            break
    logger.info("/api/export processed %d items for CSV export", total_processed)

    sorted_items = sort_items_for_response(collected_items, sort_by, sort_order)
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


@app.route("/api/apply", methods=["POST"])
def api_apply():
    # JSON payload example:
    # {
    #   "base": "...",
    #   "apiKey": "...",
    #   "changes": [
    #     {"id": "ITEMID", "add": ["Tag1","Tag2"], "remove": ["Old"]},
    #     ...
    #   ]
    # }
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = _validate_base(base, "/api/apply", data.get("base"))
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

    results = []
    for ch in changes:
        iid = ch.get("id")
        adds = [t for t in (ch.get("add") or []) if t]
        rems = [t for t in (ch.get("remove") or []) if t]
        logger.info(
            "Applying tag changes for item %s add=%s remove=%s",
            iid,
            adds,
            rems,
        )
        r = {"id": iid, "added": [], "removed": [], "errors": []}
        if not iid:
            r["errors"].append("Missing item id")
            results.append(r)
            continue
        if not (adds or rems):
            logger.debug("No tag changes provided for item %s", iid)
            results.append(r)
            continue

        try:
            final_tags = jf_update_tags(
                base,
                api_key,
                iid,
                adds,
                rems,
                user_id=user_id,
            )
            r["added"] = adds
            r["removed"] = rems
            r["tags"] = final_tags
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to update tags for item %s", iid)
            r["errors"].append(str(exc))
        results.append(r)
    logger.info("/api/apply finished processing %d changes", len(results))
    return jsonify({"updated": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
