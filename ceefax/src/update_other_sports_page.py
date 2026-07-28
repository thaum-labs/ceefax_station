"""
Update page 305 with other sports news from BBC Sport.
"""
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def fetch_other_sports() -> Dict[str, List[str]]:
    """
    Fetch other sports news from BBC Sport RSS feeds.
    """
    sports_data = {
        "rugby": [],
        "cricket": [],
        "tennis": [],
        "motorsport": []
    }
    
    # BBC Sport RSS feeds for different sports
    feeds = {
        "rugby": "https://feeds.bbci.co.uk/sport/rugby-union/rss.xml",
        "cricket": "https://feeds.bbci.co.uk/sport/cricket/rss.xml",
        "tennis": "https://feeds.bbci.co.uk/sport/tennis/rss.xml",
        "motorsport": "https://feeds.bbci.co.uk/sport/formula1/rss.xml"
    }
    
    for sport, url in feeds.items():
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            
            root = ET.fromstring(resp.content)
            items = root.findall("./channel/item/title")
            for item in items[:3]:  # Get top 3 headlines per sport
                if item.text:
                    sports_data[sport].append(item.text.strip()[:PAGE_WIDTH])
        except Exception:  # noqa: BLE001
            # Keep empty list if feed fails
            pass
    
    return sports_data


def resolve_other_sports() -> ProviderResult[Dict[str, List[str]]]:
    """Resolve and cache one combined normalized result for all BBC feeds."""
    return resolve_provider(
        "other-sports-305",
        [("BBC Sport RSS", fetch_other_sports)],
        is_valid=lambda data: isinstance(data, dict)
        and any(isinstance(items, list) and items for items in data.values()),
    )


def build_other_sports_page(
    result: ProviderResult[Dict[str, List[str]]] | None = None,
) -> List[str]:
    """Build other sports page."""
    lines: List[str] = []
    lines.append(_pad("OTHER SPORTS"))
    result = result or resolve_other_sports()
    data = result.data
    lines.append(_pad(f"Source: {result.source}"))
    stale = " | STALE" if result.stale else ""
    lines.append(_pad(f"As-of: {result.fetched_at}{stale}"))

    sep = _pad("-" * PAGE_WIDTH)

    for key, heading in (
        ("rugby", "RUGBY"),
        ("cricket", "CRICKET"),
        ("tennis", "TENNIS"),
        ("motorsport", "MOTORSPORT"),
    ):
        lines.append(_pad(heading))
        lines.append(sep)
        headlines = data.get(key, [])
        if headlines:
            for headline in headlines[:2]:
                lines.append(_pad(headline))
        else:
            lines.append(_pad("Feed temporarily unavailable"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 305 with other sports news."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "305.json"
    
    result = resolve_other_sports()
    content = build_other_sports_page(result)
    
    page = {
        "page": "305",
        "title": "Other Sports",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with other sports news")


if __name__ == "__main__":
    main()

