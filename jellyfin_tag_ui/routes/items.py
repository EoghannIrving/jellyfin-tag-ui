"""Blueprints for item search and export endpoints."""

from __future__ import annotations

import csv
import io
import logging
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from flask import Blueprint, jsonify, request, send_file

from ..config import (
    AGGREGATE_FETCH_LIMIT,
    COLLECTION_ITEM_TYPES,
    ITEM_PAGE_FETCH_LIMIT,
    ITEM_PREFETCH_JOB_TTL,
    ITEM_PREFETCH_TRIGGER_START_INDEX,
)
from ..services.jellyfin import resolve_jellyfin_config, validate_base
from ..services.items import (
    item_matches_filters,
    normalize_item_types,
    normalize_sort_params,
    page_items,
    serialize_item_for_response,
    sort_items_for_response,
)
from ..services.items_cache import (
    ItemPrefetchCacheEntry,
    ItemPrefetchCacheKey,
    ItemQueryCacheKey,
    get_cached_response,
    get_prefetch_cache_entry,
    set_cached_response,
    set_prefetch_cache_entry,
)
from ..services.tags import (
    TagCacheEntry,
    get_tag_cache_snapshot,
    is_tag_cache_stale,
    normalize_tags,
)

bp = Blueprint("items", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@dataclass
class ItemsRequestState:
    base: str
    api_key: str
    user_id: str
    library_id: str
    include_types: Sequence[str]
    include_tags: Sequence[str]
    include_tag_keys: Set[str]
    exclude_tags: Sequence[str]
    exclude_tag_keys: Set[str]
    excluded_types: Sequence[str]
    title_query: str
    sort_by: str
    sort_order: str
    start_index: int
    limit: int
    tag_cache_snapshot: Optional[TagCacheEntry] = None
    tag_cache_version: float = 0.0


@dataclass
class ItemPrefetchJob:
    job_id: str
    key: ItemPrefetchCacheKey
    state: ItemsRequestState
    status: str = "pending"
    total_matches: int = 0
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


_PREFETCH_JOB_LOCK = threading.RLock()
_ITEM_PREFETCH_JOBS: Dict[str, ItemPrefetchJob] = {}
_ITEM_PREFETCH_JOBS_BY_KEY: Dict[ItemPrefetchCacheKey, ItemPrefetchJob] = {}


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
        parsed = 50
    if parsed > ITEM_PAGE_FETCH_LIMIT:
        return ITEM_PAGE_FETCH_LIMIT
    if parsed < 0:
        return 0
    return parsed


def _prepare_fields() -> List[str]:
    return [
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


def _build_items_cache_key(
    base: str,
    user_id: str,
    lib_id: str,
    include_types: Sequence[str],
    include_tag_keys: Set[str],
    exclude_tag_keys: Set[str],
    excluded_types: Sequence[str],
    title_query: str,
    sort_by: str,
    sort_order: str,
    tag_cache_version: float,
    start_index: int,
    limit: int,
) -> ItemQueryCacheKey:
    normalized_include_types = tuple(sorted(include_types))
    normalized_excluded_types = tuple(sorted(excluded_types))
    normalized_include_tag_keys = tuple(sorted(include_tag_keys))
    normalized_exclude_tag_keys = tuple(sorted(exclude_tag_keys))
    return ItemQueryCacheKey(
        base=base,
        user_id=user_id,
        library_id=lib_id,
        include_types=normalized_include_types,
        include_tag_keys=normalized_include_tag_keys,
        exclude_tag_keys=normalized_exclude_tag_keys,
        excluded_types=normalized_excluded_types,
        title_query=title_query,
        sort_by=sort_by,
        sort_order=sort_order,
        tag_cache_version=tag_cache_version,
        start_index=start_index,
        limit=limit,
    )


def _build_prefetch_cache_key(state: ItemsRequestState) -> ItemPrefetchCacheKey:
    normalized_include_types = tuple(sorted(state.include_types))
    normalized_excluded_types = tuple(sorted(state.excluded_types))
    normalized_include_tag_keys = tuple(sorted(state.include_tag_keys))
    normalized_exclude_tag_keys = tuple(sorted(state.exclude_tag_keys))
    return ItemPrefetchCacheKey(
        base=state.base,
        user_id=state.user_id,
        library_id=state.library_id,
        include_types=normalized_include_types,
        include_tag_keys=normalized_include_tag_keys,
        exclude_tag_keys=normalized_exclude_tag_keys,
        excluded_types=normalized_excluded_types,
        title_query=state.title_query,
        sort_by=state.sort_by,
        sort_order=state.sort_order,
        tag_cache_version=state.tag_cache_version,
    )


def _parse_items_request(
    data: Dict[str, Any], endpoint: str
) -> Tuple[Optional[ItemsRequestState], Optional[Any]]:
    base, api_key = resolve_jellyfin_config(data)
    validated_base, error = validate_base(base, endpoint, data.get("base"))
    if error is not None:
        return None, error
    assert validated_base is not None
    raw_user_id = data.get("userId")
    raw_lib_id = data.get("libraryId")
    user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
    lib_id = str(raw_lib_id).strip() if raw_lib_id is not None else ""
    include_types = normalize_item_types(data.get("types"))
    include_tags = normalize_tags(data.get("includeTags", ""))
    exclude_tags = normalize_tags(data.get("excludeTags", ""))
    exclude_collections = bool(data.get("excludeCollections"))
    excluded_types: Sequence[str] = COLLECTION_ITEM_TYPES if exclude_collections else ()
    include_tag_keys: Set[str] = {tag.casefold() for tag in include_tags}
    exclude_tag_keys: Set[str] = {tag.casefold() for tag in exclude_tags}
    start = _sanitize_start_index(data.get("startIndex", 0))
    limit = _sanitize_limit(data.get("limit"))
    sort_by, sort_order = normalize_sort_params(
        data.get("sortBy"), data.get("sortOrder")
    )
    tag_cache_snapshot: Optional[TagCacheEntry] = None
    if include_tag_keys:
        missing_include_tags, tag_cache_snapshot = _missing_include_tags(
            validated_base, lib_id, user_id, include_types, include_tag_keys
        )
        if missing_include_tags:
            response_payload = {
                "TotalRecordCount": 0,
                "TotalMatchCount": 0,
                "ReturnedCount": 0,
                "Items": [],
                "SortBy": sort_by,
                "SortOrder": sort_order,
            }
            return None, jsonify(response_payload)
    tag_cache_version = tag_cache_snapshot.updated if tag_cache_snapshot else 0.0
    state = ItemsRequestState(
        base=validated_base,
        api_key=api_key,
        user_id=user_id,
        library_id=lib_id,
        include_types=tuple(include_types),
        include_tags=tuple(include_tags),
        include_tag_keys=set(include_tag_keys),
        exclude_tags=tuple(exclude_tags),
        exclude_tag_keys=set(exclude_tag_keys),
        excluded_types=tuple(excluded_types),
        title_query=str(data.get("titleQuery") or "").strip(),
        sort_by=sort_by,
        sort_order=sort_order,
        start_index=start,
        limit=limit,
        tag_cache_snapshot=tag_cache_snapshot,
        tag_cache_version=tag_cache_version,
    )
    return state, None


def _collect_matches(
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
    start_index: int,
    missing_include_tags: Optional[Set[str]],
    max_matches: Optional[int],
) -> Tuple[List[Dict[str, Any]], bool]:
    if include_tag_keys:
        missing_tags = missing_include_tags
        if missing_tags is None:
            missing_tags, _ = _missing_include_tags(
                base, lib_id, user_id, include_types, include_tag_keys
            )
        if missing_tags:
            logger.info(
                "Include tags %s missing from tag cache; returning no items",
                sorted(missing_tags),
            )
            return [], True

    fields = _prepare_fields()
    matched_items: List[Dict[str, Any]] = []
    if limit <= 0:
        logger.debug("Limit <= 0 (%s); returning empty list", limit)
        return [], True
    target_count = max_matches
    fetch_limit = min(
        AGGREGATE_FETCH_LIMIT,
        max(ITEM_PAGE_FETCH_LIMIT, limit, target_count or 0),
    )
    logger.debug(
        "Pagination fetch limit=%d (requested limit=%d max_matches=%s)",
        fetch_limit,
        limit,
        target_count,
    )
    title_query_lower = title_query.casefold() if title_query else ""
    search_term = title_query if title_query else None

    page_estimate = target_count or fetch_limit
    page_count = max(1, math.ceil(page_estimate / fetch_limit)) if page_estimate else 1
    max_prefetch_pages = min(8, max(2, page_count))
    executor = ThreadPoolExecutor(max_workers=max_prefetch_pages)
    pending: Dict[int, Any] = {}
    next_fetch_start = start_index
    next_process_start = start_index
    stop_scheduling = False
    completed_scan = True

    try:
        while True:
            while len(pending) < max_prefetch_pages and not stop_scheduling:
                start_for_fetch = next_fetch_start
                logger.debug(
                    "Queueing async page fetch start=%d limit=%d",
                    start_for_fetch,
                    fetch_limit,
                )
                pending[start_for_fetch] = executor.submit(
                    page_items,
                    base,
                    api_key,
                    user_id,
                    lib_id,
                    include_types,
                    fields,
                    start_for_fetch,
                    fetch_limit,
                    search_term=search_term,
                    exclude_types=excluded_types,
                    sort_by=sort_by,
                    sort_order=sort_order,
                )
                next_fetch_start += fetch_limit

            future = pending.get(next_process_start)
            if future is None:
                break
            payload = future.result()
            del pending[next_process_start]
            page_start = next_process_start
            next_process_start += fetch_limit
            raw_items = payload.get("Items", [])
            if not raw_items:
                logger.debug(
                    "No items returned for page start=%d limit=%d",
                    page_start,
                    fetch_limit,
                )
                stop_scheduling = True
                break

            items = raw_items
            if excluded_types:
                excluded_set = set(excluded_types)
                items = [it for it in raw_items if it.get("Type") not in excluded_set]

            stop_early = False
            for it in items:
                if item_matches_filters(
                    it, include_tag_keys, exclude_tag_keys, title_query_lower
                ):
                    matched_items.append(serialize_item_for_response(it))
                    if target_count is not None and len(matched_items) >= target_count:
                        stop_early = True
                        break

            page_size = len(raw_items)
            if stop_early:
                logger.debug(
                    "Reached required matches (%d/%s) after page starting %d",
                    len(matched_items),
                    target_count,
                    page_start,
                )
                completed_scan = False
                stop_scheduling = True
                break

            total_count = payload.get("TotalRecordCount")
            if (
                total_count is not None
                and isinstance(total_count, int)
                and page_start + page_size < total_count
            ):
                if 0 < page_size < fetch_limit:
                    fetch_limit = page_size
                continue
            if page_size < fetch_limit:
                stop_scheduling = True
                break
        return matched_items, completed_scan
    finally:
        for future in pending.values():
            future.cancel()
        executor.shutdown(wait=False)


def _filter_and_collect_items(
    state: ItemsRequestState,
) -> Tuple[List[Mapping[str, Any]], int, bool]:
    if state.limit <= 0:
        logger.debug("Limit <= 0 (%s); returning empty list", state.limit)
        return [], 0, True

    max_matches = state.start_index + state.limit
    matched_items, is_complete = _collect_matches(
        state.base,
        state.api_key,
        state.user_id,
        state.library_id,
        state.include_types,
        state.include_tag_keys,
        state.exclude_tag_keys,
        state.excluded_types,
        state.title_query,
        state.sort_by,
        state.sort_order,
        max(state.limit, ITEM_PAGE_FETCH_LIMIT),
        state.start_index,
        None,
        max_matches,
    )
    sorted_matches = sort_items_for_response(
        matched_items, state.sort_by, state.sort_order
    )
    if is_complete:
        set_prefetch_cache_entry(
            _build_prefetch_cache_key(state),
            sorted_matches,
            len(sorted_matches),
            True,
        )
    slice_end = state.start_index + state.limit
    paged_items = sorted_matches[state.start_index : slice_end]
    total_matches = len(sorted_matches)
    return paged_items, total_matches, is_complete


def _try_serve_prefetch_cache(
    state: ItemsRequestState, entry: Optional[ItemPrefetchCacheEntry]
) -> Optional[Tuple[List[Mapping[str, Any]], int]]:
    if not entry or not entry.complete:
        return None
    if state.limit <= 0:
        return [], entry.total_matches
    end_index = state.start_index + state.limit
    if end_index > len(entry.matches):
        return None
    return entry.matches[state.start_index : end_index], entry.total_matches


def _cleanup_prefetch_jobs_locked() -> None:
    now = time.time()
    expired: List[str] = []
    for job_id, job in _ITEM_PREFETCH_JOBS.items():
        if (
            job.completed_at is not None
            and (now - job.completed_at) >= ITEM_PREFETCH_JOB_TTL
        ):
            expired.append(job_id)
    for job_id in expired:
        job = _ITEM_PREFETCH_JOBS.pop(job_id)
        if job.key in _ITEM_PREFETCH_JOBS_BY_KEY:
            _ITEM_PREFETCH_JOBS_BY_KEY.pop(job.key)


def _get_prefetch_job(job_id: str) -> Optional[ItemPrefetchJob]:
    with _PREFETCH_JOB_LOCK:
        _cleanup_prefetch_jobs_locked()
        return _ITEM_PREFETCH_JOBS.get(job_id)


def _ensure_prefetch_job(state: ItemsRequestState) -> ItemPrefetchJob:
    key = _build_prefetch_cache_key(state)
    with _PREFETCH_JOB_LOCK:
        _cleanup_prefetch_jobs_locked()
        existing = _ITEM_PREFETCH_JOBS_BY_KEY.get(key)
        if existing and existing.status in {"pending", "running"}:
            return existing
        job_id = str(uuid.uuid4())
        job = ItemPrefetchJob(job_id=job_id, key=key, state=state)
        _ITEM_PREFETCH_JOBS[job_id] = job
        _ITEM_PREFETCH_JOBS_BY_KEY[key] = job
    thread = threading.Thread(target=_run_prefetch_job, args=(job,), daemon=True)
    thread.start()
    return job


def _run_prefetch_job(job: ItemPrefetchJob) -> None:
    job.status = "running"
    try:
        matched_items, is_complete = _collect_matches(
            job.state.base,
            job.state.api_key,
            job.state.user_id,
            job.state.library_id,
            job.state.include_types,
            job.state.include_tag_keys,
            job.state.exclude_tag_keys,
            job.state.excluded_types,
            job.state.title_query,
            job.state.sort_by,
            job.state.sort_order,
            AGGREGATE_FETCH_LIMIT,
            0,
            None,
            None,
        )
        sorted_matches = sort_items_for_response(
            matched_items, job.state.sort_by, job.state.sort_order
        )
        total_matches = len(sorted_matches)
        set_prefetch_cache_entry(job.key, sorted_matches, total_matches, is_complete)
        job.total_matches = total_matches
        job.status = "completed"
    except Exception as exc:
        logger.exception("Prefetch job %s failed", job.job_id)
        job.status = "failed"
        job.error = str(exc)
    finally:
        job.completed_at = time.time()
        with _PREFETCH_JOB_LOCK:
            if job.key in _ITEM_PREFETCH_JOBS_BY_KEY:
                _ITEM_PREFETCH_JOBS_BY_KEY.pop(job.key)


def _missing_include_tags(
    base: str,
    lib_id: str,
    user_id: str,
    include_types: Sequence[str],
    include_tag_keys: Set[str],
) -> Tuple[Set[str], Optional[TagCacheEntry]]:
    logger.debug(
        "Looking up tag cache for include_types=%s (base=%s lib=%s user=%s)",
        include_types,
        base,
        lib_id,
        user_id,
    )
    entry = get_tag_cache_snapshot(base, lib_id, user_id or "", include_types)
    if not entry or is_tag_cache_stale(entry):
        logger.debug(
            "Tag cache entry unavailable or stale (entry=%s)",
            "present" if entry else "missing",
        )
        return set(), None
    available = {tag.casefold() for tag in entry.tags}
    logger.debug(
        "Available tags cached=%d, requested=%d",
        len(available),
        len(include_tag_keys),
    )
    return include_tag_keys.difference(available), entry


def _fetch_items_from_server(
    base: str,
    api_key: str,
    user_id: str,
    lib_id: str,
    include_types: Sequence[str],
    excluded_types: Sequence[str],
    title_query: str,
    sort_by: str,
    sort_order: str,
    limit: int,
    start_index: int,
) -> Tuple[List[Dict[str, Any]], int]:
    if limit <= 0:
        return [], 0
    fields = _prepare_fields()
    search_term: Optional[str] = title_query if title_query else None
    payload = page_items(
        base,
        api_key,
        user_id,
        lib_id,
        include_types,
        fields,
        start_index,
        limit,
        search_term=search_term,
        exclude_types=excluded_types,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    raw_items = payload.get("Items", [])
    serialized = [serialize_item_for_response(it) for it in raw_items]
    total_count = payload.get("TotalRecordCount")
    if not isinstance(total_count, int):
        total_count = len(serialized)
    return serialized, total_count


@bp.route("/items", methods=["POST"])
def api_items():
    data = request.get_json(force=True)
    state, error_response = _parse_items_request(data, "/api/items")
    if error_response is not None:
        return error_response
    assert state is not None

    raw_user_id = data.get("userId")
    raw_lib_id = data.get("libraryId")
    if not state.user_id:
        logger.warning("POST /api/items missing required userId (raw=%r)", raw_user_id)
        return jsonify({"error": "userId is required"}), 400
    if not state.library_id:
        logger.warning(
            "POST /api/items missing required libraryId (raw=%r)", raw_lib_id
        )
        return jsonify({"error": "libraryId is required"}), 400

    logger.info(
        "POST /api/items base=%s library=%s user=%s include=%s exclude=%s start=%d limit=%d sort_by=%s sort_order=%s",
        state.base,
        state.library_id,
        state.user_id,
        state.include_tags,
        state.exclude_tags,
        state.start_index,
        state.limit,
        state.sort_by,
        state.sort_order,
    )

    cache_key = _build_items_cache_key(
        state.base,
        state.user_id,
        state.library_id,
        state.include_types,
        state.include_tag_keys,
        state.exclude_tag_keys,
        state.excluded_types,
        state.title_query,
        state.sort_by,
        state.sort_order,
        state.tag_cache_version,
        state.start_index,
        state.limit,
    )
    cached_payload = get_cached_response(cache_key)
    if cached_payload is not None:
        logger.debug("Serving cached /api/items response for %s", cache_key)
        return jsonify(cached_payload)

    delegate_to_server = not state.include_tag_keys and not state.exclude_tag_keys
    prefetch_key = _build_prefetch_cache_key(state)
    prefetch_entry = get_prefetch_cache_entry(prefetch_key)

    if not delegate_to_server:
        cached_slice = _try_serve_prefetch_cache(state, prefetch_entry)
        if cached_slice is not None:
            paged_items, total_matches = cached_slice
            response_payload = {
                "TotalRecordCount": total_matches,
                "TotalMatchCount": total_matches,
                "ReturnedCount": len(paged_items),
                "Items": paged_items,
                "SortBy": state.sort_by,
                "SortOrder": state.sort_order,
            }
            set_cached_response(cache_key, response_payload)
            return jsonify(response_payload)

        if state.start_index >= ITEM_PREFETCH_TRIGGER_START_INDEX and (
            prefetch_entry is None
            or not prefetch_entry.complete
            or state.start_index + state.limit > len(prefetch_entry.matches)
        ):
            job = _ensure_prefetch_job(state)
            message = f"Prefetch job {job.job_id} running; poll /api/items/prefetch/{job.job_id}"
            return (
                jsonify(
                    {
                        "jobId": job.job_id,
                        "status": job.status,
                        "message": message,
                    }
                ),
                202,
            )

    if delegate_to_server:
        paged_items, total_matches = _fetch_items_from_server(
            state.base,
            state.api_key,
            state.user_id,
            state.library_id,
            state.include_types,
            state.excluded_types,
            state.title_query,
            state.sort_by,
            state.sort_order,
            state.limit,
            state.start_index,
        )
        filtered_total = total_matches
        returned_count = len(paged_items)
    else:
        paged_items, total_matches, _ = _filter_and_collect_items(state)
        filtered_total = total_matches
        returned_count = len(paged_items)

    logger.info(
        "/api/items returning %d/%d items (excluded_types=%s)",
        returned_count,
        filtered_total,
        list(state.excluded_types),
    )
    response_payload = {
        "TotalRecordCount": filtered_total,
        "TotalMatchCount": total_matches,
        "ReturnedCount": returned_count,
        "Items": paged_items,
        "SortBy": state.sort_by,
        "SortOrder": state.sort_order,
    }
    set_cached_response(cache_key, response_payload)
    return jsonify(response_payload)


@bp.route("/items/prefetch", methods=["POST"])
def api_items_prefetch():
    data = request.get_json(force=True)
    state, error_response = _parse_items_request(data, "/api/items/prefetch")
    if error_response is not None:
        return error_response
    assert state is not None

    raw_user_id = data.get("userId")
    raw_lib_id = data.get("libraryId")
    if not state.user_id:
        logger.warning(
            "POST /api/items/prefetch missing required userId (raw=%r)",
            raw_user_id,
        )
        return jsonify({"error": "userId is required"}), 400
    if not state.library_id:
        logger.warning(
            "POST /api/items/prefetch missing required libraryId (raw=%r)",
            raw_lib_id,
        )
        return jsonify({"error": "libraryId is required"}), 400

    job = _ensure_prefetch_job(state)
    entry = get_prefetch_cache_entry(job.key)
    payload = {
        "jobId": job.job_id,
        "status": job.status,
        "availableMatches": len(entry.matches) if entry else 0,
        "totalMatches": entry.total_matches if entry else job.total_matches,
        "pollUrl": f"/api/items/prefetch/{job.job_id}",
    }
    status_code = 200 if job.status == "completed" else 202
    return jsonify(payload), status_code


@bp.route("/items/prefetch/<job_id>", methods=["GET"])
def api_items_prefetch_status(job_id: str):
    job = _get_prefetch_job(job_id)
    if job is None:
        return jsonify({"error": "prefetch job not found"}), 404
    entry = get_prefetch_cache_entry(job.key)
    payload = {
        "jobId": job.job_id,
        "status": job.status,
        "totalMatches": entry.total_matches if entry else job.total_matches,
        "availableMatches": len(entry.matches) if entry else 0,
        "complete": entry.complete if entry else False,
    }
    if job.completed_at is not None:
        payload["completedAt"] = job.completed_at
    if job.error:
        payload["error"] = job.error
    return jsonify(payload)


@bp.route("/export", methods=["POST"])
def api_export():
    data = request.get_json(force=True)
    base, api_key = resolve_jellyfin_config(data)
    validated_base, error = validate_base(base, "/api/export", data.get("base"))
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
        validated_base or "",
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
    assert validated_base is not None
    base = validated_base
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
    return send_file(  # type: ignore[arg-type]
        mem, mimetype="text/csv", as_attachment=True, download_name="tags_export.csv"
    )
