"""Update page 402 from the structured Lottery Results Feed API."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from .compiler import PAGE_HEIGHT, PAGE_WIDTH
from .providers import ProviderResult, atomic_write_json, require_env, resolve_provider


LOTTERY_RESULTS_API = "https://www.lotteryresultsfeed.com/api/lottery/results"
LOTTERY_RESULTS_API_KEY_ENV = "LOTTERY_RESULTS_API_KEY"
LOTTERY_SOURCE = "Lottery Results Feed"
LOTTERY_CACHE_KEY = "lottery-402"
# Two API calls per refresh. A 24-hour window stays within the free 100-call
# monthly allowance (about 60 calls/month); delayed results are acceptable.
CACHE_FRESH_SECONDS = 24 * 60 * 60


def _pad(text: str) -> str:
    return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)


def _integers(value: Any, *, field: str) -> list[int]:
    """Normalize an API integer, list, or delimited string to integers."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is missing or invalid")
    if isinstance(value, (str, int, float)):
        values: Iterable[Any]
        if isinstance(value, str) and ("," in value or " " in value):
            values = value.replace(",", " ").split()
        else:
            values = [value]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise ValueError(f"{field} is not an integer or list")

    normalized: list[int] = []
    for item in values:
        if isinstance(item, bool):
            raise ValueError(f"{field} contains a boolean")
        if isinstance(item, float) and not item.is_integer():
            raise ValueError(f"{field} contains a non-integer")
        try:
            normalized.append(int(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} contains a non-integer") from exc
    if not normalized:
        raise ValueError(f"{field} is empty")
    return normalized


def _latest_result(payload: Any, *, game: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{game} response is not a JSON object")
    results = payload.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValueError(f"{game} response has no latest result")
    return results[0]


def _normalize_lotto(payload: Any) -> dict[str, Any]:
    draw = _latest_result(payload, game="UK Lotto")
    numbers = _integers(draw.get("balls"), field="UK Lotto balls")
    bonus = _integers(draw.get("ball_bonus"), field="UK Lotto bonus")
    draw_date = str(draw.get("draw_date") or "").strip()
    if len(numbers) != 6 or len(set(numbers)) != 6 or not all(1 <= n <= 59 for n in numbers):
        raise ValueError("UK Lotto response has invalid main balls")
    if not 1 <= bonus[0] <= 59:
        raise ValueError("UK Lotto response has an invalid bonus ball")
    if not draw_date:
        raise ValueError("UK Lotto response omitted draw_date")
    return {"draw_date": draw_date, "numbers": numbers, "bonus_ball": bonus[0]}


def _normalize_euromillions(payload: Any) -> dict[str, Any]:
    draw = _latest_result(payload, game="EuroMillions")
    numbers = _integers(draw.get("balls"), field="EuroMillions balls")
    stars = _integers(draw.get("ball_bonus"), field="EuroMillions bonus")
    draw_date = str(draw.get("draw_date") or "").strip()
    if len(numbers) != 5 or len(set(numbers)) != 5 or not all(1 <= n <= 50 for n in numbers):
        raise ValueError("EuroMillions response has invalid main balls")
    if len(stars) != 2 or len(set(stars)) != 2 or not all(1 <= n <= 12 for n in stars):
        raise ValueError("EuroMillions response has invalid lucky stars")
    if not draw_date:
        raise ValueError("EuroMillions response omitted draw_date")
    return {"draw_date": draw_date, "numbers": numbers, "lucky_stars": stars}


def _fetch_game(*, params: dict[str, Any]) -> Any:
    api_key = require_env(LOTTERY_RESULTS_API_KEY_ENV)
    response = requests.get(
        LOTTERY_RESULTS_API,
        headers={"Authorization": f"Bearer {api_key}"},
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def fetch_lottery_results() -> dict[str, dict[str, Any]]:
    """Fetch and normalize the latest Lotto and EuroMillions draws."""
    # Lottery Results Feed uses slug "lotto" (not "uk-lotto"). id 722 is
    # Ireland EuroMillions; UK EuroMillions is slug "euromillions" + country uk.
    lotto = _fetch_game(params={"slug": "lotto", "country": "uk", "limit": 1})
    euro = _fetch_game(params={"slug": "euromillions", "country": "uk", "limit": 1})
    return {
        "national": _normalize_lotto(lotto),
        "euromillions": _normalize_euromillions(euro),
    }


def get_lottery_results() -> ProviderResult[dict[str, dict[str, Any]]]:
    """Return fresh-enough cached data, live data, or an indefinite stale fallback."""
    return resolve_provider(
        LOTTERY_CACHE_KEY,
        [(LOTTERY_SOURCE, fetch_lottery_results)],
        fresh_for_seconds=CACHE_FRESH_SECONDS,
    )


def _numbers(values: list[int]) -> str:
    return "  ".join(f"{value:02d}" for value in values)


def build_lottery_page(
    result: ProviderResult[dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    """Build the page 402 Lotto and EuroMillions layout."""
    result = result or get_lottery_results()
    lotto = result.data["national"]
    euro = result.data["euromillions"]
    state = "STALE" if result.stale else "CURRENT"
    as_of = "Stale/as-of" if result.stale else "As-of"

    lines = [
        _pad("LOTTERY RESULTS"),
        _pad("-" * PAGE_WIDTH),
        _pad("LOTTO"),
        _pad(f"Draw: {lotto['draw_date']}"),
        _pad(f"Main:  {_numbers(lotto['numbers'])}"),
        _pad(f"Bonus: {lotto['bonus_ball']:02d}"),
        _pad(""),
        _pad("EUROMILLIONS"),
        _pad(f"Draw: {euro['draw_date']}"),
        _pad(f"Main:  {_numbers(euro['numbers'])}"),
        _pad(f"Stars: {_numbers(euro['lucky_stars'])}"),
        _pad(""),
        _pad(f"Source: {result.source} [{state}]"),
        _pad(f"{as_of}: {result.fetched_at}"),
        _pad("Verify prizes with the official operator."),
    ]
    return lines[:PAGE_HEIGHT]


def main() -> None:
    """Atomically update page 402 only after data resolution succeeds."""
    root = Path(__file__).resolve().parent.parent
    page_file = root / "pages" / "402.json"
    result = get_lottery_results()
    page = {
        "page": "402",
        "title": "Lottery Results",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "subpage": 1,
        "content": build_lottery_page(result),
    }
    atomic_write_json(page_file, page)
    cache_note = "stale cache" if result.stale else "current data"
    print(f"Updated {page_file} with {cache_note} from {result.source}")


if __name__ == "__main__":
    main()
