"""Logging helpers for the Jellyfin Tag UI application."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .config import PROJECT_ROOT


def configure_logging() -> logging.Logger:
    """Configure the root logging handler and return the package logger."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    root = logging.getLogger()
    while root.handlers:
        root.handlers.pop()

    root.setLevel(getattr(logging, log_level, logging.INFO))
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    log_file_env = os.getenv("LOG_FILE")
    log_file = (
        Path(log_file_env)
        if log_file_env
        else PROJECT_ROOT / "logs" / "jellyfin_tag_ui.log"
    )
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, log_level, logging.INFO))
        root.addHandler(file_handler)
    except OSError as error:
        root.warning("Unable to open log file %s (%s)", log_file, error)

    return logging.getLogger("jellyfin_tag_ui")
