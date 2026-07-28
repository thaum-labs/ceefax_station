"""
Update page 600 with joke of the day from API.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, ProviderUnavailable, atomic_write_json, resolve_provider


JOKE_API_URL = "https://v2.jokeapi.dev/joke/Any"
LOCAL_SAFE_JOKES = (
    ("Why did the computer visit the doctor?", "It had caught a virus."),
    ("Why was the maths book unhappy?", "It had too many problems."),
    ("What do you call a sleeping bull?", "A bulldozer."),
)


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def fetch_jokeapi() -> Tuple[str, str]:
    response = requests.get(
        JOKE_API_URL,
        params={"safe-mode": "", "type": "twopart"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error") or data.get("type") != "twopart":
        raise ValueError("JokeAPI returned no safe two-part joke")
    setup, punchline = data.get("setup"), data.get("delivery")
    if not setup or not punchline:
        raise ValueError("JokeAPI returned incomplete joke data")
    return str(setup), str(punchline)


def fetch_joke_of_the_day(today: datetime | None = None) -> ProviderResult[Tuple[str, str]]:
    try:
        return resolve_provider("joke-600", [("JokeAPI safe mode", fetch_jokeapi)])
    except ProviderUnavailable:
        day = (today or datetime.now()).date().toordinal()
        joke = LOCAL_SAFE_JOKES[day % len(LOCAL_SAFE_JOKES)]
        return ProviderResult(joke, "Local safe jokes", (today or datetime.now()).isoformat(), False)


def build_joke_page(result: ProviderResult[Tuple[str, str]] | None = None) -> List[str]:
    """Build joke of the day page."""
    result = result or fetch_joke_of_the_day()
    setup, punchline = result.data
    lines: List[str] = []
    lines.append(_pad("JOKE OF THE DAY"))
    lines.append(_pad("-" * PAGE_WIDTH))
    lines.append(_pad(""))

    for text in (setup, punchline):
        words = text.split()
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= PAGE_WIDTH:
                current_line = f"{current_line} {word}".strip()
            else:
                if current_line:
                    lines.append(_pad(current_line))
                current_line = word
        if current_line:
            lines.append(_pad(current_line))
        lines.append(_pad(""))

    lines.append(_pad("-" * PAGE_WIDTH))
    lines.append(_pad(""))
    state = "Stale/as-of" if result.stale else "As-of"
    lines.append(_pad(f"Source: {result.source} | {state}"))

    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 600 with joke of the day."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "600.json"
    
    result = fetch_joke_of_the_day()
    content = build_joke_page(result)
    
    page = {
        "page": "600",
        "title": "Joke of the Day",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with joke of the day")


if __name__ == "__main__":
    main()

