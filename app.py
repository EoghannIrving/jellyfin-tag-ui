import os
import logging
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

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


def jf_post(url: str, api_key: str, params=None, timeout=30):
    logger.debug("POST %s params=%s", url, params)
    r = requests.post(
        url, headers=jf_headers(api_key), params=params or {}, timeout=timeout
    )
    r.raise_for_status()
    if r.text and r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return {}


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
):
    params = {
        "ParentId": lib_id,
        "Recursive": "true",
        "IncludeItemTypes": ",".join(include_types),
        "Fields": ",".join(fields),
        "StartIndex": start_index,
        "Limit": limit,
    }
    if exclude_types:
        params["ExcludeItemTypes"] = ",".join(exclude_types)
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
    include_types = data.get("types") or ["Movie", "Series", "Episode"]
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
            res = jf_get(
                f"{base}/Users/{user_id}/Items/Tags",
                api_key,
                params={
                    "ParentId": lib_id,
                    "Recursive": "true",
                    "IncludeItemTypes": ",".join(include_types),
                },
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
    include_types = data.get("types") or ["Movie", "Series", "Episode"]
    include_tags = normalize_tags(data.get("includeTags", ""))
    exclude_tags = normalize_tags(data.get("excludeTags", ""))
    exclude_collections = bool(data.get("excludeCollections"))
    excluded_types: Sequence[str] = COLLECTION_ITEM_TYPES if exclude_collections else ()
    start = int(data.get("startIndex", 0))
    limit = int(data.get("limit", 200))
    logger.info(
        "POST /api/items base=%s library=%s user=%s include=%s exclude=%s start=%d limit=%d",
        base or "",
        lib_id,
        user_id,
        include_tags,
        exclude_tags,
        start,
        limit,
    )
    if error is not None:
        return error
    user_id = data["userId"]
    lib_id = data["libraryId"]

    fields = ["TagItems", "Name", "Path", "ProviderIds", "Type", "Tags"]
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
    )
    items = payload.get("Items", [])
    if excluded_types:
        excluded_set = set(excluded_types)
        items = [it for it in items if it.get("Type") not in excluded_set]
    total = payload.get("TotalRecordCount", len(items))

    def good(item):
        tags = set([t.lower() for t in item_tags(item)])
        if include_tags and not all(t.lower() in tags for t in include_tags):
            return False
        if exclude_tags and any(t.lower() in tags for t in exclude_tags):
            return False
        return True

    filtered = [
        {
            "Id": it.get("Id", ""),
            "Type": it.get("Type", ""),
            "Name": it.get("Name", ""),
            "Path": it.get("Path", ""),
            "Tags": item_tags(it),
        }
        for it in items
        if good(it)
    ]

    logger.info(
        "/api/items returning %d filtered items out of %d total (excluded_types=%s)",
        len(filtered),
        total,
        list(excluded_types),
    )
    return jsonify(
        {"TotalRecordCount": total, "ReturnedCount": len(filtered), "Items": filtered}
    )


@app.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    base, error = _validate_base(base, "/api/export", data.get("base"))
    user_id = data.get("userId")
    lib_id = data.get("libraryId")
    include_types = data.get("types") or ["Movie", "Series", "Episode"]
    exclude_collections = bool(data.get("excludeCollections"))
    excluded_types: Sequence[str] = COLLECTION_ITEM_TYPES if exclude_collections else ()
    logger.info(
        "POST /api/export base=%s library=%s user=%s include_types=%s",
        base or "",
        lib_id,
        user_id,
        include_types,
    )
    if error is not None:
        return error
    user_id = data["userId"]
    lib_id = data["libraryId"]

    fields = ["TagItems", "Name", "Path", "ProviderIds", "Type", "Tags"]
    start = 0
    limit = 500
    rows = []
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
            rows.append(
                {
                    "id": it.get("Id", ""),
                    "type": it.get("Type", ""),
                    "name": it.get("Name", ""),
                    "path": it.get("Path", ""),
                    "tags": ";".join(sorted(item_tags(it), key=str.lower)),
                }
            )
        start += len(raw_items)
        if start >= payload.get("TotalRecordCount", start):
            break
    logger.info("/api/export processed %d items for CSV export", total_processed)

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

    def _apply_tag_update(
        base_url: str,
        api_key_value: str,
        item_id: Optional[str],
        scoped_user_id: Optional[str],
        params: Mapping[str, str],
        action: str,
    ) -> Optional[Exception]:
        endpoints = []
        if scoped_user_id:
            endpoints.append(
                (
                    "user",
                    f"{base_url}/Users/{scoped_user_id}/Items/{item_id}/Tags",
                )
            )
        endpoints.append(("global", f"{base_url}/Items/{item_id}/Tags"))
        last_error: Optional[Exception] = None
        for scope, url in endpoints:
            scope_label = "user-scoped" if scope == "user" else "global"
            try:
                jf_post(url, api_key_value, params=params)
                if scope == "global" and scoped_user_id and last_error is not None:
                    logger.info(
                        "%s for item %s succeeded via global endpoint after user-scoped failure",
                        action,
                        item_id,
                    )
                else:
                    logger.debug(
                        "%s for item %s succeeded via %s endpoint",
                        action,
                        item_id,
                        scope_label,
                    )
                return None
            except (
                Exception
            ) as exc:  # pragma: no cover - exercised in tests via fallbacks
                last_error = exc
                if scope == "user":
                    logger.exception(
                        "User-scoped %s request failed for item %s; attempting global endpoint",
                        action,
                        item_id,
                    )
                else:
                    logger.exception(
                        "Global %s request failed for item %s",
                        action,
                        item_id,
                    )
        return last_error

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
        if adds:
            params = {"AddTags": ",".join(adds)}
            error = _apply_tag_update(base, api_key, iid, user_id, params, "AddTags")
            if error is None:
                r["added"] = adds
            else:
                r["errors"].append(f"AddTags: {error}")
        if rems:
            params = {"RemoveTags": ",".join(rems)}
            error = _apply_tag_update(base, api_key, iid, user_id, params, "RemoveTags")
            if error is None:
                r["removed"] = rems
            else:
                r["errors"].append(f"RemoveTags: {error}")
        results.append(r)
    logger.info("/api/apply finished processing %d changes", len(results))
    return jsonify({"updated": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
