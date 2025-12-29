from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .maidenhead import haversine_km, maidenhead_to_latlon, maidenhead_bbox


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(dt: str | None) -> datetime | None:
    if not dt:
        return None
    try:
        # Accept both "Z" and naive.
        s = dt.replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


@dataclass(frozen=True)
class DbPaths:
    db_path: Path


def default_db_path(repo_root: Path) -> Path:
    d = repo_root / "ceefax" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ceefaxweb.sqlite3"


def connect(db_path: Path) -> sqlite3.Connection:
    # FastAPI handlers may run in threadpool; allow cross-thread use for this simple DB.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stations (
          callsign TEXT PRIMARY KEY,
          grid TEXT,
          lat REAL,
          lon REAL,
          first_seen_utc TEXT,
          last_seen_utc TEXT
        );

        CREATE TABLE IF NOT EXISTS ingested_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL,
          callsign TEXT,
          source_path TEXT,
          content_sha256 TEXT NOT NULL,
          observed_at_utc TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ingested_unique ON ingested_logs(content_sha256);

        CREATE TABLE IF NOT EXISTS transmissions (
          tx_id TEXT NOT NULL,
          tx_callsign TEXT NOT NULL,
          generated_at_utc TEXT NOT NULL,
          page_id TEXT NOT NULL,
          PRIMARY KEY (tx_id, page_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tx_time ON transmissions(generated_at_utc);
        CREATE INDEX IF NOT EXISTS idx_tx_callsign ON transmissions(tx_callsign);

        CREATE TABLE IF NOT EXISTS receptions (
          rx_callsign TEXT NOT NULL,
          tx_callsign TEXT,
          tx_id TEXT,
          received_at_utc TEXT NOT NULL,
          page_id TEXT NOT NULL,
          PRIMARY KEY (rx_callsign, tx_id, page_id)
        );
        CREATE INDEX IF NOT EXISTS idx_rx_time ON receptions(received_at_utc);
        CREATE INDEX IF NOT EXISTS idx_rx_callsign ON receptions(rx_callsign);
        CREATE INDEX IF NOT EXISTS idx_rx_pair ON receptions(tx_callsign, rx_callsign);
        """
    )
    # Lightweight schema migrations (SQLite has no IF NOT EXISTS for columns).
    def ensure_col(table: str, col: str, decl: str) -> None:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col in cols:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    ensure_col("transmissions", "freq", "TEXT")
    ensure_col("receptions", "freq", "TEXT")
    ensure_col("receptions", "rx_db", "REAL")

    conn.commit()


def upsert_station(conn: sqlite3.Connection, *, callsign: str, grid: str | None) -> None:
    cs = (callsign or "").strip().upper()
    if not cs:
        return
    grid2 = (grid or "").strip().upper() or None
    latlon = maidenhead_to_latlon(grid2) if grid2 else None
    lat = latlon[0] if latlon else None
    lon = latlon[1] if latlon else None
    now = _utcnow_iso()

    # Preserve first_seen, update last_seen; update grid/lat/lon if provided.
    row = conn.execute("SELECT first_seen_utc, grid FROM stations WHERE callsign = ?", (cs,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT OR REPLACE INTO stations(callsign, grid, lat, lon, first_seen_utc, last_seen_utc) VALUES (?,?,?,?,?,?)",
            (cs, grid2, lat, lon, now, now),
        )
    else:
        first_seen = row["first_seen_utc"] or now
        # Only overwrite grid if new grid provided.
        use_grid = grid2 if grid2 else row["grid"]
        use_latlon = maidenhead_to_latlon(use_grid) if use_grid else None
        use_lat = use_latlon[0] if use_latlon else None
        use_lon = use_latlon[1] if use_latlon else None
        conn.execute(
            "UPDATE stations SET grid=?, lat=?, lon=?, first_seen_utc=?, last_seen_utc=? WHERE callsign=?",
            (use_grid, use_lat, use_lon, first_seen, now, cs),
        )
    conn.commit()


def ingest_log(
    conn: sqlite3.Connection,
    *,
    payload: dict[str, Any],
    uploader_callsign: str | None,
    uploader_grid: str | None,
    source_path: str | None,
) -> tuple[bool, str]:
    """
    Insert log JSON + derive transmissions/receptions rows.
    Returns: (inserted, reason)
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sha = _sha256_text(raw)
    try:
        conn.execute(
            "INSERT INTO ingested_logs(kind,callsign,source_path,content_sha256,observed_at_utc,payload_json) VALUES (?,?,?,?,?,?)",
            (
                str(payload.get("kind") or payload.get("schema") or "unknown"),
                (uploader_callsign or "").strip().upper() or None,
                source_path,
                sha,
                _utcnow_iso(),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    except sqlite3.IntegrityError:
        return (False, "duplicate")

    # Update uploader station info (grid is authoritative for that station).
    if uploader_callsign:
        upsert_station(conn, callsign=uploader_callsign, grid=uploader_grid)

    # Optional station grid hints inside the payload (useful for sample data and
    # for remote ingestion where the uploader isn't the same as station_callsign).
    station_grid = (str(payload.get("station_grid") or "").strip().upper() or None)
    listener_grid = (str(payload.get("listener_grid") or "").strip().upper() or None)

    # TX report
    if payload.get("kind") == "ceefax_tx_report" and payload.get("tx_id") and payload.get("station_callsign"):
        tx_id = str(payload.get("tx_id"))
        tx_cs = str(payload.get("station_callsign")).strip().upper()
        gen = _parse_iso(str(payload.get("generated_at") or "")) or datetime.now(timezone.utc)
        gen_iso = gen.isoformat().replace("+00:00", "Z")
        tx_freq = (str(payload.get("frequency") or payload.get("freq") or "").strip() or None)

        upsert_station(
            conn,
            callsign=tx_cs,
            grid=(
                station_grid
                or (uploader_grid if tx_cs == (uploader_callsign or "").strip().upper() else None)
            ),
        )

        pages = payload.get("page_ids") or []
        if isinstance(pages, list):
            for pid in pages:
                page_id = str(pid).strip()
                if not page_id:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO transmissions(tx_id, tx_callsign, generated_at_utc, page_id, freq) VALUES (?,?,?,?,?)",
                    (tx_id, tx_cs, gen_iso, page_id, tx_freq),
                )
        conn.commit()
        return (True, "tx_ingested")

    # RX report (schema 1, has pages_decoded + listener_callsign)
    if payload.get("schema") == 1 and payload.get("listener_callsign") and payload.get("pages_decoded"):
        rx_cs = str(payload.get("listener_callsign")).strip().upper()
        tx_cs = str(payload.get("station_callsign") or "").strip().upper() or None
        started = _parse_iso(str(payload.get("started_at") or "")) or _parse_iso(str(payload.get("updated_at") or "")) or datetime.now(timezone.utc)
        rx_freq = (str(payload.get("frequency") or payload.get("freq") or "").strip() or None)
        rx_db_top = payload.get("rx_db")
        try:
            rx_db_top_f = float(rx_db_top) if rx_db_top is not None else None
        except Exception:  # noqa: BLE001
            rx_db_top_f = None

        upsert_station(
            conn,
            callsign=rx_cs,
            grid=(
                listener_grid
                or (uploader_grid if rx_cs == (uploader_callsign or "").strip().upper() else None)
            ),
        )
        if tx_cs:
            upsert_station(conn, callsign=tx_cs, grid=station_grid)

        pages_decoded = payload.get("pages_decoded") or {}
        if isinstance(pages_decoded, dict):
            for k, v in pages_decoded.items():
                if not isinstance(v, dict):
                    continue
                tx_id = str(v.get("tx_id") or "")
                page = str(v.get("page") or "").strip()
                sub = v.get("subpage")
                if page and isinstance(sub, int) and sub != 1:
                    page_id = f"{page}.{sub}"
                else:
                    page_id = page
                if not tx_id or not page_id:
                    continue
                # Best-effort per-page timestamp (started_at + first_complete_rx_s)
                rx_at = started
                try:
                    s = v.get("first_complete_rx_s")
                    if s is not None:
                        rx_at = started + timedelta(seconds=float(s))
                except Exception:  # noqa: BLE001
                    rx_at = started
                rx_at_iso = rx_at.isoformat().replace("+00:00", "Z")

                # Best-effort per-page dB reading and frequency
                try:
                    rx_db = float(v.get("rx_db")) if v.get("rx_db") is not None else rx_db_top_f
                except Exception:  # noqa: BLE001
                    rx_db = rx_db_top_f
                freq = (str(v.get("frequency") or "").strip() or None) or rx_freq
                conn.execute(
                    "INSERT OR REPLACE INTO receptions(rx_callsign, tx_callsign, tx_id, received_at_utc, page_id, freq, rx_db) VALUES (?,?,?,?,?,?,?)",
                    (rx_cs, tx_cs, tx_id, rx_at_iso, page_id, freq, rx_db),
                )
        conn.commit()
        return (True, "rx_ingested")

    conn.commit()
    return (True, "log_saved_no_derivation")


def _range_to_since(range_key: str) -> datetime:
    now = datetime.now(timezone.utc)
    rk = (range_key or "24h").lower().strip()
    if rk in ("24h", "1d", "day"):
        return now - timedelta(hours=24)
    if rk in ("7d", "week"):
        return now - timedelta(days=7)
    if rk in ("30d", "1m", "month"):
        return now - timedelta(days=30)
    return now - timedelta(hours=24)


def query_map(conn: sqlite3.Connection, *, range_key: str) -> dict[str, Any]:
    since = _range_to_since(range_key).isoformat().replace("+00:00", "Z")

    stations = [
        dict(r)
        for r in conn.execute(
            "SELECT callsign, grid, lat, lon, first_seen_utc, last_seen_utc FROM stations"
        ).fetchall()
    ]

    # Links: join RX to TX counts over time window.
    links = [
        dict(r)
        for r in conn.execute(
            """
            SELECT
              r.tx_callsign AS tx_callsign,
              r.rx_callsign AS rx_callsign,
              COUNT(*) AS rx_pages_ok,
              COUNT(DISTINCT r.page_id) AS rx_pages_ok_unique
            FROM receptions r
            WHERE r.received_at_utc >= ?
            GROUP BY r.tx_callsign, r.rx_callsign
            """,
            (since,),
        ).fetchall()
    ]

    # TX unique page set size per callsign (for completeness checks).
    tx_pages_unique = {
        r["tx_callsign"]: int(r["tx_pages_unique"])
        for r in conn.execute(
            """
            SELECT tx_callsign, COUNT(DISTINCT page_id) AS tx_pages_unique
            FROM transmissions
            WHERE generated_at_utc >= ?
            GROUP BY tx_callsign
            """,
            (since,),
        ).fetchall()
    }
    for l in links:
        tx_cs = (l.get("tx_callsign") or "")
        total_unique = int(tx_pages_unique.get(tx_cs, 0))
        ok_unique = int(l.get("rx_pages_ok_unique") or 0)
        l["tx_pages_unique"] = total_unique
        l["complete"] = bool(total_unique > 0 and ok_unique >= total_unique)

    # Station render metadata:
    # - bbox for grid (so UI can draw the grid square)
    # - status: "partial" if any inbound link is incomplete; otherwise "ok"
    inbound_partial: set[str] = set()
    for l in links:
        if not l.get("complete"):
            rx = (l.get("rx_callsign") or "").strip().upper()
            if rx:
                inbound_partial.add(rx)

    # RX activity per station: how many unique pages decoded in the window.
    rx_pages_unique = {
        r["rx_callsign"]: int(r["rx_pages_unique"])
        for r in conn.execute(
            """
            SELECT rx_callsign, COUNT(DISTINCT page_id) AS rx_pages_unique
            FROM receptions
            WHERE received_at_utc >= ?
            GROUP BY rx_callsign
            """,
            (since,),
        ).fetchall()
    }

    for s in stations:
        grid = (s.get("grid") or "").strip().upper()
        if grid:
            bb = maidenhead_bbox(grid)
            if bb:
                (sw, ne) = bb
                s["bbox"] = {"sw": {"lat": sw[0], "lon": sw[1]}, "ne": {"lat": ne[0], "lon": ne[1]}}
        cs = (s.get("callsign") or "").strip().upper()
        s["tx_pages_unique"] = int(tx_pages_unique.get(cs, 0))
        s["is_tx"] = bool(s["tx_pages_unique"] > 0)
        s["rx_pages_ok_unique"] = int(rx_pages_unique.get(cs, 0))
        s["is_rx"] = bool(s["rx_pages_ok_unique"] > 0)

        # Status rules:
        # - "none": receiver with no decoded pages in this window (and not a TX station)
        # - "partial": receiver has activity but some inbound link is incomplete
        # - "ok": everything else
        if (not s["is_tx"]) and (not s["is_rx"]):
            s["status"] = "none"
        else:
            s["status"] = "partial" if cs in inbound_partial else "ok"

    return {"range": range_key, "since_utc": since, "stations": stations, "links": links}


def query_link_detail(conn: sqlite3.Connection, *, tx: str, rx: str, range_key: str) -> dict[str, Any]:
    since = _range_to_since(range_key).isoformat().replace("+00:00", "Z")
    tx_cs = (tx or "").strip().upper()
    rx_cs = (rx or "").strip().upper()

    sent_rows = conn.execute(
        """
        SELECT
          t.page_id AS page_id,
          MAX(t.generated_at_utc) AS tx_at_utc,
          MAX(t.freq) AS tx_freq
        FROM transmissions t
        WHERE t.tx_callsign = ? AND t.generated_at_utc >= ?
        GROUP BY t.page_id
        ORDER BY t.page_id
        """,
        (tx_cs, since),
    ).fetchall()

    rx_rows = conn.execute(
        """
        SELECT
          r.page_id AS page_id,
          MAX(r.received_at_utc) AS rx_at_utc,
          MAX(r.freq) AS rx_freq,
          MAX(r.rx_db) AS rx_db
        FROM receptions r
        WHERE r.tx_callsign = ? AND r.rx_callsign = ? AND r.received_at_utc >= ?
        GROUP BY r.page_id
        """,
        (tx_cs, rx_cs, since),
    ).fetchall()

    rx_by_page = {r["page_id"]: dict(r) for r in rx_rows}

    now = datetime.now(timezone.utc)
    table_rows: list[dict[str, Any]] = []
    sent: list[str] = []
    ok: list[str] = []

    for r in sent_rows:
        page_id = r["page_id"]
        sent.append(page_id)
        rxr = rx_by_page.get(page_id)
        rx_ok = bool(rxr and rxr.get("rx_at_utc"))
        if rx_ok:
            ok.append(page_id)

        tx_at = r["tx_at_utc"]
        rx_at = (rxr or {}).get("rx_at_utc")
        # Age relative to most recent rx_at, else tx_at.
        age_base = _parse_iso(rx_at) or _parse_iso(tx_at) or now
        age_s = max(0.0, (now - age_base).total_seconds())

        table_rows.append(
            {
                "page_id": page_id,
                "tx": True,
                "rx_ok": rx_ok,
                "tx_at_utc": tx_at,
                "rx_at_utc": rx_at,
                "frequency": (rxr or {}).get("rx_freq") or r["tx_freq"],
                "rx_db": (rxr or {}).get("rx_db"),
                "age_s": age_s,
            }
        )

    # Distance and grid squares (best-effort): use stored lat/lon/grid from stations table.
    distance_km: float | None = None
    distance_mi: float | None = None
    tx_grid: str | None = None
    rx_grid: str | None = None
    try:
        tx_station = conn.execute(
            "SELECT lat, lon, grid FROM stations WHERE callsign = ?",
            (tx_cs,),
        ).fetchone()
        rx_station = conn.execute(
            "SELECT lat, lon, grid FROM stations WHERE callsign = ?",
            (rx_cs,),
        ).fetchone()
        if tx_station:
            tx_grid = tx_station.get("grid") or None
        if rx_station:
            rx_grid = rx_station.get("grid") or None
        if tx_station and rx_station and tx_station["lat"] is not None and tx_station["lon"] is not None and rx_station["lat"] is not None and rx_station["lon"] is not None:
            distance_km = float(haversine_km(float(tx_station["lat"]), float(tx_station["lon"]), float(rx_station["lat"]), float(rx_station["lon"])))
            distance_mi = float(distance_km * 0.621371)
    except Exception:  # noqa: BLE001
        distance_km = None
        distance_mi = None

    return {
        "range": range_key,
        "since_utc": since,
        "tx_callsign": tx_cs,
        "rx_callsign": rx_cs,
        "tx_grid": tx_grid,
        "rx_grid": rx_grid,
        "distance_km": distance_km,
        "distance_mi": distance_mi,
        "pages_sent": sent,
        "pages_rx_ok": ok,
        "rows": table_rows,
    }


