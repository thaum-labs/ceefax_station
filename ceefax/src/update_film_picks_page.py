"""Update page 504 with structured TMDB film data."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import ProviderResult, atomic_write_json, require_env, resolve_provider


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


TMDB_API = "https://api.themoviedb.org/3/movie"
TMDB_SOURCE = "TMDB"


def _tmdb_list(endpoint: str, api_key: str, *, region: bool) -> List[Dict]:
    params = {"api_key": api_key, "language": "en-GB"}
    if region:
        params["region"] = "GB"
    response = requests.get(f"{TMDB_API}/{endpoint}", params=params, timeout=15)
    response.raise_for_status()
    payload = response.json()
    films = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(films, list) or not films:
        raise ValueError(f"TMDB {endpoint} returned no films")
    return [
        {
            "title": str(film.get("title") or film.get("original_title") or "Unknown"),
            "vote_average": float(film.get("vote_average") or 0),
            "release_date": str(film.get("release_date") or ""),
        }
        for film in films
        if isinstance(film, dict)
    ]


def fetch_tmdb_films() -> Dict[str, List[Dict]]:
    api_key = require_env("TMDB_API_KEY")
    return {
        "now_playing": _tmdb_list("now_playing", api_key, region=True),
        "popular": _tmdb_list("popular", api_key, region=False),
        "upcoming": _tmdb_list("upcoming", api_key, region=True),
    }


def get_film_data() -> ProviderResult[Dict[str, List[Dict]]]:
    return resolve_provider("films-504", [(TMDB_SOURCE, fetch_tmdb_films)])


def format_rating(vote_average: float) -> str:
    """Convert rating (0-10) to star display (★★★★☆)."""
    stars = int(vote_average / 2)  # Convert 0-10 to 0-5 stars
    full_stars = min(stars, 5)
    return "★" * full_stars + "☆" * (5 - full_stars)


def build_film_picks_page(result: ProviderResult[Dict[str, List[Dict]]] | None = None) -> List[str]:
    """Build film picks page."""
    result = result or get_film_data()
    film_data = result.data
    lines: List[str] = []
    lines.append(_pad("FILM PICKS"))
    lines.append(_pad(""))
    
    # Now showing in cinemas
    lines.append(_pad("NOW SHOWING"))
    sep = _pad("-" * PAGE_WIDTH)
    lines.append(sep)
    
    now_playing = film_data["now_playing"][:3]
    
    if now_playing:
        cinema_num = 1
        for film in now_playing:
            title = film.get("title", "Unknown")[:35]
            lines.append(_pad(f"Cinema {cinema_num}:  {title}"))
            cinema_num += 1
    else:
        lines.append(_pad("No current releases supplied"))
    
    lines.append(_pad(""))
    
    # This week's picks (popular films)
    lines.append(_pad("THIS WEEK'S PICKS"))
    lines.append(sep)
    
    popular = film_data["popular"][:3]
    
    if popular:
        for film in popular:
            title = film.get("title", "Unknown")[:30]
            rating = film.get("vote_average", 0)
            stars = format_rating(rating)
            lines.append(_pad(f"{stars}  {title}"))
    else:
        lines.append(_pad("No popular films supplied"))
    
    lines.append(_pad(""))
    
    # Coming soon
    lines.append(_pad("COMING SOON"))
    lines.append(sep)
    
    upcoming = film_data["upcoming"][:2]
    
    if upcoming:
        for film in upcoming:
            title = film.get("title", "Unknown")[:35]
            release_date = film.get("release_date", "")
            if release_date:
                try:
                    release_dt = datetime.strptime(release_date, "%Y-%m-%d")
                    day_name = release_dt.strftime("%a")
                    lines.append(_pad(f"Next {day_name}:  {title}"))
                except (ValueError, AttributeError):
                    lines.append(_pad(f"Coming soon:  {title}"))
            else:
                lines.append(_pad(f"Coming soon:  {title}"))
    else:
        lines.append(_pad("No upcoming films supplied"))
    
    lines.append(_pad(""))
    lines.append(_pad("RATINGS"))
    lines.append(sep)
    state = "Stale/as-of" if result.stale else "As-of"
    lines.append(_pad(f"Source: TMDB | {state} {result.fetched_at}"))
    
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Update page 504 with film picks."""
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "504.json"
    
    result = get_film_data()
    content = build_film_picks_page(result)
    
    page = {
        "page": "504",
        "title": "Film Picks",
        "timestamp": datetime.now().isoformat() + "Z",
        "subpage": 1,
        "content": content,
    }
    
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with film picks from {result.source}")


if __name__ == "__main__":
    main()

