from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_persist_radio_config_preserves_frequency_and_grid(tmp_path: Path) -> None:
    from ceefax.src.update_all import persist_radio_config

    cfg = tmp_path / "radio_config.json"
    cfg.write_text(
        json.dumps({"callsign": "M7TJF", "frequency": "145.500 MHz", "grid": "IO91WM"}),
        encoding="utf-8",
    )

    # Hourly priming passes empty frequency; must not wipe existing fields.
    persist_radio_config("M7TJF", frequency="", config_path=cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["callsign"] == "M7TJF"
    assert data["frequency"] == "145.500 MHz"
    assert data["grid"] == "IO91WM"

    # New grid only fills when missing.
    cfg.write_text(json.dumps({"callsign": "M7TJF", "frequency": "145.500 MHz"}), encoding="utf-8")
    persist_radio_config("M7TJF", frequency="", grid="JO02aa", config_path=cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["grid"] == "JO02AA"

    # Existing grid is not overwritten.
    persist_radio_config("M7TJF", frequency="433.500 MHz", grid="IO91XX", config_path=cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["frequency"] == "433.500 MHz"
    assert data["grid"] == "JO02AA"


def test_audio_level_regex_parses_direwolf_line() -> None:
    from ceefax.src.viewer import _AUDIO_LEVEL_RE, _maybe_update_audio_db

    m = _AUDIO_LEVEL_RE.search("Audio level = -12.3 dB")
    assert m is not None
    assert m.group(1) == "-12.3"

    stats: dict = {}
    _maybe_update_audio_db(stats, line="audio level = 7")
    assert stats["rx_db"] == 7.0


def test_progress_bar_fixed_width() -> None:
    from ceefax.src.viewer import _format_progress_bar

    width = 20
    for pct in (0.0, 0.05, 0.5, 0.99, 1.0):
        bar = _format_progress_bar(width, pct)
        assert len(bar) == width + 2
        assert bar[0] == "[" and bar[-1] == "]"


def test_normalize_page_id_accepts_string_subpage() -> None:
    from ceefaxweb.db import _normalize_page_id

    assert _normalize_page_id("503", 2) == "503.2"
    assert _normalize_page_id("503", "2") == "503.2"
    assert _normalize_page_id("503", 1) == "503"
    assert _normalize_page_id("503", "1") == "503"
    assert _normalize_page_id("503", None) == "503"
    assert _normalize_page_id("", "2") == ""


def test_query_link_detail_includes_rx_only_pages(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from ceefaxweb.db import connect, init_db, query_link_detail

    db_path = tmp_path / "t.sqlite3"
    conn = connect(db_path)
    init_db(conn)

    seen = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO stations(callsign, grid, lat, lon, first_seen_utc, last_seen_utc) VALUES (?,?,?,?,?,?)",
        ("TX1", "IO91WM", 51.5, -0.1, "2026-01-01T00:00:00Z", seen),
    )
    conn.execute(
        "INSERT INTO stations(callsign, grid, lat, lon, first_seen_utc, last_seen_utc) VALUES (?,?,?,?,?,?)",
        ("RX1", "IO91XN", 51.6, -0.05, "2026-01-01T00:00:00Z", seen),
    )
    conn.execute(
        "INSERT INTO receptions(rx_callsign, tx_callsign, tx_id, received_at_utc, page_id, freq, rx_db) VALUES (?,?,?,?,?,?,?)",
        ("RX1", "TX1", "tx-only-rx", seen, "101", "145.500 MHz", -8.5),
    )
    conn.commit()

    detail = query_link_detail(conn, tx="TX1", rx="RX1", range_key="30d")
    assert detail["rows"], "expected RX-only page rows"
    assert detail["rows"][0]["page_id"] == "101"
    assert detail["rows"][0]["tx"] is False
    assert detail["rows"][0]["rx_ok"] is True
    conn.close()


def test_ingest_accepts_public_upload_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CEEFAXWEB_DB", str(tmp_path / "web.sqlite3"))
    monkeypatch.setenv("CEEFAXWEB_UPLOAD_TOKEN", "secret-should-not-be-required")

    # Import after env is set so lifespan picks up CEEFAXWEB_DB.
    import importlib
    import ceefaxweb.server as server_mod

    importlib.reload(server_mod)

    with TestClient(server_mod.create_app()) as client:
        body = {
            "uploader": {"callsign": "M7TJF", "grid": "IO91WM"},
            "source_path": "test.json",
            "log": {
                "schema": 1,
                "kind": "ceefax_tx_report",
                "tx_id": "11111111-1111-1111-1111-111111111111",
                "station_callsign": "M7TJF",
                "station_grid": "IO91WM",
                "generated_at": "2026-07-28T12:00:00Z",
                "page_ids": ["000"],
            },
        }
        # No token field at all
        resp = client.post("/api/ingest/log", json=body)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Wrong token still accepted (public by design)
        body2 = dict(body)
        body2["token"] = "wrong"
        body2["source_path"] = "test2.json"
        body2["log"] = dict(body["log"])
        body2["log"]["tx_id"] = "22222222-2222-2222-2222-222222222222"
        resp2 = client.post("/api/ingest/log", json=body2)
        assert resp2.status_code == 200
        assert resp2.json()["ok"] is True


def test_upload_log_file_posts_once_and_skips_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefaxstation import uploader as up

    root = tmp_path
    (root / "ceefax" / "logs_tx").mkdir(parents=True)
    (root / "ceefax" / "cache").mkdir(parents=True)
    log_path = root / "ceefax" / "logs_tx" / "tx.json"
    log_path.write_text(json.dumps({"schema": 1, "kind": "ceefax_tx_report"}), encoding="utf-8")

    monkeypatch.setattr(up, "_repo_root", lambda: root)
    posts: list[dict] = []

    class Ok:
        def raise_for_status(self) -> None:
            return None

    def fake_post(_url: str, **kwargs):
        posts.append(kwargs.get("json") or {})
        return Ok()

    monkeypatch.setattr(up.requests, "post", fake_post)

    assert up.upload_log_file(
        log_path,
        server_url="https://example.test",
        uploader_callsign="M7TJF",
        uploader_grid="IO91WM",
        wait_stable=False,
    )
    assert len(posts) == 1
    assert posts[0]["uploader"]["callsign"] == "M7TJF"

    assert up.upload_log_file(
        log_path,
        server_url="https://example.test",
        uploader_callsign="M7TJF",
        uploader_grid="IO91WM",
        wait_stable=False,
    )
    assert len(posts) == 1  # duplicate content skipped


def test_auto_upload_log_respects_disable_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ceefaxstation import uploader as up

    called: list[Path] = []
    monkeypatch.setenv("CEEFAX_AUTO_UPLOAD", "0")
    monkeypatch.setattr(up, "upload_log_file", lambda path, **_k: called.append(Path(path)) or True)

    up.auto_upload_log(tmp_path / "x.json")
    assert called == []


def test_uploader_scan_continues_after_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ceefaxstation import uploader as up

    root = tmp_path
    (root / "ceefax" / "logs_tx").mkdir(parents=True)
    (root / "ceefax" / "logs_rx").mkdir(parents=True)
    (root / "ceefax" / "cache").mkdir(parents=True)

    log_path = root / "ceefax" / "logs_tx" / "a.json"
    log_path.write_text(json.dumps({"schema": 1, "kind": "ceefax_tx_report"}), encoding="utf-8")

    monkeypatch.setattr(up, "_repo_root", lambda: root)

    class Boom:
        def raise_for_status(self) -> None:
            raise up.requests.HTTPError("500")

    def fake_post(*_a, **_k):
        return Boom()

    monkeypatch.setattr(up.requests, "post", fake_post)

    # Should not raise; state should not mark file as uploaded.
    up.upload_logs(
        server_url="https://example.test",
        token=None,
        uploader_callsign="M7TJF",
        uploader_grid="IO91WM",
        once=True,
    )
    state = up._load_state()
    assert state.get("files") in ({}, None) or "ceefax/logs_tx/a.json" not in state.get("files", {})


def test_download_routes_redirect_to_github_release_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CEEFAXWEB_DB", str(tmp_path / "web.sqlite3"))
    import importlib
    import ceefaxweb.server as server_mod

    importlib.reload(server_mod)
    with TestClient(server_mod.create_app()) as client:
        windows = client.get("/download", follow_redirects=False)
        assert windows.status_code == 302
        assert windows.headers["location"].endswith("CeefaxStation-Setup.exe")

        linux = client.get("/download/linux", follow_redirects=False)
        assert linux.status_code == 302
        assert linux.headers["location"].endswith("ceefax-station.deb")

        alias = client.get("/download/windows", follow_redirects=False)
        assert alias.status_code == 302
        assert alias.headers["location"].endswith("CeefaxStation-Setup.exe")
