"""Configuration for the IIIF Image API server."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SEARCH_DIRS: tuple = ("/data/images",)

DEFAULT_IMAGE_DB: str = "/data/images.db"

DEFAULT_MAX_WIDTH = 4000
DEFAULT_MAX_HEIGHT = 4000
DEFAULT_MAX_AREA: int | None = None

DEFAULT_INFO_VERSION = "3"  # "2" or "3"

DEFAULT_TILE_CACHE_DIR = "/data/iiif-cache"


class Settings:
    """Runtime settings for the IIIF image server."""

    @property
    def search_dirs(self) -> list:
        raw = os.environ.get("IIIF_IMAGE_DIRS") or os.environ.get(
            "IIIF_IMAGE_SERVICE_DIRS"
        )
        if not raw:
            return list(DEFAULT_SEARCH_DIRS)
        return [d.strip() for d in raw.split(",") if d and d.strip()]

    @property
    def image_db(self) -> str:
        return os.environ.get("IIIF_IMAGE_DB") or DEFAULT_IMAGE_DB

    @property
    def max_width(self) -> int:
        return int(os.environ.get("IIIF_MAX_WIDTH") or DEFAULT_MAX_WIDTH)

    @property
    def max_height(self) -> int:
        return int(os.environ.get("IIIF_MAX_HEIGHT") or DEFAULT_MAX_HEIGHT)

    @property
    def max_area(self) -> int | None:
        raw = os.environ.get("IIIF_MAX_AREA")
        if not raw:
            return DEFAULT_MAX_AREA
        return int(raw)

    @property
    def info_version(self) -> str:
        return os.environ.get("IIIF_IMAGE_API_VERSION") or DEFAULT_INFO_VERSION

    @property
    def tile_cache_dir(self) -> str:
        return os.environ.get("IIIF_CACHE_DIR") or DEFAULT_TILE_CACHE_DIR


settings = Settings()
