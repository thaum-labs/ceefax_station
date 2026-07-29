"""Station helpers for hub page packs and refresh orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from .page_pack import apply_pack_bytes
from .paths import pages_dir as default_pages_dir


DEFAULT_HUB_URL = "https://ceefaxstation.com"
DEFAULT_PAGES_SOURCE = "auto"  # auto | hub | local


def pages_source(override: str | None = None) -> str:
    value = (override or os.environ.get("CEEFAX_PAGES_SOURCE") or DEFAULT_PAGES_SOURCE).strip().lower()
    if value not in {"auto", "hub", "local"}:
        return DEFAULT_PAGES_SOURCE
    return value


def hub_base_url(override: str | None = None) -> str:
    return (override or os.environ.get("CEEFAX_PAGES_HUB_URL") or DEFAULT_HUB_URL).strip().rstrip("/")


def pull_page_pack(
    *,
    pages_dir: Path | None = None,
    hub_url: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Download /api/pages/pack and apply shared pages. Preserves 102/700."""
    target = pages_dir or default_pages_dir()
    base = hub_base_url(hub_url)
    url = f"{base}/api/pages/pack"
    response = requests.get(
        url,
        timeout=timeout,
        headers={"Accept": "application/zip, application/json", "User-Agent": "CeefaxStation/1.0"},
    )
    if response.status_code == 404:
        raise RuntimeError(
            "Hub has no published page pack yet. "
            "Official hub page pack is unavailable; try again later or use --pages-source local"
        )
    if response.status_code == 429:
        raise RuntimeError("Hub page-pack rate limit exceeded; try again shortly")
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise RuntimeError(f"Hub did not return a zip pack ({response.status_code})")
    return apply_pack_bytes(pack_bytes=response.content, pages_dir=target)


def refresh_local_only_pages(*, user_location: tuple[str, str] | None = None) -> None:
    """Refresh station-specific pages after a hub pull."""
    from . import update_about_page, update_callsign_page, update_start_page, update_weather_page
    from . import update_all as update_all_mod
    from .update_all import auto_detect_location_silent

    try:
        update_start_page.main()
    except Exception as exc:  # noqa: BLE001
        print(f"Start page (000) refresh failed: {exc}")

    loc = user_location or getattr(update_all_mod, "_user_location", None)
    if loc is None:
        loc = auto_detect_location_silent()

    try:
        update_weather_page.main(user_location=loc)
    except Exception as exc:  # noqa: BLE001
        print(f"Local weather (102) refresh failed: {exc}")

    try:
        update_callsign_page.main()
    except Exception as exc:  # noqa: BLE001
        print(f"Callsign page (700) refresh failed: {exc}")

    try:
        update_about_page.main()
    except Exception as exc:  # noqa: BLE001
        print(f"About page (900) refresh failed: {exc}")


def _needs_station_setup(callsign: str | None) -> bool:
    value = (callsign or "").strip().upper()
    return value in {"", "TEST", "N0CALL", "N0CALL-1", "YOUR_CALLSIGN", "YOURCALL"}


def refresh_station_pages(
    *,
    callsign: str | None = None,
    frequency: str | None = None,
    location: tuple[str, str] | None = None,
    auto_location: bool = True,
    source: str | None = None,
    hub_url: str | None = None,
    pages_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Refresh pages according to CEEFAX_PAGES_SOURCE (default: auto).

    auto/hub: pull shared pack from hub, then refresh local-only pages
    local: run full update_all() with local API keys / free sources
    auto falls back to local if hub pull fails
    """
    from .paths import ceefax_root
    from .update_all import (
        get_user_callsign_and_frequency,
        get_user_location,
        prime_user_settings,
        update_all,
    )

    # Prefer an already-saved callsign unless the caller overrode it.
    saved_callsign = None
    saved_frequency = None
    try:
        import json

        cfg_path = ceefax_root() / "radio_config.json"
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                saved_callsign = str(data.get("callsign") or "").strip().upper() or None
                saved_frequency = str(data.get("frequency") or "").strip() or None
    except Exception:  # noqa: BLE001
        pass

    effective_callsign = (callsign.strip().upper() if callsign else None) or saved_callsign
    effective_frequency = frequency if frequency is not None else saved_frequency

    if _needs_station_setup(effective_callsign):
        print()
        print("Station setup required (callsign not configured).")
        prompted_cs, prompted_freq = get_user_callsign_and_frequency()
        if prompted_cs:
            effective_callsign = prompted_cs
        if prompted_freq:
            effective_frequency = prompted_freq
        if location is None:
            location = get_user_location()

    prime_user_settings(
        callsign=effective_callsign,
        frequency=effective_frequency,
        location=location,
        auto_location=auto_location,
    )

    mode = pages_source(source)
    target = pages_dir or default_pages_dir()

    if mode in {"hub", "auto"}:
        try:
            print(f"Pulling shared pages from hub ({hub_base_url(hub_url)}) ...")
            manifest = pull_page_pack(pages_dir=target, hub_url=hub_url)
            print(
                f"Hub pack OK: {manifest.get('page_count')} pages "
                f"(generated {manifest.get('generated_at')})"
            )
            print("Refreshing local-only pages (000, 102, 700, 900) ...")
            refresh_local_only_pages()
            return {"mode": "hub", "manifest": manifest}
        except Exception as exc:  # noqa: BLE001
            print(f"Hub pull failed: {exc}")
            if mode == "hub":
                raise
            print("Falling back to local page refresh ...")

    print("Refreshing pages locally ...")
    update_all()
    return {"mode": "local"}
