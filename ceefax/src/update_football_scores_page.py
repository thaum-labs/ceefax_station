"""Update page 301 from structured Premier League match data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List

from .compiler import PAGE_HEIGHT, PAGE_WIDTH
from .paths import pages_dir
from .providers import ProviderResult, atomic_write_json, fetch_football_data, resolve_provider, FRESH_FOOTBALL_SECONDS


SCORED_STATUSES = {"FINISHED", "IN_PLAY", "PAUSED"}


def _pad(text: str) -> str:
    return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)


def _page(lines: List[str]) -> List[str]:
    lines = lines[:PAGE_HEIGHT]
    return [_pad(line) for line in lines] + [_pad("")] * (PAGE_HEIGHT - len(lines))


def _normalize_matches(payload: dict[str, Any]) -> List[dict[str, Any]]:
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise ValueError("matches response has no matches list")
    normalized: List[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        home = match.get("homeTeam")
        away = match.get("awayTeam")
        full_time = (match.get("score") or {}).get("fullTime") or {}
        if not isinstance(home, dict) or not isinstance(away, dict):
            continue
        normalized.append(
            {
                "utc_date": str(match.get("utcDate") or ""),
                "status": str(match.get("status") or ""),
                "home": str(home.get("shortName") or home.get("name") or ""),
                "away": str(away.get("shortName") or away.get("name") or ""),
                "home_score": full_time.get("home"),
                "away_score": full_time.get("away"),
            }
        )
    return normalized


def fetch_premier_league_scores(now: datetime | None = None) -> List[dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    payload = fetch_football_data(
        "competitions/PL/matches",
        params={
            "dateFrom": (current - timedelta(days=3)).date().isoformat(),
            "dateTo": current.date().isoformat(),
        },
    )
    return [
        match
        for match in _normalize_matches(payload)
        if match["status"] in SCORED_STATUSES
    ]


def _scores() -> ProviderResult[List[dict[str, Any]]]:
    return resolve_provider(
        "football-scores-pl",
        [("football-data.org", fetch_premier_league_scores)],
        is_valid=lambda data: isinstance(data, list),
        fresh_for_seconds=FRESH_FOOTBALL_SECONDS,
    )


def _match_line(match: dict[str, Any]) -> str:
    date = match["utc_date"][5:10].replace("-", "/")
    home_score = match.get("home_score")
    away_score = match.get("away_score")
    if home_score is None or away_score is None:
        score = match["status"].replace("_", " ")[:7]
    else:
        score = f"{home_score}-{away_score}"
    return (
        f"{date:>5} {match['home'][:17]:>17} "
        f"{score:^7} {match['away'][:17]:<17}"
    )


def build_football_scores_page() -> List[str]:
    result = _scores()
    matches = sorted(result.data, key=lambda match: match["utc_date"], reverse=True)
    lines = [
        "FOOTBALL LIVE SCORES",
        "-" * PAGE_WIDTH,
        "PREMIER LEAGUE - LIVE & RECENT",
        "-" * PAGE_WIDTH,
    ]
    if matches:
        lines.extend(_match_line(match) for match in matches[:17])
    else:
        lines.append("No live or recent matches in the UTC window")
    lines = lines[:21]
    lines.append("")
    state = "STALE" if result.stale else "CURRENT"
    stamp = result.fetched_at[5:16].replace("T", " ")
    lines.append(f"Src {result.source[:17]} As-of {stamp}Z {state}")
    return _page(lines)


def main() -> None:
    page_file = pages_dir() / "301.json"
    content = build_football_scores_page()
    atomic_write_json(
        page_file,
        {
            "page": "301",
            "title": "Football Live Scores",
            "timestamp": "football-data.org",
            "subpage": 1,
            "content": content,
        },
    )
    print(f"Updated {page_file} with latest football scores")


if __name__ == "__main__":
    main()
