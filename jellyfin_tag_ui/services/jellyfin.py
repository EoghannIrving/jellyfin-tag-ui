"""Helpers for resolving Jellyfin connection information."""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Optional, Tuple

from flask import jsonify
from flask.typing import ResponseReturnValue


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


def validate_base(
    base: Optional[str], endpoint: str, raw_base: Any = None
) -> Tuple[Optional[str], Optional[ResponseReturnValue]]:
    normalized = _normalized_base(base)
    if not normalized:
        logging.getLogger(__name__).warning(
            "POST %s missing Jellyfin base URL (raw=%r)", endpoint, raw_base
        )
        return None, (jsonify({"error": "Jellyfin base URL is required"}), 400)
    return normalized, None


__all__ = ["resolve_jellyfin_config", "validate_base"]
