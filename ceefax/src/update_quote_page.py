"""Update page 501 from a curated public-domain quote collection."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import List, Tuple

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import atomic_write_json


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


QUOTES_PATH = Path(__file__).resolve().parent.parent / "data" / "public_domain_quotes.json"


def fetch_quote_of_the_day(day: date | None = None) -> Tuple[str, str]:
    """Select a stable quote for a calendar day, without network access."""
    quotes = json.loads(QUOTES_PATH.read_text(encoding="utf-8"))
    if not isinstance(quotes, list) or not quotes:
        raise ValueError("public-domain quote collection is empty")
    selected = quotes[(day or date.today()).toordinal() % len(quotes)]
    return str(selected["quote"]), str(selected["author"])


def build_quote_page() -> List[str]:
    """Build quote of the day page."""
    lines: List[str] = []
    lines.append(_pad("QUOTE OF THE DAY"))
    lines.append(_pad("-" * PAGE_WIDTH))
    lines.append(_pad(""))
    
    quote, author = fetch_quote_of_the_day()

    words = quote.split()
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 <= PAGE_WIDTH - 2:
            if current_line:
                current_line += " " + word
            else:
                current_line = f'"{word}'
        else:
            if current_line:
                if not current_line.endswith('"'):
                    current_line += '"'
                lines.append(_pad(current_line))
            current_line = f'"{word}'

    if current_line:
        if not current_line.endswith('"'):
            current_line += '"'
        lines.append(_pad(current_line))

    lines.append(_pad(""))
    lines.append(_pad(f"                    - {author}"))
    lines.append(_pad(""))
    lines.append(_pad("-" * PAGE_WIDTH))
    lines.append(_pad(""))
    lines.append(_pad("Source: Curated public-domain quotes"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 501 with quote of the day."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "501.json"
    
    content = build_quote_page()
    
    page = {
        "page": "501",
        "title": "Quote of the Day",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with quote of the day")


if __name__ == "__main__":
    main()

