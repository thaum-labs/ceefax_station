"""Update page 304 from structured Premier League fixtures and results."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from .compiler import PAGE_HEIGHT, PAGE_WIDTH
from .providers import ProviderResult, atomic_write_json, fetch_football_data, resolve_provider, FRESH_FOOTBALL_SECONDS


RESULT_STATUSES = {"FINISHED", "IN_PLAY", "PAUSED"}
FIXTURE_STATUSES = {"SCHEDULED", "TIMED"}


def _pad(text: str) -> str:
    return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)


def _page(lines: List[str]) -> List[str]:
    lines = lines[:PAGE_HEIGHT]
    return [_pad(line) for line in lines] + [_pad("")] * (PAGE_HEIGHT - len(lines))


def _normalize_match(match: dict[str, Any]) -> dict[str, Any] | None:
    home = match.get("homeTeam")
    away = match.get("awayTeam")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    full_time = (match.get("score") or {}).get("fullTime") or {}
    return {
        "utc_date": str(match.get("utcDate") or ""),
        "status": str(match.get("status") or ""),
        "home": str(home.get("shortName") or home.get("name") or ""),
        "away": str(away.get("shortName") or away.get("name") or ""),
        "home_score": full_time.get("home"),
        "away_score": full_time.get("away"),
    }


def fetch_premier_league_data(now: datetime | None = None) -> Dict[str, List[dict[str, Any]]]:
    """Fetch a UTC window containing recent results and upcoming fixtures."""
    current = now or datetime.now(timezone.utc)
    payload = fetch_football_data(
        "competitions/PL/matches",
        params={
            "dateFrom": (current - timedelta(days=2)).date().isoformat(),
            # football-data.org accepts bounded date ranges; this gives a
            # nine-day span with recent context and one week ahead.
            "dateTo": (current + timedelta(days=7)).date().isoformat(),
        },
    )
    raw_matches = payload.get("matches")
    if not isinstance(raw_matches, list):
        raise ValueError("matches response has no matches list")
    matches = [
        normalized
        for match in raw_matches
        if isinstance(match, dict)
        if (normalized := _normalize_match(match)) is not None
    ]
    return {
        "scores": [match for match in matches if match["status"] in RESULT_STATUSES],
        "fixtures": [match for match in matches if match["status"] in FIXTURE_STATUSES],
    }


def _fixtures() -> ProviderResult[Dict[str, List[dict[str, Any]]]]:
    return resolve_provider(
        "football-fixtures-results-pl",
        [("football-data.org", fetch_premier_league_data)],
        is_valid=lambda data: (
            isinstance(data, dict)
            and isinstance(data.get("scores"), list)
            and isinstance(data.get("fixtures"), list)
        ),
        fresh_for_seconds=FRESH_FOOTBALL_SECONDS,
    )


def _result_line(match: dict[str, Any]) -> str:
    day = match["utc_date"][5:10].replace("-", "/")
    home_score = match.get("home_score")
    away_score = match.get("away_score")
    score = (
        f"{home_score}-{away_score}"
        if home_score is not None and away_score is not None
        else match["status"][:5]
    )
    return f"{day:>5} {match['home'][:17]:>17} {score:^5} {match['away'][:17]:<17}"


def _fixture_line(match: dict[str, Any]) -> str:
    stamp = match["utc_date"]
    when = f"{stamp[5:10].replace('-', '/')} {stamp[11:16]}"
    return f"{when:>11} {match['home'][:15]:>15} v {match['away'][:15]:<15}"


def build_fixtures_page() -> List[str]:
    result = _fixtures()
    scores = sorted(result.data["scores"], key=lambda match: match["utc_date"], reverse=True)
    fixtures = sorted(result.data["fixtures"], key=lambda match: match["utc_date"])
    lines = [
        "PREMIER LEAGUE",
        "FIXTURES & RESULTS",
        "RECENT RESULTS",
        "-" * PAGE_WIDTH,
    ]
    lines.extend(_result_line(match) for match in scores[:5])
    if not scores:
        lines.append("No recent results in the UTC window")
    lines.extend(["UPCOMING FIXTURES (UTC)", "-" * PAGE_WIDTH])
    lines.extend(_fixture_line(match) for match in fixtures[:7])
    if not fixtures:
        lines.append("No fixtures scheduled in the UTC window")
    lines = lines[:21]
    lines.append("")
    state = "STALE" if result.stale else "CURRENT"
    stamp = result.fetched_at[5:16].replace("T", " ")
    lines.append(f"Src {result.source[:17]} As-of {stamp}Z {state}")
    return _page(lines)


def main() -> None:
    page_file = Path(__file__).resolve().parent.parent / "pages" / "304.json"
    content = build_fixtures_page()
    atomic_write_json(
        page_file,
        {
            "page": "304",
            "title": "Fixtures & Results",
            "timestamp": "football-data.org",
            "subpage": 1,
            "content": content,
        },
    )
    print(f"Updated {page_file} with fixtures and results")


if __name__ == "__main__":
    main()
