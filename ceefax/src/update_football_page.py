"""Update football headlines (300) and league tables (302/303)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, List

import requests

from .compiler import PAGE_HEIGHT, PAGE_WIDTH
from .paths import pages_dir
from .providers import ProviderResult, atomic_write_json, fetch_football_data, resolve_provider, FRESH_FOOTBALL_SECONDS


BBC_FOOTBALL_RSS = "https://feeds.bbci.co.uk/sport/football/rss.xml"
FOOTBALL_DATA_SOURCE = "football-data.org"


def _pad(text: str) -> str:
    return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)


def _page(lines: List[str]) -> List[str]:
    return [_pad(line) for line in lines[:PAGE_HEIGHT]] + [_pad("")] * max(
        0, PAGE_HEIGHT - len(lines)
    )


def _as_of(result: ProviderResult[Any]) -> str:
    state = "STALE" if result.stale else "CURRENT"
    stamp = result.fetched_at[5:16].replace("T", " ")
    return f"Src {result.source[:17]} As-of {stamp}Z {state}"


def fetch_results(limit: int = 6) -> List[str]:
    """Fetch durable BBC football RSS headlines."""
    response = requests.get(BBC_FOOTBALL_RSS, timeout=10)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    return [
        item.text.strip()
        for item in root.findall("./channel/item/title")
        if item.text and item.text.strip()
    ][:limit]


def _headlines() -> ProviderResult[List[str]]:
    return resolve_provider(
        "football-headlines-300",
        [("BBC Sport RSS", lambda: fetch_results(limit=6))],
    )


def _normalize_standings(payload: dict[str, Any], limit: int = 20) -> List[List[str]]:
    standings = payload.get("standings")
    if not isinstance(standings, list):
        raise ValueError("standings response has no standings list")
    total = next(
        (
            entry.get("table")
            for entry in standings
            if isinstance(entry, dict) and entry.get("type") == "TOTAL"
        ),
        None,
    )
    if not isinstance(total, list):
        raise ValueError("standings response has no TOTAL table")

    rows: List[List[str]] = []
    for entry in total[:limit]:
        if not isinstance(entry, dict) or not isinstance(entry.get("team"), dict):
            continue
        team = entry["team"].get("shortName") or entry["team"].get("name")
        if not team:
            continue
        rows.append(
            [
                str(entry.get("position", "")),
                str(team),
                str(entry.get("playedGames", "")),
                str(entry.get("won", "")),
                str(entry.get("draw", "")),
                str(entry.get("lost", "")),
                str(entry.get("goalsFor", "")),
                str(entry.get("goalsAgainst", "")),
                str(entry.get("goalDifference", "")),
                str(entry.get("points", "")),
            ]
        )
    if not rows:
        raise ValueError("standings response contained no usable rows")
    return rows


def _has_played_games(rows: List[List[str]]) -> bool:
    """True when at least one side has contested a match."""
    for row in rows:
        try:
            if int(row[2] or "0") > 0:
                return True
        except (TypeError, ValueError, IndexError):
            continue
    return False


def _season_start_year(payload: dict[str, Any]) -> int | None:
    season = payload.get("season")
    if isinstance(season, dict):
        start = str(season.get("startDate") or "")
        if len(start) >= 4 and start[:4].isdigit():
            return int(start[:4])
    filters = payload.get("filters")
    if isinstance(filters, dict):
        value = filters.get("season")
        if value is not None and str(value).isdigit():
            return int(value)
    return None


def fetch_league_rows(code: str, limit: int = 20) -> List[List[str]]:
    """Fetch and normalize a football-data.org competition table.

    Between seasons the API often returns the new roster with every side on
    0 played / 0 points. Prefer the previous completed season when that
    happens so Ceefax pages keep a real league table.
    """
    payload = fetch_football_data(f"competitions/{code}/standings")
    rows = _normalize_standings(payload, limit=limit)
    if _has_played_games(rows):
        return rows

    season_year = _season_start_year(payload)
    if season_year is None:
        return rows

    prev_payload = fetch_football_data(
        f"competitions/{code}/standings",
        params={"season": str(season_year - 1)},
    )
    prev_rows = _normalize_standings(prev_payload, limit=limit)
    if _has_played_games(prev_rows):
        return prev_rows
    return rows


def _league_table(code: str) -> ProviderResult[List[List[str]]]:
    return resolve_provider(
        f"football-standings-{code.lower()}",
        [(FOOTBALL_DATA_SOURCE, lambda: fetch_league_rows(code, limit=20))],
        fresh_for_seconds=FRESH_FOOTBALL_SECONDS,
    )


def build_football_page() -> List[str]:
    result = _headlines()
    lines = ["SPORTS HEADLINES", "-" * PAGE_WIDTH]
    for title in result.data:
        while title:
            lines.append(title[:PAGE_WIDTH])
            title = title[PAGE_WIDTH:]
        lines.append("-" * PAGE_WIDTH)
    lines = lines[:22]
    lines.append(_as_of(result))
    return _page(lines)


def _build_table_page(title: str, code: str) -> List[str]:
    result = _league_table(code)
    if not _has_played_games(result.data):
        lines = [
            title,
            "-" * PAGE_WIDTH,
            "Season not started yet.",
            "Table will appear after matchday 1.",
            "",
            _as_of(result),
        ]
        return _page(lines)

    lines = [
        title,
        f"{'Pos':>2} {'Team':<25} {'P':>2} {'W':>2} {'D':>2} {'L':>2} {'GD':>3} {'Pts':>3}",
    ]
    for pos, team, played, won, drawn, lost, _gf, _ga, gd, points in result.data:
        lines.append(
            f"{pos:>2} {team[:25]:<25} {played:>2} {won:>2} "
            f"{drawn:>2} {lost:>2} {gd:>3} {points:>3}"
        )
    lines.append(_as_of(result))
    return _page(lines)


def build_premier_league_table_page() -> List[str]:
    return _build_table_page("PREMIER LEAGUE TABLE", "PL")


def build_championship_table_page() -> List[str]:
    return _build_table_page("CHAMPIONSHIP TABLE", "ELC")


def main() -> None:
    """Build all content before atomically replacing any page."""
    target = pages_dir()
    pages = [
        (
            target / "300.json",
            {
                "page": "300",
                "title": "Sports Headlines",
                "timestamp": "BBC Sport RSS",
                "subpage": 1,
                "content": build_football_page(),
            },
        ),
        (
            target / "302.json",
            {
                "page": "302",
                "title": "Premier League Table",
                "timestamp": "football-data.org",
                "subpage": 1,
                "content": build_premier_league_table_page(),
            },
        ),
        (
            target / "303.json",
            {
                "page": "303",
                "title": "Championship Table",
                "timestamp": "football-data.org",
                "subpage": 1,
                "content": build_championship_table_page(),
            },
        ),
    ]
    for path, payload in pages:
        atomic_write_json(path, payload)
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
