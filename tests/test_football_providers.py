from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from ceefax.src import providers
from ceefax.src.providers import ProviderUnavailable


class FakeResponse:
    def __init__(self, payload: dict[str, Any], content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _match(
    utc_date: str,
    status: str,
    home: str,
    away: str,
    home_score: int | None = None,
    away_score: int | None = None,
) -> dict[str, Any]:
    return {
        "utcDate": utc_date,
        "status": status,
        "homeTeam": {"shortName": home},
        "awayTeam": {"shortName": away},
        "score": {"fullTime": {"home": home_score, "away": away_score}},
    }


def test_standings_use_codes_auth_header_and_normalize(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from ceefax.src import update_football_page as football

    calls: list[dict[str, Any]] = []
    payload = {
        "standings": [
            {
                "type": "TOTAL",
                "table": [
                    {
                        "position": 1,
                        "team": {"shortName": "Arsenal"},
                        "playedGames": 3,
                        "won": 2,
                        "draw": 1,
                        "lost": 0,
                        "goalsFor": 7,
                        "goalsAgainst": 2,
                        "goalDifference": 5,
                        "points": 7,
                    }
                ],
            }
        ]
    }

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(payload)

    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(providers.requests, "get", fake_get)

    assert football.fetch_league_rows("PL")[0] == [
        "1",
        "Arsenal",
        "3",
        "2",
        "1",
        "0",
        "7",
        "2",
        "5",
        "7",
    ]
    assert calls[0]["url"].endswith("/v4/competitions/PL/standings")
    assert calls[0]["headers"] == {"X-Auth-Token": "test-token"}
    championship = football.build_championship_table_page()
    assert calls[1]["url"].endswith("/v4/competitions/ELC/standings")
    assert len(championship) == 23
    assert all(len(line) == 50 for line in championship)
    assert any("football-data.org" in line and "CURRENT" in line for line in championship)


def test_scores_and_fixtures_use_expected_utc_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from ceefax.src import update_fixtures_page as fixtures
    from ceefax.src import update_football_scores_page as scores

    calls: list[dict[str, Any]] = []
    payload = {
        "matches": [
            _match("2026-07-27T19:00:00Z", "FINISHED", "Arsenal", "Chelsea", 2, 1),
            _match("2026-08-01T14:00:00Z", "TIMED", "Everton", "Fulham"),
        ]
    }

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(payload)

    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(providers.requests, "get", fake_get)
    now = datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc)

    score_rows = scores.fetch_premier_league_scores(now)
    fixture_rows = fixtures.fetch_premier_league_data(now)

    assert [row["status"] for row in score_rows] == ["FINISHED"]
    assert calls[0]["params"] == {"dateFrom": "2026-07-25", "dateTo": "2026-07-28"}
    assert calls[0]["url"].endswith("/v4/competitions/PL/matches")
    assert len(fixture_rows["scores"]) == 1
    assert len(fixture_rows["fixtures"]) == 1
    assert calls[1]["params"] == {"dateFrom": "2026-07-26", "dateTo": "2026-08-04"}


def test_structured_page_uses_stale_cache_when_api_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from ceefax.src import update_football_scores_page as scores

    payload = {
        "matches": [
            _match("2026-07-28T19:00:00Z", "FINISHED", "Arsenal", "Chelsea", 2, 1)
        ]
    }
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-token")
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(providers, "FRESH_FOOTBALL_SECONDS", 0)
    monkeypatch.setattr(scores, "FRESH_FOOTBALL_SECONDS", 0)
    monkeypatch.setattr(providers.requests, "get", lambda *_a, **_k: FakeResponse(payload))
    current = scores.build_football_scores_page()
    assert any("CURRENT" in line for line in current)

    monkeypatch.delenv("FOOTBALL_DATA_API_KEY")
    stale = scores.build_football_scores_page()
    assert any("STALE" in line for line in stale)
    assert len(stale) == 23
    assert all(len(line) == 50 for line in stale)


def test_missing_key_without_cache_raises_before_page_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from ceefax.src import update_football_scores_page as scores

    writes: list[Any] = []
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(scores, "atomic_write_json", lambda *args: writes.append(args))

    with pytest.raises(ProviderUnavailable, match="FOOTBALL_DATA_API_KEY"):
        scores.main()
    assert writes == []


def test_headlines_keep_bbc_rss_and_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from ceefax.src import update_football_page as football

    rss = b"<rss><channel><item><title>Durable football headline</title></item></channel></rss>"
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(
        football.requests,
        "get",
        lambda url, **_kwargs: FakeResponse({}, content=rss),
    )
    current = football.build_football_page()
    assert any("Durable football headline" in line for line in current)
    assert any("BBC Sport RSS" in line and "CURRENT" in line for line in current)

    monkeypatch.setattr(
        football.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    stale = football.build_football_page()
    assert any("BBC Sport RSS" in line and "STALE" in line for line in stale)
