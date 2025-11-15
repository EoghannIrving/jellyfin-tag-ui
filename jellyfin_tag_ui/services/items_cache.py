"""Cache helpers for item queries in `/api/items`. """

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List, Mapping, Tuple, Any

from ..config import (
    ITEM_PREFETCH_CACHE_LIMIT,
    ITEM_PREFETCH_CACHE_MAX_ENTRIES,
    ITEM_PREFETCH_CACHE_TTL,
    ITEM_QUERY_CACHE_MAX_ENTRIES,
    ITEM_QUERY_CACHE_TTL,
)


@dataclass(frozen=True)
class ItemQueryCacheKey:
    base: str
    user_id: str
    library_id: str
    include_types: Tuple[str, ...]
    include_tag_keys: Tuple[str, ...]
    exclude_tag_keys: Tuple[str, ...]
    excluded_types: Tuple[str, ...]
    title_query: str
    sort_by: str
    sort_order: str
    tag_cache_version: float
    start_index: int
    limit: int


@dataclass
class ItemQueryCacheEntry:
    response: Mapping[str, Any]
    stored_at: float = field(default_factory=time.time)


_CACHE_LOCK = threading.RLock()
_ITEM_QUERY_CACHE: "OrderedDict[ItemQueryCacheKey, ItemQueryCacheEntry]" = OrderedDict()


@dataclass(frozen=True)
class ItemPrefetchCacheKey:
    base: str
    user_id: str
    library_id: str
    include_types: Tuple[str, ...]
    include_tag_keys: Tuple[str, ...]
    exclude_tag_keys: Tuple[str, ...]
    excluded_types: Tuple[str, ...]
    title_query: str
    sort_by: str
    sort_order: str
    tag_cache_version: float


@dataclass
class ItemPrefetchCacheEntry:
    matches: List[Mapping[str, Any]]
    total_matches: int
    complete: bool
    truncated: bool
    stored_at: float = field(default_factory=time.time)


_ITEM_PREFETCH_CACHE: "OrderedDict[ItemPrefetchCacheKey, ItemPrefetchCacheEntry]" = (
    OrderedDict()
)


def _prefetch_evict_if_needed() -> None:
    while len(_ITEM_PREFETCH_CACHE) > ITEM_PREFETCH_CACHE_MAX_ENTRIES:
        _ITEM_PREFETCH_CACHE.popitem(last=False)


def _prefetch_is_expired(entry: ItemPrefetchCacheEntry) -> bool:
    return (time.time() - entry.stored_at) >= ITEM_PREFETCH_CACHE_TTL


def _evict_if_needed() -> None:
    while len(_ITEM_QUERY_CACHE) > ITEM_QUERY_CACHE_MAX_ENTRIES:
        _ITEM_QUERY_CACHE.popitem(last=False)


def _is_expired(entry: ItemQueryCacheEntry) -> bool:
    return (time.time() - entry.stored_at) >= ITEM_QUERY_CACHE_TTL


def get_cached_response(key: ItemQueryCacheKey) -> Mapping[str, Any] | None:
    with _CACHE_LOCK:
        entry = _ITEM_QUERY_CACHE.get(key)
        if not entry:
            return None
        if _is_expired(entry):
            _ITEM_QUERY_CACHE.pop(key, None)
            return None
        # move to most-recent position so eviction favors older entries
        _ITEM_QUERY_CACHE.move_to_end(key)
        return entry.response


def set_cached_response(key: ItemQueryCacheKey, response: Mapping[str, Any]) -> None:
    with _CACHE_LOCK:
        _ITEM_QUERY_CACHE[key] = ItemQueryCacheEntry(
            response=response, stored_at=time.time()
        )
        _ITEM_QUERY_CACHE.move_to_end(key)
        _evict_if_needed()


def get_prefetch_cache_entry(
    key: ItemPrefetchCacheKey,
) -> ItemPrefetchCacheEntry | None:
    with _CACHE_LOCK:
        entry = _ITEM_PREFETCH_CACHE.get(key)
        if not entry:
            return None
        if _prefetch_is_expired(entry):
            _ITEM_PREFETCH_CACHE.pop(key, None)
            return None
        _ITEM_PREFETCH_CACHE.move_to_end(key)
        return entry


def set_prefetch_cache_entry(
    key: ItemPrefetchCacheKey,
    matches: List[Mapping[str, Any]],
    total_matches: int,
    complete: bool,
) -> None:
    trimmed = matches[:ITEM_PREFETCH_CACHE_LIMIT]
    truncated = len(trimmed) < total_matches
    entry = ItemPrefetchCacheEntry(
        matches=trimmed,
        total_matches=total_matches,
        complete=complete,
        truncated=truncated,
        stored_at=time.time(),
    )
    with _CACHE_LOCK:
        _ITEM_PREFETCH_CACHE[key] = entry
        _ITEM_PREFETCH_CACHE.move_to_end(key)
        _prefetch_evict_if_needed()
