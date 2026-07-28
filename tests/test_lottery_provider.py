from __future__ import annotations

from typing import Any

import pytest

from ceefax.src.providers import ProviderResult, ProviderUnavailable


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


LOTTO_PAYLOAD = {
    "results": [
        {
            "draw_date": "2026-07-25",
            "balls": ["4", 12, 18, 27, 41, 55],
            "ball_bonus": 9,
        }
    ]
}
EURO_PAYLOAD = {
    "results": [
        {
            "draw_date": "2026-07-24",
            "balls": [3, "14", 22, 35, 48],
            "ball_bonus": ["2", 11],
        }
    ]
}


def test_api_auth_params_normalization_and_fresh_cache(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_lottery_page as lottery

    calls: list[dict[str, Any]] = []
    responses = iter((LOTTO_PAYLOAD, EURO_PAYLOAD))

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(next(responses))

    monkeypatch.setenv("LOTTERY_RESULTS_API_KEY", "secret-token")
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(lottery.requests, "get", fake_get)

    result = lottery.get_lottery_results()

    assert result.data["national"] == {
        "draw_date": "2026-07-25",
        "numbers": [4, 12, 18, 27, 41, 55],
        "bonus_ball": 9,
    }
    assert result.data["euromillions"]["lucky_stars"] == [2, 11]
    assert [call["params"] for call in calls] == [
        {"slug": "uk-lotto", "country": "uk", "limit": 1},
        {"id": 722, "limit": 1},
    ]
    assert all(call["url"] == lottery.LOTTERY_RESULTS_API for call in calls)
    assert all(call["headers"] == {"Authorization": "Bearer secret-token"} for call in calls)
    assert all(call["timeout"] == 15 for call in calls)

    cached = lottery.get_lottery_results()
    assert cached.data == result.data
    assert cached.stale is False
    assert len(calls) == 2


def test_missing_key_and_live_failure_use_indefinite_stale_cache(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_lottery_page as lottery

    responses = iter((LOTTO_PAYLOAD, EURO_PAYLOAD))
    monkeypatch.setenv("LOTTERY_RESULTS_API_KEY", "seed-key")
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(
        lottery.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(next(responses)),
    )
    live = lottery.get_lottery_results()

    monkeypatch.delenv("LOTTERY_RESULTS_API_KEY")
    monkeypatch.setattr(lottery, "CACHE_FRESH_SECONDS", -1)
    stale = lottery.get_lottery_results()

    assert stale.data == live.data
    assert stale.stale is True
    assert "LOTTERY_RESULTS_API_KEY" in (stale.error or "")

    monkeypatch.setenv("LOTTERY_RESULTS_API_KEY", "configured-again")
    monkeypatch.setattr(
        lottery.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )
    failed_live = lottery.get_lottery_results()
    assert failed_live.data == live.data
    assert failed_live.stale is True
    assert "network down" in (failed_live.error or "")


def test_no_cache_raises_without_overwriting_page(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_lottery_page as lottery

    writes: list[tuple[Any, ...]] = []
    monkeypatch.delenv("LOTTERY_RESULTS_API_KEY", raising=False)
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(lottery, "atomic_write_json", lambda *args: writes.append(args))

    with pytest.raises(ProviderUnavailable, match="LOTTERY_RESULTS_API_KEY"):
        lottery.main()
    assert writes == []


def test_page_content_marks_source_as_of_stale_and_prize_warning() -> None:
    from ceefax.src import update_lottery_page as lottery

    result = ProviderResult(
        data={
            "national": {
                "draw_date": "2026-07-25",
                "numbers": [4, 12, 18, 27, 41, 55],
                "bonus_ball": 9,
            },
            "euromillions": {
                "draw_date": "2026-07-24",
                "numbers": [3, 14, 22, 35, 48],
                "lucky_stars": [2, 11],
            },
        },
        source="Lottery Results Feed",
        fetched_at="2026-07-25T20:00:00Z",
        stale=True,
    )

    page = lottery.build_lottery_page(result)

    assert all(len(line) == 50 for line in page)
    assert any("LOTTO" in line for line in page)
    assert any("EUROMILLIONS" in line for line in page)
    assert any("Lottery Results Feed [STALE]" in line for line in page)
    assert any("Stale/as-of: 2026-07-25T20:00:00Z" in line for line in page)
    assert any("Verify prizes with the official operator." in line for line in page)
