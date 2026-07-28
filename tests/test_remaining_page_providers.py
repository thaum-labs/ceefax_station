from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceefax.src.providers import ProviderUnavailable


def _raise_offline(*_args, **_kwargs):
    raise RuntimeError("offline")


def test_travel_uses_stale_cache_and_never_writes_error_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_travel_page as travel
    from ceefax.src import providers as providers_mod

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    monkeypatch.setattr(providers_mod, "FRESH_TFL_SECONDS", 0)
    monkeypatch.setattr(travel, "FRESH_TFL_SECONDS", 0)
    live_data = [{"name": "Victoria", "status": "Good Service"}]
    monkeypatch.setattr(travel, "fetch_tfl_line_status", lambda: live_data)
    assert travel.resolve_travel_status().data == live_data

    monkeypatch.setattr(travel, "fetch_tfl_line_status", _raise_offline)
    stale = travel.resolve_travel_status()
    assert stale.stale is True
    assert stale.data == live_data
    assert any("STALE" in line for line in travel.build_travel_page(stale))

    empty_cache = tmp_path / "empty"
    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(empty_cache))
    writes: list[object] = []
    monkeypatch.setattr(travel, "atomic_write_json", lambda *_args: writes.append(_args))
    with pytest.raises(ProviderUnavailable):
        travel.main()
    assert writes == []


def test_other_sports_caches_combined_partial_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_other_sports_page as sports

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    partial = {
        "rugby": ["Rugby headline"],
        "cricket": [],
        "tennis": ["Tennis headline"],
        "motorsport": [],
    }
    monkeypatch.setattr(sports, "fetch_other_sports", lambda: partial)
    live = sports.resolve_other_sports()
    assert live.data == partial
    assert live.source == "BBC Sport RSS"

    monkeypatch.setattr(sports, "fetch_other_sports", lambda: {key: [] for key in partial})
    stale = sports.resolve_other_sports()
    assert stale.stale is True
    assert stale.data == partial
    page = sports.build_other_sports_page(stale)
    assert any("Source: BBC Sport RSS" in line for line in page)
    assert any("STALE" in line for line in page)


def test_fact_provider_chain_caches_first_valid_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_fact_page as fact

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))

    def fake_fetch(url, _parser):
        if "catfact" in url:
            raise RuntimeError("first provider down")
        return "A sufficiently long fact from the second provider."

    monkeypatch.setattr(fact, "_fetch_fact", fake_fetch)
    live = fact.resolve_fact_of_the_day()
    assert live.source == "Numbers API"

    monkeypatch.setattr(fact, "_fetch_fact", _raise_offline)
    stale = fact.resolve_fact_of_the_day()
    assert stale.stale is True
    assert stale.data == live.data
    assert any("STALE" in line for line in fact.build_fact_page(stale))


def test_quiz_caches_normalized_question_and_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_quiz_page as quiz

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    normalized = {
        "question": "Which answer is correct?",
        "answers": {"A": "One", "B": "Two", "C": "Three", "D": "Four"},
        "correct": "B",
        "explanation": "The answer is B) Two",
    }
    monkeypatch.setattr(quiz, "fetch_quiz_question", lambda: normalized)
    assert quiz.resolve_quiz_question().data == normalized

    monkeypatch.setattr(quiz, "fetch_quiz_question", _raise_offline)
    stale = quiz.resolve_quiz_question()
    assert stale.stale is True
    assert stale.data["answers"] == normalized["answers"]
    assert any("STALE" in line for line in quiz.build_quiz_page(stale))


def test_callsign_uses_normalized_cache_without_html_scraping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefax.src import update_callsign_page as callsign

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path))
    normalized = {
        "callsign": "M0ABC",
        "total_spots": 0,
        "recent_contacts": [],
        "bands_used": [],
        "modes_used": [],
        "last_spot_time": None,
        "countries": [],
    }
    monkeypatch.setattr(callsign, "_fetch_normalized_psk_data", lambda _call: normalized)
    callsign.resolve_callsign_data("M0ABC")

    monkeypatch.setattr(callsign, "_fetch_normalized_psk_data", _raise_offline)
    # A recent response is reused for five minutes without another API call.
    fresh_cached = callsign.resolve_callsign_data("M0ABC")
    assert fresh_cached.stale is False

    cache_file = next(tmp_path.glob("*.json"))
    cache_payload = json.loads(cache_file.read_text(encoding="utf-8"))
    cache_payload["fetched_at"] = "2020-01-01T00:00:00Z"
    cache_file.write_text(json.dumps(cache_payload), encoding="utf-8")
    stale = callsign.resolve_callsign_data("M0ABC")
    assert stale.stale is True
    assert any("STALE" in line for line in callsign.build_callsign_page("M0ABC", stale))

    monkeypatch.setattr(
        callsign.requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("HTML scraping request was attempted"),
    )
    assert callsign.fetch_last_report_days("M0ABC") is None

    monkeypatch.setenv("CEEFAX_PROVIDER_CACHE", str(tmp_path / "empty"))
    monkeypatch.setattr(callsign, "get_callsign_from_config", lambda: "M0ABC")
    writes: list[object] = []
    monkeypatch.setattr(callsign, "atomic_write_json", lambda *_args: writes.append(_args))
    with pytest.raises(ProviderUnavailable):
        callsign.main()
    assert writes == []


def test_psk_reporter_uses_documented_rate_limited_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_callsign_page as callsign

    seen: dict = {}

    class Response:
        status_code = 200
        headers = {"content-type": "application/xml"}
        content = b"<receptionReports/>"

        def raise_for_status(self) -> None:
            pass

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(callsign.requests, "get", fake_get)
    assert callsign.fetch_psk_reporter_data("M0ABC") is not None
    assert seen["params"] == {
        "senderCallsign": "M0ABC",
        "flowStartSeconds": "-86400",
        "rptlimit": "50",
        "rronly": "1",
        "noactive": "1",
    }


def test_local_ascii_page_uses_atomic_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefax.src import update_ascii_art_page as ascii_page

    writes: list[tuple[Path, dict]] = []
    monkeypatch.setattr(
        ascii_page,
        "atomic_write_json",
        lambda path, payload: writes.append((path, payload)),
    )
    ascii_page.main()

    assert len(writes) == 1
    path, payload = writes[0]
    assert path.name == "601.json"
    assert payload["page"] == "601"
