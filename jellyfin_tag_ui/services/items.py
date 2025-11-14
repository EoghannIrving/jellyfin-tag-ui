"""Item-related domain logic helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..config import DEFAULT_SORT_BY, DEFAULT_SORT_ORDER, SORTABLE_FIELDS, SORT_ORDERS
from ..jellyfin_client import jf_get


_KNOWN_ITEM_TYPES = {
    "movie": "Movie",
    "series": "Series",
    "season": "Season",
    "episode": "Episode",
    "audio": "Audio",
    "audiobook": "AudioBook",
    "musicvideo": "MusicVideo",
    "musicalbum": "MusicAlbum",
    "musicartist": "MusicArtist",
    "playlist": "Playlist",
    "boxset": "BoxSet",
    "collectionfolder": "CollectionFolder",
    "folder": "Folder",
    "photo": "Photo",
    "photoalbum": "PhotoAlbum",
    "book": "Book",
    "video": "Video",
    "program": "Program",
    "recording": "Recording",
    "tvchannel": "TvChannel",
    "trailer": "Trailer",
}


def normalize_item_types(raw_types: Any) -> List[str]:
    if raw_types is None:
        return []

    seen: Set[str] = set()
    normalized: List[str] = []

    def _iter_candidates(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            for part in value.split(","):
                text = part.strip()
                if text:
                    yield text
            return
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for entry in value:
                yield from _iter_candidates(entry)
            return
        text = str(value or "").strip()
        if text:
            yield text

    for candidate in _iter_candidates(raw_types):
        key = candidate.casefold()
        canonical = _KNOWN_ITEM_TYPES.get(key, candidate)
        canonical_key = canonical.casefold()
        if canonical_key in seen:
            continue
        seen.add(canonical_key)
        normalized.append(canonical)

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


def item_matches_filters(
    item: Mapping[str, Any],
    include_tag_keys: Set[str],
    exclude_tag_keys: Set[str],
    title_query_lower: str,
) -> bool:
    tags = {t.casefold() for t in _tags_for_item(item)}
    if include_tag_keys and not include_tag_keys.issubset(tags):
        return False
    if exclude_tag_keys and tags.intersection(exclude_tag_keys):
        return False
    if title_query_lower:
        candidate_values: List[str] = []
        for key in ("Name", "SortName"):
            value = item.get(key)
            if value is None:
                continue
            text = str(value)
            if not text.strip():
                continue
            candidate_values.append(text)
        if not any(
            title_query_lower in candidate.casefold() for candidate in candidate_values
        ):
            return False
    return True


def serialize_item_for_response(item: Mapping[str, Any]) -> Dict[str, Any]:
    name = item.get("Name", "")
    sort_name = item.get("SortName") or name
    return {
        "Id": item.get("Id", ""),
        "Type": item.get("Type", ""),
        "Name": name,
        "SortName": sort_name,
        "Path": item.get("Path", ""),
        "Tags": _tags_for_item(item),
        "PremiereDate": item.get("PremiereDate"),
        "ProductionYear": item.get("ProductionYear"),
    }


def page_items(
    base: str,
    api_key: str,
    user_id: Optional[str],
    lib_id: str,
    include_types: Iterable[str],
    fields: Sequence[str],
    start_index: int = 0,
    limit: int = 200,
    search_term: Optional[str] = None,
    exclude_types: Optional[Sequence[str]] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
):
    normalized_types = normalize_item_types(include_types)
    params: Dict[str, Any] = {
        "ParentId": lib_id,
        "Recursive": "true",
        "Fields": ",".join(fields),
        "StartIndex": start_index,
        "Limit": limit,
    }
    if normalized_types:
        params["IncludeItemTypes"] = ",".join(normalized_types)
    if search_term is not None:
        normalized_search = str(search_term).strip()
        if normalized_search:
            params["SearchTerm"] = normalized_search
    if exclude_types:
        params["ExcludeItemTypes"] = ",".join(exclude_types)
    if sort_by is not None or sort_order is not None:
        normalized_sort_by, normalized_sort_order = normalize_sort_params(
            sort_by, sort_order
        )
        params["SortBy"] = normalized_sort_by
        params["SortOrder"] = normalized_sort_order
    endpoint = f"{base}/Users/{user_id}/Items" if user_id else f"{base}/Items"
    return jf_get(endpoint, api_key, params)


def _tags_for_item(item: Mapping[str, Any]) -> List[str]:
    from .tags import item_tags

    return item_tags(item)


__all__ = [
    "item_matches_filters",
    "normalize_item_types",
    "normalize_sort_params",
    "page_items",
    "serialize_item_for_response",
    "sort_items_for_response",
]
