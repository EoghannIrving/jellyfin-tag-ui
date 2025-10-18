"""Blueprint serving the main HTML interface."""

from __future__ import annotations

import logging
import os

from flask import Blueprint, render_template

bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def index():
    base_url = os.getenv("JELLYFIN_BASE_URL", "")
    api_key = os.getenv("JELLYFIN_API_KEY", "")
    logger.info(
        "GET / - rendering index (base_url_configured=%s, api_key_configured=%s)",
        bool(base_url),
        bool(api_key),
    )
    return render_template("index.html", base_url=base_url, api_key=api_key)
