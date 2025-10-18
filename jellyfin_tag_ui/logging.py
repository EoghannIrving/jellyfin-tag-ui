"""Logging helpers for the Jellyfin Tag UI application."""

from __future__ import annotations

import logging
import os


def configure_logging() -> logging.Logger:
    """Configure the root logging handler and return the package logger."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger("jellyfin_tag_ui")
