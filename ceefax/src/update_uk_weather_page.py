"""
Update page 101 with UK weather for major cities.
Also updates page 101_2 with additional cities.
Uses same format as page 101.
"""
from pathlib import Path
from typing import Dict, List, Tuple

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, resolve_provider, FRESH_OPEN_METEO_SECONDS
from .weather_map import (
    WeatherSummary,
    fetch_open_meteo,
    fetch_open_meteo_many,
    weather_summary_from_dict,
    weather_summary_to_dict,
)


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)

def _center_pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.center(PAGE_WIDTH)

def _wrap_center(text: str, width: int = PAGE_WIDTH) -> List[str]:
    """Word-wrap and center each line within width."""
    words = text.split()
    if not words:
        return [_center_pad("")]
    lines: List[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
            continue
        if len(cur) + 1 + len(w) <= width:
            cur = f"{cur} {w}"
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return [(_center_pad(l) if len(l) <= width else _pad(l)) for l in lines]


def _ascii_icon(desc: str) -> List[str]:
    """
    Return 3-line ASCII weather icon matching wttr.in format.
    These are the actual icons used by wttr.in for weather display.
    """
    desc_lower = desc.lower()
    
    # Partly cloudy must be checked BEFORE generic cloud/overcast
    if "partly" in desc_lower and "cloud" in desc_lower:
        return [
            "   \\  /      ",
            " _ /\"\".-.    ",
            "   \\_(   ).  ",
            "    /(___(__) "
        ]
    
    # Clear/Sunny
    if "sun" in desc_lower or "clear" in desc_lower:
        return [
            "    \\   /    ",
            "     .-.     ",
            "  -- (   ) -- ",
            "     `-’     ",
        ]
    
    # Rain/Shower
    if "rain" in desc_lower or "shower" in desc_lower or "drizzle" in desc_lower:
        return [
            "     .-.     ",
            "    (   ).   ",
            "   (___(__)  ",
            "    ‘ ‘ ‘ ‘  ",
        ]
    
    # Cloudy/Overcast
    if "cloud" in desc_lower or "overcast" in desc_lower:
        return [
            "     .--.    ",
            "  .-(    ).  ",
            " (___.__)__) ",
            "             ",
        ]
    
    # Snow
    if "snow" in desc_lower or "sleet" in desc_lower:
        return [
            "     .-.     ",
            "    (   )    ",
            "   (___(__)  ",
            "    * * * *  ",
        ]
    
    # Fog/Mist
    if "fog" in desc_lower or "mist" in desc_lower or "haze" in desc_lower:
        return [
            " _ - _ - _ - ",
            "  _ - _ - _  ",
            " _ - _ - _ - ",
            "             ",
        ]
    
    # Default (cloudy)
    return [
        "     .--.    ",
        "  .-(    ).  ",
        " (___.__)__) ",
        "             ",
    ]


UK_CITIES_MAIN = [
    ("London", "London,UK"),
    ("Birmingham", "Birmingham,UK"),
    ("Manchester", "Manchester,UK"),
]

UK_CITIES_SUB = [
    ("Edinburgh", "Edinburgh,UK"),
    ("Belfast", "Belfast,UK"),
    ("Newcastle", "Newcastle upon Tyne,UK"),
]


def build_single_location_weather_page(
    name: str,
    query: str,
    *,
    summary: WeatherSummary | None = None,
    source_label: str = "Open-Meteo",
    stale: bool = False,
) -> List[str]:
    """Build a single location weather page with detailed forecast."""
    lines: List[str] = []
    
    try:
        if summary is None:
            summary = fetch_open_meteo(query)
        icon_lines = _ascii_icon(summary.description)

        # Centered title
        lines.append(_center_pad(""))
        lines.append(_center_pad(f"{name.upper()} WEATHER"))
        lines.append(_center_pad(""))

        # Centered current conditions block (more "graphic" + consistent)
        lines.append(_center_pad(f"Temp {summary.temp_c}C (feels {summary.feels_like_c}C)"))
        lines.append(_center_pad(""))

        # Center the icon (no box)
        for icon_line in icon_lines:
            lines.append(_center_pad(icon_line))

        # Description + wind centered
        lines.append(_center_pad(""))
        lines.append(_center_pad(summary.description.upper()[:PAGE_WIDTH]))
        lines.append(_center_pad(f"Wind {summary.wind_kph} km/h {summary.wind_dir}".upper()[:PAGE_WIDTH]))
        lines.append(_center_pad(""))
        
        # Detailed forecast
        # Today
        today_text = f"Today: {summary.today_desc or summary.description}"
        if summary.today_max != "?" and summary.today_min != "?":
            today_text += f" Max {summary.today_max}C, Min {summary.today_min}C."
        else:
            today_text += f" Temp {summary.temp_c}C."
        lines.extend(_wrap_center(today_text))
        
        # Tonight
        if summary.tonight_desc:
            tonight_text = f"Tonight: {summary.tonight_desc}"
            if summary.tonight_min != "?":
                tonight_text += f" Min around {summary.tonight_min}C."
            lines.extend(_wrap_center(tonight_text))
        else:
            tonight_text = f"Tonight: Mostly {summary.description.lower()}"
            if summary.today_min != "?":
                tonight_text += f" Min around {summary.today_min}C."
            lines.extend(_wrap_center(tonight_text))
        
        # Tomorrow
        if summary.tomorrow_desc:
            tomorrow_text = f"Tomorrow: {summary.tomorrow_desc}"
            lines.extend(_wrap_center(tomorrow_text))
        else:
            lines.append(_center_pad("Tomorrow: Forecast unavailable"))
        
    except Exception as e:  # noqa: BLE001
        lines.append(_center_pad(""))
        lines.append(_center_pad(name.upper() + " WEATHER"))
        lines.append(_center_pad(""))
        error_msg = str(e)[:PAGE_WIDTH-25]
        lines.append(_center_pad(f"Error fetching data: {error_msg}"))
        lines.append(_center_pad(f"Query used: {query[:PAGE_WIDTH-12]}"))
        # Print error to console for debugging
        print(f"  Warning: Failed to fetch weather for {name} using query '{query}': {e}")

    lines.append(_center_pad(""))
    lines.append(_center_pad(f"Source: {source_label}{' (STALE)' if stale else ''}"))

    return lines[:PAGE_HEIGHT]


def main() -> None:
    """
    Update page 101 and subpages with UK weather - one location per page.
    Always starts with London as the first page.
    """
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"

    # Create one page per city - always start with London
    all_cities = UK_CITIES_MAIN + UK_CITIES_SUB

    queries = [q for _n, q in all_cities]
    result: ProviderResult[dict] = resolve_provider(
        "weather-101-six-cities",
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
    prefetched: Dict[str, WeatherSummary] = {
        query: weather_summary_from_dict(data)
        for query, data in result.data.items()
    }

    for idx, (name, query) in enumerate(all_cities, start=1):
        summary = prefetched[query]
        page_lines = build_single_location_weather_page(
            name,
            query,
            summary=summary,
            source_label=result.source,
            stale=result.stale,
        )
        page_file = pages_dir / f"101{'_' + str(idx) if idx > 1 else ''}.json"
        page_data = {
            "page": "101",
            "title": f"{name} Weather",
            "timestamp": f"{result.source} - {result.status_label}",
            "subpage": idx,
            "content": page_lines,
        }
        atomic_write_json(page_file, page_data)
        print(f"Updated {page_file} with {name} weather")
