"""
Update page 401 with TFL (Transport for London) status information.

Uses TFL Unified API (free, no API key required).
"""
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


TFL_API_BASE = "https://api.tfl.gov.uk"


def fetch_tfl_line_status() -> List[Dict]:
    """
    Fetch TFL line status from TFL Unified API.
    Returns list of line statuses with name and status.
    """
    url = f"{TFL_API_BASE}/Line/Mode/tube,dlr,overground,elizabeth-line/Status"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("TfL returned a non-list response")

    line_statuses = []
    for line_group in data:
        if not isinstance(line_group, dict):
            continue
        line_name = line_group.get("name", "Unknown")
        line_statuses_list = line_group.get("lineStatuses", [])

        status_text = "Good Service"
        for status in line_statuses_list:
            status_severity = status.get("statusSeverity", 10)
            status_description = status.get("statusSeverityDescription", "")
            reason = status.get("reason", "")
            if status_severity < 10:
                status_text = status_description
                if reason:
                    status_text = f"{status_description}: {reason[:30]}"
                break

        line_statuses.append({"name": str(line_name), "status": str(status_text)})
    return line_statuses


def resolve_travel_status() -> ProviderResult[List[Dict]]:
    """Resolve live TfL status or the last valid normalized response."""
    return resolve_provider(
        "travel-401",
        [("TfL Unified API", fetch_tfl_line_status)],
        is_valid=lambda data: bool(data)
        and all(isinstance(item, dict) and item.get("name") for item in data),
    )


def build_travel_page(result: ProviderResult[List[Dict]] | None = None) -> List[str]:
    """Build travel information page with TFL statuses in table format."""
    lines: List[str] = []
    lines.append(_pad("TRAVEL INFORMATION"))
    lines.append(_pad(""))
    
    # TFL Status section - table format like page 210
    lines.append(_pad("TFL STATUS"))
    sep = _pad("-" * PAGE_WIDTH)
    lines.append(sep)
    
    result = result or resolve_travel_status()
    for line_info in result.data[:12]:
        name = line_info.get("name", "Unknown")
        status = line_info.get("status", "Unknown")
        if len(status) > 25:
            status = status[:22] + "..."
        lines.append(_pad(f"{name:<18} {status}"[:PAGE_WIDTH]))

    lines.append(_pad(""))
    lines.append(_pad(f"Source: {result.source}"))
    stale = " | STALE" if result.stale else ""
    lines.append(_pad(f"As-of: {result.fetched_at}{stale}"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 401 with TFL travel information."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "401.json"
    
    result = resolve_travel_status()
    content = build_travel_page(result)
    
    page = {
        "page": "401",
        "title": "Travel Info",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with TFL travel information")


if __name__ == "__main__":
    main()

