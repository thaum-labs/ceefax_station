from pathlib import Path

from .providers import ProviderResult, atomic_write_json, resolve_provider, FRESH_OPEN_METEO_SECONDS
from .uk_weather_map import REGIONS, build_uk_weather_map
from .weather_map import (
    WeatherSummary,
    fetch_open_meteo_many,
    weather_summary_from_dict,
    weather_summary_to_dict,
)


def main() -> None:
    """
    Generate a UK weather map and write it to pages/103.json.
    """
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "103.json"

    queries = [query for query, _row, _column in REGIONS.values()]
    result: ProviderResult[dict] = resolve_provider(
        "weather-103-map",
        [
            (
                "Open-Meteo",
                lambda: {
                    query: weather_summary_to_dict(summary)
                    for query, summary in fetch_open_meteo_many(queries, max_workers=6).items()
                },
            )
        ],
        is_valid=lambda data: isinstance(data, dict) and all(query in data for query in queries),
        fresh_for_seconds=FRESH_OPEN_METEO_SECONDS,
    )
    by_query: dict[str, WeatherSummary] = {
        query: weather_summary_from_dict(data)
        for query, data in result.data.items()
    }
    summaries = {
        name: by_query[query]
        for name, (query, _row, _column) in REGIONS.items()
    }
    lines = build_uk_weather_map(
        summaries,
        source_label=result.source,
        stale=result.stale,
    )

    page = {
        "page": "103",
        "title": "Weather Map",
        "timestamp": f"{result.source} - {result.status_label}",
        "subpage": 1,
        "content": lines,
    }

    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with UK weather map")


if __name__ == "__main__":
    main()


