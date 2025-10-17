import os
from flask import Flask, render_template, request, jsonify, send_file
import requests  # type: ignore[import-untyped]
import csv
import io
from dotenv import load_dotenv  # type: ignore[import-not-found]

load_dotenv()

app = Flask(__name__)


def jf_headers(api_key: str):
    return {"X-Emby-Token": api_key}


def jf_get(url: str, api_key: str, params=None, timeout=30):
    r = requests.get(
        url, headers=jf_headers(api_key), params=params or {}, timeout=timeout
    )
    r.raise_for_status()
    return r.json()


def jf_post(url: str, api_key: str, params=None, timeout=30):
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
    return [t.get("Name", "") for t in (item.get("TagItems") or []) if t.get("Name")]


def page_items(
    base, api_key, user_id, lib_id, include_types, fields, start_index=0, limit=200
):
    params = {
        "ParentId": lib_id,
        "Recursive": "true",
        "IncludeItemTypes": ",".join(include_types),
        "Fields": ",".join(fields),
        "StartIndex": start_index,
        "Limit": limit,
    }
    return jf_get(f"{base}/Users/{user_id}/Items", api_key, params)


@app.route("/")
def index():
    base_url = os.getenv("JELLYFIN_BASE_URL", "")
    api_key = os.getenv("JELLYFIN_API_KEY", "")
    return render_template("index.html", base_url=base_url, api_key=api_key)


@app.route("/api/users", methods=["POST"])
def api_users():
    data = request.get_json(force=True)
    base = data["base"].rstrip("/")
    api_key = data["apiKey"]
    users = jf_get(f"{base}/Users", api_key)
    return jsonify(users)


@app.route("/api/libraries", methods=["POST"])
def api_libraries():
    data = request.get_json(force=True)
    base = data["base"].rstrip("/")
    api_key = data["apiKey"]
    libs = jf_get(f"{base}/Library/VirtualFolders", api_key)
    return jsonify(libs)


@app.route("/api/tags", methods=["POST"])
def api_tags():
    data = request.get_json(force=True)
    base = data["base"].rstrip("/")
    api_key = data["apiKey"]
    lib_id = data["libraryId"]
    user_id = data.get("userId")
    include_types = data.get("types") or ["Movie", "Series", "Episode"]

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
            return jsonify({"tags": names, "source": "users-items-tags"})
        except Exception:
            # fall through to aggregation
            pass

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
        return jsonify({"tags": names, "source": "items-tags"})
    except Exception:
        # 3) Robust fallback: aggregate by paging items and collecting TagItems
        try:
            fields = ["TagItems", "Type"]
            start = 0
            limit = 500
            tags = set()
            while True:
                payload = page_items(
                    base, api_key, user_id, lib_id, include_types, fields, start, limit
                )
                items = payload.get("Items", [])
                if not items:
                    break
                for it in items:
                    for t in it.get("TagItems") or []:
                        n = t.get("Name")
                        if n:
                            tags.add(n)
                start += len(items)
                if start >= payload.get("TotalRecordCount", start):
                    break
            return jsonify(
                {"tags": sorted(tags, key=str.lower), "source": "aggregated"}
            )
        except Exception as e2:
            return jsonify({"error": f"Failed to list tags: {e2}"}), 400


@app.route("/api/items", methods=["POST"])
def api_items():
    data = request.get_json(force=True)
    base = data["base"].rstrip("/")
    api_key = data["apiKey"]
    user_id = data["userId"]
    lib_id = data["libraryId"]
    include_types = data.get("types") or ["Movie", "Series", "Episode"]
    include_tags = normalize_tags(data.get("includeTags", ""))
    exclude_tags = normalize_tags(data.get("excludeTags", ""))
    start = int(data.get("startIndex", 0))
    limit = int(data.get("limit", 200))

    fields = ["TagItems", "Name", "Path", "ProviderIds", "Type"]
    payload = page_items(
        base, api_key, user_id, lib_id, include_types, fields, start, limit
    )
    items = payload.get("Items", [])
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

    return jsonify(
        {"TotalRecordCount": total, "ReturnedCount": len(filtered), "Items": filtered}
    )


@app.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json(force=True)
    base = data["base"].rstrip("/")
    api_key = data["apiKey"]
    user_id = data["userId"]
    lib_id = data["libraryId"]
    include_types = data.get("types") or ["Movie", "Series", "Episode"]

    fields = ["TagItems", "Name", "Path", "ProviderIds", "Type"]
    start = 0
    limit = 500
    rows = []
    while True:
        payload = page_items(
            base, api_key, user_id, lib_id, include_types, fields, start, limit
        )
        items = payload.get("Items", [])
        if not items:
            break
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
        start += len(items)
        if start >= payload.get("TotalRecordCount", start):
            break

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
    base = data["base"].rstrip("/")
    api_key = data["apiKey"]
    changes = data.get("changes") or []
    results = []
    for ch in changes:
        iid = ch.get("id")
        adds = [t for t in (ch.get("add") or []) if t]
        rems = [t for t in (ch.get("remove") or []) if t]
        r = {"id": iid, "added": [], "removed": [], "errors": []}
        if adds:
            try:
                jf_post(
                    f"{base}/Items/{iid}/Tags",
                    api_key,
                    params={"AddTags": ",".join(adds)},
                )
                r["added"] = adds
            except Exception as e:
                r["errors"].append(f"AddTags: {e}")
        if rems:
            try:
                jf_post(
                    f"{base}/Items/{iid}/Tags",
                    api_key,
                    params={"RemoveTags": ",".join(rems)},
                )
                r["removed"] = rems
            except Exception as e:
                r["errors"].append(f"RemoveTags: {e}")
        results.append(r)
    return jsonify({"updated": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
