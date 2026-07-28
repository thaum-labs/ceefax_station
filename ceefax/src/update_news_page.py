import os
from pathlib import Path
from typing import List

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .news_providers import fetch_bbc_rss_headlines, fetch_guardian_headlines
from .providers import ProviderResult, atomic_write_json, resolve_provider


BBC_SOMERSET_RSS = "https://feeds.bbci.co.uk/news/england/somerset/rss.xml"


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def fetch_headlines(limit: int = 6) -> List[str]:
    """Fetch top headlines from BBC Somerset RSS (compatibility helper)."""
    return fetch_bbc_rss_headlines(BBC_SOMERSET_RSS, limit=limit)


def resolve_headlines(limit: int = 6) -> ProviderResult[List[str]]:
    providers = []
    if (os.environ.get("GUARDIAN_API_KEY") or "").strip():
        providers.append(
            (
                "Guardian Open Platform",
                lambda: fetch_guardian_headlines(
                    section="uk-news",
                    query="Somerset",
                    limit=limit,
                ),
            )
        )
    providers.append(("BBC Somerset RSS", lambda: fetch_headlines(limit)))
    return resolve_provider("news-200-somerset", providers)


def build_news_page(result: ProviderResult[List[str]] | None = None) -> List[str]:
    lines: List[str] = []
    lines.append(_pad("NEWS HEADLINES"))
    result = result or resolve_headlines()
    headlines = result.data

    # Simple horizontal separator line spanning the full page width
    sep = _pad("-" * PAGE_WIDTH)
    # Keep pages uniform: show the "blue line" directly under the top heading.
    lines.append(sep)
    lines.append(_pad(f"{result.source}{' - STALE' if result.stale else ''}"))

    for title in headlines:
        wrapped = []
        text = title
        while text:
            wrapped.append(_pad(text[: PAGE_WIDTH]))
            text = text[PAGE_WIDTH:]
        lines.extend(wrapped)
        # Separator between stories
        lines.append(sep)

    lines.append(_pad(f"As of: {result.fetched_at}"))

    return lines[:PAGE_HEIGHT]


def main() -> None:
    """
    Update page 200 with latest local news headlines.
    """
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "200.json"

    result = resolve_headlines()
    content = build_news_page(result)

    page = {
        "page": "200",
        "title": "News Headlines",
        "timestamp": f"{result.source} - {result.status_label}",
        "subpage": 1,
        "content": content,
    }

    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with latest news headlines")


if __name__ == "__main__":
    main()


