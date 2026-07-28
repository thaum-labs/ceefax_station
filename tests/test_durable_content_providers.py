from __future__ import annotations

from pathlib import Path

import pytest


class _Response:
    def __init__(self, payload: dict, *, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_open_meteo_fetch_is_structured_and_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import weather_map

    calls: list[tuple[str, dict]] = []
    responses = iter(
        [
            _Response({"results": [{"latitude": 51.23, "longitude": -2.32, "name": "Frome"}]}),
            _Response(
                {
                    "current": {
                        "temperature_2m": 17.6,
                        "apparent_temperature": 16.8,
                        "weather_code": 2,
                        "wind_speed_10m": 12.2,
                        "wind_direction_10m": 225,
                    },
                    "daily": {
                        "weather_code": [2, 61],
                        "temperature_2m_max": [19.2, 16.1],
                        "temperature_2m_min": [10.4, 9.8],
                    },
                }
            ),
        ]
    )

    def fake_get(url: str, **kwargs):
        calls.append((url, kwargs["params"]))
        return next(responses)

    monkeypatch.setattr(weather_map.requests, "get", fake_get)
    summary = weather_map.fetch_open_meteo("Frome,UK")

    assert summary.location == "Frome"
    assert summary.temp_c == "18"
    assert summary.description == "Partly cloudy"
    assert summary.wind_dir == "SW"
    assert summary.tomorrow_desc == "Light rain"
    assert calls[0][0] == weather_map.OPEN_METEO_GEOCODING_URL
    assert "apikey" not in calls[0][1] and "api_key" not in calls[0][1]
    assert calls[1][0] == weather_map.OPEN_METEO_FORECAST_URL


def test_guardian_request_uses_key_section_and_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import news_providers

    monkeypatch.setenv("GUARDIAN_API_KEY", "test-key")
    seen: dict = {}

    def fake_get(url: str, **kwargs):
        seen.update(url=url, **kwargs)
        return _Response(
            {
                "response": {
                    "results": [
                        {"fields": {"headline": "Somerset headline"}},
                        {"webTitle": "Fallback title"},
                    ]
                }
            }
        )

    monkeypatch.setattr(news_providers.requests, "get", fake_get)
    headlines = news_providers.fetch_guardian_headlines(
        section="uk-news", query="Somerset", limit=2
    )

    assert headlines == ["Somerset headline", "Fallback title"]
    assert seen["url"] == news_providers.GUARDIAN_SEARCH_URL
    assert seen["params"]["api-key"] == "test-key"
    assert seen["params"]["section"] == "uk-news"
    assert seen["params"]["q"] == "Somerset"


def test_news_prefers_guardian_then_uses_stale_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_news_page

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setenv("GUARDIAN_API_KEY", "configured")
    monkeypatch.setattr(
        update_news_page,
        "fetch_guardian_headlines",
        lambda **_kwargs: ["Cached Somerset story"],
    )
    monkeypatch.setattr(
        update_news_page,
        "fetch_headlines",
        lambda _limit=6: (_ for _ in ()).throw(RuntimeError("BBC unavailable")),
    )

    live = update_news_page.resolve_headlines()
    assert live.source == "Guardian Open Platform"
    assert live.stale is False

    monkeypatch.setattr(
        update_news_page,
        "fetch_guardian_headlines",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("Guardian unavailable")),
    )
    stale = update_news_page.resolve_headlines()
    assert stale.data == ["Cached Somerset story"]
    assert stale.stale is True
    assert "STALE" in update_news_page.build_news_page(stale)[2]


def test_news_without_live_or_cache_raises_and_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_uk_news_page
    from ceefax.src.providers import ProviderUnavailable

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)
    monkeypatch.setattr(
        update_uk_news_page,
        "fetch_headlines",
        lambda _limit=6: (_ for _ in ()).throw(RuntimeError("BBC unavailable")),
    )
    writes: list[object] = []
    monkeypatch.setattr(update_uk_news_page, "atomic_write_json", lambda *_args: writes.append(_args))

    with pytest.raises(ProviderUnavailable):
        update_uk_news_page.main()
    assert writes == []


def test_weather_101_writes_all_six_pages_from_resolved_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_uk_weather_page
    from ceefax.src.weather_map import WeatherSummary

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))

    def fake_many(queries, **_kwargs):
        return {
            query: WeatherSummary(
                location=query,
                temp_c="12",
                feels_like_c="11",
                description="Clear sky",
                wind_kph="8",
                wind_dir="W",
                icon="sun",
                today_max="14",
                today_min="7",
                today_desc="Clear sky",
                tonight_min="7",
                tonight_desc="Clear sky",
                tomorrow_desc="Partly cloudy",
            )
            for query in queries
        }

    writes: list[tuple[Path, dict]] = []
    monkeypatch.setattr(update_uk_weather_page, "fetch_open_meteo_many", fake_many)
    monkeypatch.setattr(
        update_uk_weather_page,
        "atomic_write_json",
        lambda path, payload: writes.append((path, payload)),
    )

    update_uk_weather_page.main()

    assert len(writes) == 6
    assert [payload["subpage"] for _, payload in writes] == [1, 2, 3, 4, 5, 6]
    assert all("Open-Meteo" in payload["timestamp"] for _, payload in writes)
