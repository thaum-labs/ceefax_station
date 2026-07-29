"""Update page 000 — Ceefax Station start / logo page."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .compiler import PAGE_HEIGHT, PAGE_WIDTH
from .paths import pages_dir
from .providers import atomic_write_json


# Block-character logo created for Ceefax Station (also used on the website / README).
CEEFAX_STATION_LOGO = (
    "  ░█▀▀░█▀▀░█▀▀░█▀▀░█▀█░█░█░░",
    "  ░█░░░█▀▀░█▀▀░█▀▀░█▀█░▄▀▄░░",
    "  ░▀▀▀░▀▀▀░▀▀▀░▀░░░▀░▀░▀░▀░░",
    "░█▀▀░▀█▀░█▀█░▀█▀░▀█▀░█▀█░█▀█",
    "░▀▀█░░█░░█▀█░░█░░░█░░█░█░█░█",
    "░▀▀▀░░▀░░▀░▀░░▀░░▀▀▀░▀▀▀░▀░▀",
)


def _pad(text: str) -> str:
    return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)


def build_start_page() -> List[str]:
    """Build the start page with logo, callsign placeholder, and credits."""
    lines: List[str] = [""]
    lines.extend(CEEFAX_STATION_LOGO)
    lines.append("")
    # Viewer substitutes {{users callsign}} with the configured callsign at display time.
    lines.append("{{users callsign}} TELETEX SERVICE")
    lines.append("")
    lines.append("Press 100 for MAIN INDEX")
    lines.append("Use n/p to browse pages")
    lines.append("")
    lines.append("created by M7TJF")
    return [_pad(line) for line in lines[: PAGE_HEIGHT - 2]]


def main() -> None:
    """Write pages/000.json (station-local; not overwritten by hub packs)."""
    page_file = pages_dir() / "000.json"
    page = {
        "page": "000",
        "title": "Start",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subpage": 1,
        "content": build_start_page(),
    }
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with Ceefax Station start page")


if __name__ == "__main__":
    main()
