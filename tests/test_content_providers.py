from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from ceefax.src.providers import ProviderUnavailable, resolve_provider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


def test_provider_uses_last_good_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    live = resolve_provider("example", [("Example API", lambda: {"value": 1})])
    assert live.stale is False

    cached = resolve_provider(
        "example",
        [("Example API", lambda: (_ for _ in ()).throw(RuntimeError("offline")))],
    )
    assert cached.data == {"value": 1}
    assert cached.source == "Example API"
    assert cached.stale is True
    assert "offline" in (cached.error or "")


def test_tvmaze_filters_and_normalizes_four_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_tv_guide_page as tv

    payload = [
        {
            "airstamp": "2026-07-28T20:30:00Z",
            "runtime": 30,
            "name": "Episode 2",
            "show": {"name": "Example Show", "network": {"name": channel}, "summary": "<p>Summary</p>"},
        }
        for channel in ("BBC One HD", "BBC Two", "ITV", "Channel 4")
    ]
    monkeypatch.setattr(tv.requests, "get", lambda *_args, **_kwargs: FakeResponse(payload))
    items = tv.fetch_tvmaze_schedule(
        start_utc=datetime(2026, 7, 28, 20, tzinfo=timezone.utc),
        end_utc=datetime(2026, 7, 28, 22, tzinfo=timezone.utc),
    )
    assert {item["channel"] for item in items} == set(tv.POPULAR_CHANNELS)
    assert all(item["synopsis"] == "Summary" for item in items)


def test_tvmaze_accepts_partial_channel_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_tv_guide_page as tv

    payload = [
        {
            "airstamp": "2026-07-28T20:30:00Z",
            "runtime": 30,
            "show": {"name": "Example", "network": {"name": channel}},
        }
        for channel in ("BBC One", "ITV1", "Channel 4")
    ]
    monkeypatch.setattr(tv.requests, "get", lambda *_args, **_kwargs: FakeResponse(payload))
    items = tv.fetch_tvmaze_schedule(
        start_utc=datetime(2026, 7, 28, 20, tzinfo=timezone.utc),
        end_utc=datetime(2026, 7, 28, 22, tzinfo=timezone.utc),
    )
    assert {item["channel"] for item in items} == {"BBC One", "ITV1", "Channel 4"}


def test_tvmaze_reads_embedded_show_from_full_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_tv_guide_page as tv

    payload = [
        {
            "airstamp": "2026-07-28T20:30:00Z",
            "runtime": 60,
            "name": "Episode 1",
            "_embedded": {
                "show": {"name": "Embedded Show", "network": {"name": "BBC Two"}, "summary": "<p>Hi</p>"}
            },
        }
    ]
    monkeypatch.setattr(tv.requests, "get", lambda *_args, **_kwargs: FakeResponse(payload))
    items = tv.fetch_tvmaze_schedule(
        start_utc=datetime(2026, 7, 28, 20, tzinfo=timezone.utc),
        end_utc=datetime(2026, 7, 28, 22, tzinfo=timezone.utc),
    )
    assert items[0]["channel"] == "BBC Two"
    assert items[0]["title"] == "Embedded Show"
    assert items[0]["synopsis"] == "Hi"


def test_tvmaze_rejects_empty_listings(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_tv_guide_page as tv

    monkeypatch.setattr(tv.requests, "get", lambda *_args, **_kwargs: FakeResponse([]))
    with pytest.raises(ValueError, match="no listings"):
        tv.fetch_tvmaze_schedule(
            start_utc=datetime(2026, 7, 28, 20, tzinfo=timezone.utc),
            end_utc=datetime(2026, 7, 28, 22, tzinfo=timezone.utc),
        )


def test_tmdb_uses_gb_region_for_release_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_film_picks_page as films

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return FakeResponse({"results": [{"title": "Film", "vote_average": 8, "release_date": "2026-08-01"}]})

    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    monkeypatch.setattr(films.requests, "get", fake_get)
    result = films.fetch_tmdb_films()
    assert set(result) == {"now_playing", "popular", "upcoming"}
    params = {url.rsplit("/", 1)[-1]: values for url, values in calls}
    assert params["now_playing"]["region"] == "GB"
    assert params["upcoming"]["region"] == "GB"
    assert "region" not in params["popular"]


def test_tmdb_without_key_or_cache_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_film_picks_page as films

    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    with pytest.raises(ProviderUnavailable):
        films.get_film_data()


def test_frankfurter_derives_gbp_cross_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_exchange_rates_page as exchange

    monkeypatch.setattr(
        exchange.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(
            {"rates": {"GBP": 0.8, "USD": 1.2, "JPY": 160, "CHF": 0.9, "CAD": 1.5, "AUD": 1.6}}
        ),
    )
    rates = exchange.fetch_exchange_rates()
    assert rates["EUR"] == pytest.approx(1.25)
    assert rates["USD"] == pytest.approx(1.5)
    assert rates["JPY"] == pytest.approx(200)


def test_wikimedia_user_agent_and_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_on_this_day_page as history

    request = {}

    def fake_get(url, **kwargs):
        request.update(url=url, **kwargs)
        return FakeResponse({"events": [{"year": 1969, "text": "A historical event."}]})

    monkeypatch.setattr(history.requests, "get", fake_get)
    data = history.fetch_wikimedia_on_this_day(datetime(2026, 7, 28))
    assert data["events"] == ["1969 - A historical event."]
    assert request["headers"]["User-Agent"] == history.WIKIMEDIA_USER_AGENT
    assert request["url"].endswith("/07/28")


def test_jokeapi_safe_mode_and_local_fallback(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_joke_page as jokes

    request = {}

    def fake_get(_url, **kwargs):
        request.update(kwargs)
        return FakeResponse({"type": "twopart", "setup": "Setup?", "delivery": "Punchline!", "error": False})

    monkeypatch.setattr(jokes.requests, "get", fake_get)
    assert jokes.fetch_jokeapi() == ("Setup?", "Punchline!")
    assert "safe-mode" in request["params"]

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(jokes, "fetch_jokeapi", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    first = jokes.fetch_joke_of_the_day(datetime(2026, 7, 28))
    second = jokes.fetch_joke_of_the_day(datetime(2026, 7, 28))
    assert first.data == second.data
    assert first.source == "Local safe jokes"


def test_quote_selection_is_deterministic_and_offline() -> None:
    from ceefax.src.update_quote_page import fetch_quote_of_the_day

    assert fetch_quote_of_the_day(date(2026, 7, 28)) == fetch_quote_of_the_day(date(2026, 7, 28))
    quote, author = fetch_quote_of_the_day(date(2026, 7, 28))
    assert quote and author
