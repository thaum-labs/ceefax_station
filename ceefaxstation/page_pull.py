"""Download shared teletext pages from the Ceefax Station hub."""

from __future__ import annotations

# Re-export station helpers from ceefax.src.hub_pages for CLI convenience.
from ceefax.src.hub_pages import (  # noqa: F401
    DEFAULT_HUB_URL,
    DEFAULT_PAGES_SOURCE,
    fetch_hub_manifest,
    hub_base_url,
    hub_pack_is_newer,
    pages_source,
    pull_page_pack,
    refresh_local_only_pages,
    refresh_station_pages,
    sync_hub_pack,
)
