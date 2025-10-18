"""Configuration constants and environment bootstrap utilities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv  # type: ignore[import-not-found]

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
ENV_PATH = PROJECT_ROOT / ".env"

COLLECTION_ITEM_TYPES: Tuple[str, ...] = ("BoxSet", "CollectionFolder")
TAG_PAGE_LIMIT = 200
MAX_TAG_PAGES = 100

DEFAULT_SORT_BY = "SortName"
DEFAULT_SORT_ORDER = "Ascending"
SORTABLE_FIELDS: Tuple[str, ...] = ("SortName", "PremiereDate")
SORT_ORDERS: Tuple[str, ...] = ("Ascending", "Descending")

UPDATE_FIELDS: Tuple[str, ...] = (
    "Id",
    "Name",
    "SortName",
    "Overview",
    "Genres",
    "Tags",
    "ProviderIds",
    "CommunityRating",
    "CriticRating",
    "OfficialRating",
    "ProductionYear",
    "PremiereDate",
    "EndDate",
    "Taglines",
    "People",
    "Studios",
)


def load_environment() -> None:
    """Load variables from the optional project-level ``.env`` file."""
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH)
    else:
        logging.getLogger(__name__).warning("Missing .env file at %s", ENV_PATH)
