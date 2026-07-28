"""
Update page 502 with historical events that happened on this day.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider


WIKIMEDIA_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{month:02d}/{day:02d}"
WIKIMEDIA_USER_AGENT = "CeefaxStation/1.0 (non-commercial; contact via repository)"


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def fetch_wikimedia_on_this_day(today: datetime | None = None) -> Dict:
    """Fetch historical events from Wikimedia's supported REST feed."""
    today = today or datetime.now()
    response = requests.get(
        WIKIMEDIA_URL.format(month=today.month, day=today.day),
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    raw_events = payload.get("events") if isinstance(payload, dict) else None
    events = [
        f"{event['year']} - {event['text']}"
        for event in (raw_events or [])[:5]
        if isinstance(event, dict) and event.get("year") is not None and event.get("text")
    ]
    if not events:
        raise ValueError("Wikimedia returned no events for today")
    return {"date": f"{today.day} {today.strftime('%B').upper()}", "events": events}


def fetch_on_this_day(today: datetime | None = None) -> ProviderResult[Dict]:
    return resolve_provider(
        "on-this-day-502",
        [("Wikimedia On This Day", lambda: fetch_wikimedia_on_this_day(today))],
    )


def build_on_this_day_page(result: ProviderResult[Dict] | None = None) -> List[str]:
    """Build on this day page."""
    result = result or fetch_on_this_day()
    data = result.data
    lines: List[str] = []
    lines.append(_pad("ON THIS DAY"))
    lines.append(_pad(""))

    date_str = data.get("date", "")
    if date_str:
        lines.append(_pad(date_str))

    sep = _pad("-" * PAGE_WIDTH)
    lines.append(sep)
    lines.append(_pad(""))

    events = data.get("events", [])
    for event in events:
        event_lines: List[str] = []
        if len(event) <= PAGE_WIDTH:
            event_lines.append(_pad(event))
        else:
            words = event.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 <= PAGE_WIDTH:
                    if current_line:
                        current_line += " " + word
                    else:
                        current_line = word
                else:
                    if current_line:
                        event_lines.append(_pad(current_line))
                    current_line = word
            if current_line:
                event_lines.append(_pad(current_line))
        if len(lines) + len(event_lines) + 4 > PAGE_HEIGHT:
            break
        lines.extend(event_lines)
        lines.append(_pad(""))

    lines.append(sep)
    lines.append(_pad(""))
    state = "Stale/as-of" if result.stale else "As-of"
    lines.append(_pad(f"Source: Wikimedia | {state} {result.fetched_at}"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 502 with on this day events."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "502.json"
    
    result = fetch_on_this_day()
    content = build_on_this_day_page(result)
    
    page = {
        "page": "502",
        "title": "On This Day",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with on this day events")


if __name__ == "__main__":
    main()

