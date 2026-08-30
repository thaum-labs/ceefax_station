from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ceefaxweb.db import connect, ingest_log, init_db, query_link_detail, query_map
from ceefaxweb.scripts.delete_sample_data import delete_sample_data


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_offset(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()  # keeps +00:00


def _seed_station(
    conn,
    *,
    callsign: str,
    seen_at: datetime,
    tx_at: datetime | None = None,
    tx_ts: str | None = None,
    freq: str = "7.040 MHz (40m)",
) -> None:
    seen = _iso_z(seen_at)
    conn.execute(
        "INSERT INTO stations(callsign, grid, lat, lon, first_seen_utc, last_seen_utc) VALUES (?,?,?,?,?,?)",
        (callsign, "IO91WM", 51.5, -0.1, seen, seen),
    )
    if tx_at is not None or tx_ts is not None:
        ts = tx_ts if tx_ts is not None else _iso_z(tx_at or seen_at)
        conn.execute(
            "INSERT INTO transmissions(tx_id, tx_callsign, generated_at_utc, page_id, freq) VALUES (?,?,?,?,?)",
            (f"tx-{callsign}", callsign, ts, "101", freq),
        )
    conn.commit()


def _callsigns(data: dict) -> set[str]:
    return {s["callsign"] for s in data["stations"]}


def test_recent_station_still_shows_on_24h(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.sqlite3")
    init_db(conn)
    twelve_hours_ago = datetime.now(timezone.utc) - timedelta(hours=12)
    _seed_station(conn, callsign="G0NOW", seen_at=twelve_hours_ago, tx_at=twelve_hours_ago)

    m24 = query_map(conn, range_key="24h")
    assert "G0NOW" in _callsigns(m24)
    st = next(s for s in m24["stations"] if s["callsign"] == "G0NOW")
    assert st["is_tx"] is True
    conn.close()


def test_station_older_than_24h_reappears_on_7d_and_30d(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.sqlite3")
    init_db(conn)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    _seed_station(conn, callsign="G0OLD", seen_at=two_days_ago, tx_at=two_days_ago)

    m24 = query_map(conn, range_key="24h")
    m7 = query_map(conn, range_key="7d")
    m30 = query_map(conn, range_key="30d")

    assert "G0OLD" not in _callsigns(m24)
    assert "G0OLD" in _callsigns(m7)
    assert "G0OLD" in _callsigns(m30)

    st7 = next(s for s in m7["stations"] if s["callsign"] == "G0OLD")
    assert st7["is_tx"] is True
    assert st7["tx_pages_unique"] == 1
    conn.close()


def test_listening_only_station_follows_last_seen_window(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.sqlite3")
    init_db(conn)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    _seed_station(conn, callsign="M7WAIT", seen_at=two_days_ago)

    m24 = query_map(conn, range_key="24h")
    m7 = query_map(conn, range_key="7d")

    assert "M7WAIT" not in _callsigns(m24)
    assert "M7WAIT" in _callsigns(m7)
    st = next(s for s in m7["stations"] if s["callsign"] == "M7WAIT")
    assert st["is_tx"] is False
    assert st["status"] == "none"
    conn.close()


def test_tx_timestamp_with_offset_suffix_counts_in_7d(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.sqlite3")
    init_db(conn)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    _seed_station(
        conn,
        callsign="F8COD",
        seen_at=two_days_ago,
        tx_ts=_iso_offset(two_days_ago),
    )

    m7 = query_map(conn, range_key="7d")
    st = next(s for s in m7["stations"] if s["callsign"] == "F8COD")
    assert st["is_tx"] is True
    assert st["tx_pages_unique"] == 1

    detail = query_link_detail(conn, tx="F8COD", rx="NONE", range_key="7d")
    assert [r["page_id"] for r in detail["rows"] if r["tx"]] == ["101"]
    conn.close()


def test_station_20_days_ago_only_in_30d(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.sqlite3")
    init_db(conn)
    twenty_days_ago = datetime.now(timezone.utc) - timedelta(days=20)
    _seed_station(conn, callsign="G4OLD", seen_at=twenty_days_ago, tx_at=twenty_days_ago)

    assert "G4OLD" not in _callsigns(query_map(conn, range_key="24h"))
    assert "G4OLD" not in _callsigns(query_map(conn, range_key="7d"))
    assert "G4OLD" in _callsigns(query_map(conn, range_key="30d"))
    conn.close()


def test_ingested_old_tx_shows_on_7d_not_24h(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.sqlite3")
    init_db(conn)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    ts = _iso_z(two_days_ago)
    inserted, reason = ingest_log(
        conn,
        payload={
            "schema": 1,
            "kind": "ceefax_tx_report",
            "tx_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "station_callsign": "G0OLD",
            "station_grid": "IO91WM",
            "generated_at": ts,
            "completed_at": ts,
            "page_ids": ["101"],
            "frequency": "7.040 MHz (40m)",
        },
        uploader_callsign="G0OLD",
        uploader_grid="IO91WM",
        source_path="logs_tx/old.json",
    )
    assert inserted and reason == "tx_ingested"
    assert "G0OLD" not in _callsigns(query_map(conn, range_key="24h"))
    m7 = query_map(conn, range_key="7d")
    assert "G0OLD" in _callsigns(m7)
    st = next(s for s in m7["stations"] if s["callsign"] == "G0OLD")
    assert st["is_tx"] is True
    conn.close()


def test_delete_sample_data_keeps_listening_only_station(tmp_path: Path) -> None:
    db_path = tmp_path / "t.sqlite3"
    conn = connect(db_path)
    init_db(conn)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    _seed_station(conn, callsign="M7WAIT", seen_at=two_days_ago)
    conn.close()

    delete_sample_data(db_path)

    conn = connect(db_path)
    row = conn.execute("SELECT callsign FROM stations WHERE callsign = ?", ("M7WAIT",)).fetchone()
    assert row is not None
    conn.close()
