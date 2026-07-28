"""
Update page 500 with fact of the day from API.
"""
from datetime import datetime
from pathlib import Path
from typing import Callable, List

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def _fetch_fact(url: str, parser: Callable[[requests.Response], str]) -> str:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    fact = parser(response)
    if not isinstance(fact, str) or len(fact.strip()) <= 10:
        raise ValueError("fact API returned an invalid fact")
    return fact.strip()


def fetch_fact_of_the_day() -> str:
    """Fetch a fact using the existing live provider chain."""
    return resolve_fact_of_the_day().data


def resolve_fact_of_the_day() -> ProviderResult[str]:
    """Cache and return the first valid result in the fact provider chain."""
    return resolve_provider(
        "fact-500",
        [
            (
                "Cat Facts API",
                lambda: _fetch_fact(
                    "https://catfact.ninja/fact",
                    lambda response: response.json().get("fact", ""),
                ),
            ),
            (
                "Numbers API",
                lambda: _fetch_fact(
                    "https://numbersapi.com/random/trivia?json",
                    lambda response: response.json().get("text", ""),
                ),
            ),
            (
                "Useless Facts API",
                lambda: _fetch_fact(
                    "https://uselessfacts.jsph.pl/random.txt",
                    lambda response: response.text,
                ),
            ),
        ],
        is_valid=lambda fact: isinstance(fact, str) and len(fact) > 10,
    )


def build_fact_page(result: ProviderResult[str] | None = None) -> List[str]:
    """Build fact of the day page."""
    lines: List[str] = []
    lines.append(_pad("FACT OF THE DAY"))
    lines.append(_pad("-" * PAGE_WIDTH))
    result = result or resolve_fact_of_the_day()
    lines.append(_pad(f"Source: {result.source}"))
    stale = " | STALE" if result.stale else ""
    lines.append(_pad(f"As-of: {result.fetched_at}{stale}"))
    lines.append(_pad(""))
    lines.append(_pad("Did you know?"))
    lines.append(_pad(""))

    words = result.data.split()
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
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 500 with fact of the day."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "500.json"
    
    result = resolve_fact_of_the_day()
    content = build_fact_page(result)
    
    page = {
        "page": "500",
        "title": "Fact of the Day",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with fact of the day")


if __name__ == "__main__":
    main()

