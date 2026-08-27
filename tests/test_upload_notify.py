from __future__ import annotations

import os

import pytest

from ceefaxweb import notify


class _FakeResp:
    def __init__(self, status_code: int = 200, text: str = '{"id":"email_1"}') -> None:
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResp(self.status_code)


@pytest.fixture(autouse=True)
def _clear_cooldown(monkeypatch: pytest.MonkeyPatch):
    notify._last_notify_at.clear()
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("CEEFAXWEB_NOTIFY_TO", raising=False)
    monkeypatch.delenv("CEEFAXWEB_NOTIFY_FROM", raising=False)
    monkeypatch.delenv("CEEFAXWEB_NOTIFY_COOLDOWN_SECONDS", raising=False)


def test_notify_disabled_without_config() -> None:
    result = notify.notify_upload(
        reason="tx_ingested",
        uploader_callsign="M7TJF",
        uploader_grid="IO81UF",
        source_path="ceefax/logs_tx/a.json",
        log={"kind": "ceefax_tx_report", "station_callsign": "M7TJF", "page_ids": ["200"]},
    )
    assert result == {"ok": False, "skipped": "not_configured"}


def test_notify_skips_sample_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("CEEFAXWEB_NOTIFY_FROM", "Ceefax <notify@example.com>")
    result = notify.notify_upload(
        reason="tx_ingested",
        uploader_callsign="G0PKT",
        uploader_grid="JO01CE",
        source_path="sample:G0PKT:tx",
        log={"kind": "ceefax_tx_report", "station_callsign": "G0PKT", "page_ids": ["200"]},
    )
    assert result == {"ok": False, "skipped": "sample"}


def test_notify_sends_via_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("CEEFAXWEB_NOTIFY_TO", "tobias.j.franklin@gmail.com")
    monkeypatch.setenv("CEEFAXWEB_NOTIFY_FROM", "Ceefax Station <notify@example.com>")
    monkeypatch.setenv("CEEFAXWEB_NOTIFY_COOLDOWN_SECONDS", "0")
    session = _FakeSession()
    log = {
        "kind": "ceefax_tx_report",
        "station_callsign": "M7TJF",
        "station_grid": "IO81UF",
        "frequency": "144.800 MHz (2m)",
        "page_ids": ["200", "301"],
        "tx_id": "abc-123",
    }
    result = notify.notify_upload(
        reason="tx_ingested",
        uploader_callsign="M7TJF",
        uploader_grid="IO81UF",
        source_path="ceefax/logs_tx/tx.json",
        log=log,
        session=session,
    )
    assert result["ok"] is True
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == notify.RESEND_API_URL
    assert call["headers"]["Authorization"] == "Bearer re_test"
    assert call["json"]["to"] == ["tobias.j.franklin@gmail.com"]
    assert "TX from M7TJF" in call["json"]["subject"]
    assert "Pages (2): 200, 301" in call["json"]["text"]


def test_notify_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("CEEFAXWEB_NOTIFY_FROM", "Ceefax <notify@example.com>")
    monkeypatch.setenv("CEEFAXWEB_NOTIFY_COOLDOWN_SECONDS", "60")
    session = _FakeSession()
    kwargs = dict(
        reason="rx_ingested",
        uploader_callsign="G1RXA",
        uploader_grid="IO91OJ",
        source_path="ceefax/logs_rx/a.json",
        log={
            "schema": 1,
            "listener_callsign": "G1RXA",
            "station_callsign": "GW0CEF",
            "pages_decoded": {"x": {}},
        },
        session=session,
    )
    assert notify.notify_upload(**kwargs)["ok"] is True
    second = notify.notify_upload(**kwargs)
    assert second == {"ok": False, "skipped": "cooldown"}
    assert len(session.calls) == 1


def test_build_rx_email_subject() -> None:
    subject, body = notify.build_upload_email(
        reason="rx_ingested",
        uploader_callsign="G1RXA",
        uploader_grid="IO91OJ",
        source_path="rx.json",
        log={"schema": 1, "listener_callsign": "G1RXA", "station_callsign": "GW0CEF", "pages_decoded": {}},
    )
    assert subject == "Ceefax upload: RX from G1RXA"
    assert "Listener: G1RXA" in body
