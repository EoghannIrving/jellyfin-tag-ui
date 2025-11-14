"""HTTP client helpers for interacting with the Jellyfin API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

import requests  # type: ignore[import-untyped]

from .config import JELLYFIN_TIMEOUT

logger = logging.getLogger(__name__)


def jf_headers(api_key: str) -> Dict[str, str]:
    return {"X-Emby-Token": api_key}


def _extract_error_details(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""

    if not isinstance(payload, Mapping):
        return ""

    details = []
    seen = set()

    def add_detail(value: Any, prefix: str = "") -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        detail = f"{prefix}{text}" if prefix else text
        if detail in seen:
            return
        seen.add(detail)
        details.append(detail)

    add_detail(payload.get("Message") or payload.get("message"))
    error_code = payload.get("ErrorCode") or payload.get("errorCode")
    if error_code is not None:
        add_detail(error_code, "ErrorCode=")

    response_status = payload.get("ResponseStatus") or payload.get("responseStatus")
    if isinstance(response_status, Mapping):
        add_detail(response_status.get("Message") or response_status.get("message"))
        rs_error_code = response_status.get("ErrorCode") or response_status.get(
            "errorCode"
        )
        if rs_error_code is not None:
            add_detail(rs_error_code, "ResponseStatus.ErrorCode=")
    elif response_status:
        add_detail(response_status, "ResponseStatus=")

    return "; ".join(details)


def format_http_error(error: requests.HTTPError) -> str:
    response = getattr(error, "response", None)
    base_message = str(error).strip()

    if response is None:
        return base_message or "HTTP request failed"

    details = _extract_error_details(response)
    if details:
        if base_message:
            return f"{base_message} - {details}"
        status_code = getattr(response, "status_code", "")
        reason = getattr(response, "reason", "") or ""
        url = getattr(response, "url", "") or ""
        status_message = f"HTTP {status_code}" if status_code else "HTTP request failed"
        if reason:
            status_message = f"{status_message} {reason}"
        if url:
            status_message = f"{status_message} for url: {url}"
        return f"{status_message} - {details}" if status_message else details

    return base_message or "HTTP request failed"


def _raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise requests.HTTPError(
            format_http_error(error),
            response=error.response,
            request=getattr(error, "request", None),
        ) from error


def jf_get(
    url: str,
    api_key: str,
    params: Optional[Mapping[str, Any]] = None,
    timeout: Optional[int] = None,
):
    logger.debug("GET %s params=%s", url, params)
    effective_timeout = timeout if timeout is not None else JELLYFIN_TIMEOUT
    response = requests.get(
        url,
        headers=jf_headers(api_key),
        params=params or {},
        timeout=effective_timeout,
    )
    _raise_for_status(response)
    return response.json()


def _parse_json_response(response: requests.Response) -> Dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if isinstance(content_type, str):
        normalized_content_type = content_type.lower()
    else:
        normalized_content_type = ""
    if response.text and normalized_content_type.startswith("application/json"):
        return response.json()
    return {}


def jf_post(
    url: str,
    api_key: str,
    params: Optional[Mapping[str, Any]] = None,
    json: Optional[Mapping[str, Any]] = None,
    timeout: Optional[int] = None,
):
    logger.debug("POST %s params=%s json=%s", url, params, json)
    effective_timeout = timeout if timeout is not None else JELLYFIN_TIMEOUT
    response = requests.post(
        url,
        headers=jf_headers(api_key),
        params=params or {},
        json=json,
        timeout=effective_timeout,
    )
    _raise_for_status(response)
    return _parse_json_response(response)


def jf_put(
    url: str,
    api_key: str,
    params: Optional[Mapping[str, Any]] = None,
    json: Optional[Mapping[str, Any]] = None,
    timeout: Optional[int] = None,
):
    logger.debug("PUT %s params=%s json=%s", url, params, json)
    effective_timeout = timeout if timeout is not None else JELLYFIN_TIMEOUT
    response = requests.put(
        url,
        headers=jf_headers(api_key),
        params=params or {},
        json=json,
        timeout=effective_timeout,
    )
    _raise_for_status(response)
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
