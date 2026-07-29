from __future__ import annotations

import json
import math

import pytest

from ceefax.src.providers import (
    ProviderResult,
    atomic_write_json,
    clear_provider_activity,
    provider_activity_snapshot,
    resolve_provider,
)


def test_provider_activity_records_live_and_stale_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    clear_provider_activity()

    live = resolve_provider("weather-test", [("Live API", lambda: {"temperature": 18})])
    assert live.stale is False
    assert provider_activity_snapshot()["weather-test"] == live

    stale = resolve_provider(
        "weather-test",
        [("Live API", lambda: (_ for _ in ()).throw(RuntimeError("offline")))],
    )
    assert stale.stale is True
    assert provider_activity_snapshot()["weather-test"] == stale

    clear_provider_activity()
    assert provider_activity_snapshot() == {}


def test_fresh_cache_is_reused_without_calling_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    resolve_provider("rates", [("ECB", lambda: {"GBP": 1.0})])
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        return {"GBP": 2.0}

    result = resolve_provider("rates", [("ECB", fetch)], fresh_for_seconds=3600)
    assert result.data == {"GBP": 1.0}
    assert result.stale is False
    assert calls == 0


def test_atomic_write_json_replaces_complete_document(tmp_path) -> None:
    path = tmp_path / "page.json"
    atomic_write_json(path, {"page": "101", "content": ["old"]})
    atomic_write_json(path, {"page": "101", "content": ["new"]})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "page": "101",
        "content": ["new"],
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_invalid_cached_shape_is_rejected(tmp_path, monkeypatch) -> None:
    from ceefax.src.providers import ProviderUnavailable

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    resolve_provider("shape", [("API", lambda: {"items": [1]})])
    cache_file = next(tmp_path.glob("*.json"))
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["data"] = {"wrong": True}
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProviderUnavailable):
        resolve_provider(
            "shape",
            [("API", lambda: (_ for _ in ()).throw(RuntimeError("offline")))],
            is_valid=lambda data: isinstance(data, dict) and bool(data.get("items")),
        )


def test_provider_errors_redact_environment_secrets(tmp_path, monkeypatch) -> None:
    from ceefax.src.providers import ProviderUnavailable

    secret = "super-secret-api-key"
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setenv("GUARDIAN_API_KEY", secret)

    with pytest.raises(ProviderUnavailable) as caught:
        resolve_provider(
            "secret",
            [("API", lambda: (_ for _ in ()).throw(RuntimeError(f"https://api.test/?key={secret}")))],
        )
    assert secret not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)


def test_cache_failure_does_not_discard_live_data(tmp_path, monkeypatch) -> None:
    from ceefax.src import providers

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(providers, "save_last_good", lambda *_args: (_ for _ in ()).throw(OSError("read only")))
    result = providers.resolve_provider("live", [("API", lambda: {"ok": True})])
    assert result.data == {"ok": True}
    assert "cache write failed" in (result.error or "")


def test_atomic_json_rejects_non_finite_numbers_without_replacing(tmp_path) -> None:
    path = tmp_path / "page.json"
    atomic_write_json(path, {"value": 1})
    with pytest.raises(ValueError):
        atomic_write_json(path, {"value": math.nan})
    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 1}


def test_system_status_displays_cached_provider_state() -> None:
    from ceefax.src.update_system_status_page import build_system_status_page

    labels = [
        "Weather (Open-Meteo)",
        "News (Guardian/BBC)",
        "Sport (API/RSS)",
        "Exchange Rates",
        "Travel (TFL)",
        "TV (TVMaze)",
        "Film (TMDB)",
        "Lottery",
        "Entertainment APIs",
        "PSK Reporter",
    ]
    statuses = {label: (True, "OK") for label in labels}
    statuses["Weather (Open-Meteo)"] = (True, "STALE")

    lines = build_system_status_page(statuses, "20:00:00", 30, 60, hub_pack_stamp="2026-07-29 15:54 UTC (30 pages)")
    assert any("Weather (Open-Meteo)" in line and "CACHED" in line for line in lines)
    assert any("Operating with cached data" in line for line in lines)
    assert any("Hub Pack:" in line and "2026-07-29 15:54 UTC" in line for line in lines)
