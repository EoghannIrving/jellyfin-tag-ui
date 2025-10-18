"""HTTP client helpers for interacting with the Jellyfin API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

import requests  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def jf_headers(api_key: str) -> Dict[str, str]:
    return {"X-Emby-Token": api_key}


def jf_get(
    url: str,
    api_key: str,
    params: Optional[Mapping[str, Any]] = None,
    timeout: int = 30,
):
    logger.debug("GET %s params=%s", url, params)
    response = requests.get(
        url, headers=jf_headers(api_key), params=params or {}, timeout=timeout
    )
    response.raise_for_status()
    return response.json()


def _parse_json_response(response: requests.Response) -> Dict[str, Any]:
    if response.text and response.headers.get("content-type", "").startswith(
        "application/json"
    ):
        return response.json()
    return {}


def jf_post(
    url: str,
    api_key: str,
    params: Optional[Mapping[str, Any]] = None,
    json: Optional[Mapping[str, Any]] = None,
    timeout: int = 30,
):
    logger.debug("POST %s params=%s json=%s", url, params, json)
    response = requests.post(
        url,
        headers=jf_headers(api_key),
        params=params or {},
        json=json,
        timeout=timeout,
    )
    response.raise_for_status()
    return _parse_json_response(response)


def jf_put(
    url: str,
    api_key: str,
    params: Optional[Mapping[str, Any]] = None,
    json: Optional[Mapping[str, Any]] = None,
    timeout: int = 30,
):
    logger.debug("PUT %s params=%s json=%s", url, params, json)
    response = requests.put(
        url,
        headers=jf_headers(api_key),
        params=params or {},
        json=json,
        timeout=timeout,
    )
    response.raise_for_status()
    return _parse_json_response(response)


def _is_unsupported_method_error(error: requests.HTTPError) -> bool:
    response = getattr(error, "response", None)
    if response is None:
        return False
    return getattr(response, "status_code", None) in {405, 501}


def jf_put_with_fallback(
    url: str,
    api_key: str,
    json: Optional[Mapping[str, Any]] = None,
    timeout: int = 30,
):
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
