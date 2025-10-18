"""Tag-oriented domain logic and helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from xml.etree import ElementTree as ET

from ..config import MAX_TAG_PAGES, TAG_PAGE_LIMIT, UPDATE_FIELDS
from ..jellyfin_client import jf_get, jf_put_with_fallback


class TagPaginationError(RuntimeError):
    """Raised when tag pagination cannot complete."""


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


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


def normalize_tags(tag_string: Any) -> List[str]:
    if not tag_string:
        return []
    raw = [t.strip() for part in str(tag_string).split(",") for t in part.split(";")]
    return sorted(list({t for t in raw if t}), key=str.lower)


def item_tags(item: Mapping[str, Any]) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()

    def _add(name: Optional[str]) -> None:
        if not isinstance(name, str):
            return
        trimmed = name.strip()
        if not trimmed:
            return
        key = trimmed.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(trimmed)

    for tag in item.get("TagItems") or []:
        _add((tag or {}).get("Name"))

    for name in item.get("Tags") or []:
        _add(name)

    for name in item.get("InheritedTags") or []:
        _add(name)

    return names


def _normalized_count(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return max(count, 0)


def _sorted_tag_names(
    tag_counts: Mapping[str, int], canonical_names: Optional[Mapping[str, str]] = None
) -> List[str]:
    sortable: List[Tuple[str, int]] = []
    for key, count in tag_counts.items():
        name = canonical_names.get(key, key) if canonical_names else key
        sortable.append((name, count))
    sortable.sort(key=lambda item: (-item[1], item[0].casefold(), item[0]))
    return [name for name, _ in sortable]


def sorted_tag_names(
    tag_counts: Mapping[str, int], canonical_names: Optional[Mapping[str, str]] = None
) -> List[str]:
    return _sorted_tag_names(tag_counts, canonical_names)


def _merge_tag_counts(
    aggregate_counts: Counter[str],
    aggregate_canonical: Dict[str, str],
    new_counts: Mapping[str, int],
    new_canonical: Mapping[str, str],
) -> None:
    for key, count in new_counts.items():
        if count <= 0:
            continue
        aggregate_counts[key] += count
    for key, value in new_canonical.items():
        aggregate_canonical.setdefault(key, value)


def _add_tag_count(
    counts: Counter[str], canonical_names: Dict[str, str], name: str, count: int
) -> None:
    if count <= 0:
        return
    trimmed = name.strip()
    if not trimmed:
        return
    key = trimmed.casefold()
    canonical_names.setdefault(key, trimmed)
    counts[key] += count


def _tag_counts_from_endpoint_items(
    items: Sequence[Mapping[str, Any]],
) -> Tuple[Counter[str], Dict[str, str]]:
    counts: Counter[str] = Counter()
    canonical: Dict[str, str] = {}
    for entry in items:
        name = entry.get("Name")
        if not isinstance(name, str) or not name:
            continue
        count: Optional[int] = None
        for key in ("ItemCount", "Count"):
            if key in entry:
                count = _normalized_count(entry.get(key))
                if count is not None:
                    break
        _add_tag_count(
            counts,
            canonical,
            name,
            (count if count is not None else 1),
        )
    return counts, canonical


def collect_paginated_tags(
    url: str,
    api_key: str,
    base_params: Mapping[str, Any],
) -> Tuple[Counter[str], Dict[str, str]]:
    start_index = 0
    aggregate_counts: Counter[str] = Counter()
    canonical_names: Dict[str, str] = {}
    previous_signature: Optional[Tuple[Tuple[Any, ...], ...]] = None
    page_number = 0

    while True:
        params = dict(base_params)
        params["Limit"] = TAG_PAGE_LIMIT
        params["StartIndex"] = start_index
        response = jf_get(url, api_key, params=params)
        items = response.get("Items", [])
        if not isinstance(items, Sequence):
            raise TagPaginationError("Tag endpoint returned unexpected payload")

        signature: Tuple[Tuple[Any, ...], ...] = tuple(
            (
                entry.get("Name"),
                _normalized_count(entry.get("ItemCount")),
                _normalized_count(entry.get("Count")),
            )
            for entry in items
        )
        if previous_signature is not None and signature == previous_signature:
            raise TagPaginationError("Tag pagination appears capped by server limit")
        previous_signature = signature

        if not items:
            break

        page_counts, page_canonical = _tag_counts_from_endpoint_items(items)
        _merge_tag_counts(
            aggregate_counts, canonical_names, page_counts, page_canonical
        )

        page_size = len(items)
        start_index += page_size
        page_number += 1

        if page_number >= MAX_TAG_PAGES:
            raise TagPaginationError("Exceeded maximum tag pagination requests")

        total_count = _normalized_count(
            response.get("TotalRecordCount") or response.get("TotalCount")
        )
        if page_size < TAG_PAGE_LIMIT:
            break
        if total_count is not None and start_index >= total_count:
            break

    return aggregate_counts, canonical_names


def aggregate_tags_from_items(
    base: str,
    api_key: str,
    user_id: Optional[str],
    lib_id: str,
    include_types: Sequence[str],
    fields: Sequence[str],
    start: int,
    fetch_limit: int,
) -> Tuple[Counter[str], Dict[str, str], int]:
    from .items import page_items

    tag_counts: Counter[str] = Counter()
    canonical_names: Dict[str, str] = {}
    total_processed = 0
    current_start = start
    current_limit = fetch_limit

    while True:
        payload = page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            current_start,
            current_limit,
        )
        items = payload.get("Items", [])
        if not items:
            break
        batch_size = len(items)
        total_processed += batch_size
        for it in items:
            for name in item_tags(it):
                _add_tag_count(tag_counts, canonical_names, name, 1)
        current_start += batch_size
        total_count = payload.get("TotalRecordCount")
        if (
            total_count is not None
            and isinstance(total_count, int)
            and current_start < total_count
        ):
            if 0 < batch_size < current_limit:
                current_limit = batch_size
            continue
        if batch_size < current_limit:
            break

    return tag_counts, canonical_names, total_processed


def render_nfo(metadata: Mapping[str, Any]) -> str:
    root = ET.Element("item")

    def _set_text(tag: str, value: Optional[Any]) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        ET.SubElement(root, tag).text = text

    _set_text("title", metadata.get("Name"))
    _set_text("sorttitle", metadata.get("SortName"))
    _set_text("plot", metadata.get("Overview"))
    taglines = metadata.get("Taglines") or []
    if taglines:
        _set_text("tagline", taglines[0])
    _set_text("communityrating", metadata.get("CommunityRating"))
    _set_text("criticrating", metadata.get("CriticRating"))
    _set_text("mpaa", metadata.get("OfficialRating"))
    _set_text("year", metadata.get("ProductionYear"))
    _set_text("premiered", metadata.get("PremiereDate"))
    _set_text("ended", metadata.get("EndDate"))

    for genre in metadata.get("Genres") or []:
        _set_text("genre", genre)

    for tag in metadata.get("Tags") or []:
        _set_text("tag", tag)

    for tagline in taglines[1:]:
        _set_text("tagline", tagline)

    people = metadata.get("People") or []
    if people:
        people_el = ET.SubElement(root, "people")
        for person in people:
            if not isinstance(person, Mapping):
                continue
            entry = ET.SubElement(people_el, "person")
            person_name = person.get("Name")
            if person_name:
                ET.SubElement(entry, "name").text = str(person_name)
            if person.get("Type"):
                ET.SubElement(entry, "type").text = str(person.get("Type"))
            if person.get("Role"):
                ET.SubElement(entry, "role").text = str(person.get("Role"))

    studios = metadata.get("Studios") or []
    for studio in studios:
        if isinstance(studio, Mapping):
            name = studio.get("Name")
        else:
            name = studio
        _set_text("studio", name)

    provider_ids = metadata.get("ProviderIds") or {}
    if isinstance(provider_ids, Mapping):
        for key, value in provider_ids.items():
            if value:
                unique = ET.SubElement(root, "uniqueid")
                unique.text = str(value)
                unique.set("type", str(key))

    return ET.tostring(root, encoding="unicode")


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
    item = jf_get(fetch_endpoint, api_key)

    existing_tags = item_tags(item)
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

    jf_put_with_fallback(update_endpoint, api_key, json=payload)

    item_path = item.get("Path")
    if not item_path:
        return final_tags

    try:
        nfo_path = Path(item_path).with_suffix(".nfo")
    except TypeError:
        return final_tags

    metadata: Dict[str, Any] = {
        "Name": payload.get("Name") or item.get("Name"),
        "SortName": payload.get("SortName") or item.get("SortName"),
        "Overview": payload.get("Overview") or item.get("Overview"),
        "Genres": payload.get("Genres") or item.get("Genres") or [],
        "Tags": final_tags,
        "Taglines": payload.get("Taglines") or item.get("Taglines") or [],
        "People": payload.get("People") or item.get("People") or [],
        "Studios": payload.get("Studios") or item.get("Studios") or [],
        "ProviderIds": payload.get("ProviderIds") or item.get("ProviderIds") or {},
        "CommunityRating": payload.get("CommunityRating")
        or item.get("CommunityRating"),
        "CriticRating": payload.get("CriticRating") or item.get("CriticRating"),
        "OfficialRating": payload.get("OfficialRating") or item.get("OfficialRating"),
        "ProductionYear": payload.get("ProductionYear") or item.get("ProductionYear"),
        "PremiereDate": payload.get("PremiereDate") or item.get("PremiereDate"),
        "EndDate": payload.get("EndDate") or item.get("EndDate"),
    }

    xml_content = render_nfo(metadata)

    nfo_parent = nfo_path.parent
    nfo_parent.mkdir(parents=True, exist_ok=True)
    nfo_path.write_text(xml_content, encoding="utf-8")

    return final_tags


__all__ = [
    "TagPaginationError",
    "aggregate_tags_from_items",
    "collect_paginated_tags",
    "item_tags",
    "jf_update_tags",
    "normalize_tags",
    "render_nfo",
    "sorted_tag_names",
]
