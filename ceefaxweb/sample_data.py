from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_sample(
    *,
    tx_callsign: str,
    tx_grid: str,
    rx_callsign: str,
    rx_grid: str,
    generated_at: datetime,
    pages: list[str],
    rx_ok_pages: list[str],
    tx_frequency: str | None = None,
    rx_frequency: str | None = None,
    rx_db: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tx_id = str(uuid.uuid4())
    tx = {
        "schema": 1,
        "kind": "ceefax_tx_report",
        "tx_id": tx_id,
        "station_callsign": tx_callsign,
        "station_grid": tx_grid,
        "dest_callsign": "CEEFAX",
        "frequency": tx_frequency,
        "wav_name": f"sample_{tx_callsign}_{generated_at.strftime('%Y%m%d_%H%M%S')}.wav",
        "generated_at": generated_at.isoformat(),
        "loops": 1,
        "page_ids": pages,
        "page_count": len(pages),
        "fragments_total": 0,
        "ui_frames_total": 0,
    }

    pages_decoded: dict[str, Any] = {}
    for pid in rx_ok_pages:
        if "." in pid:
            page, sub = pid.split(".", 1)
            try:
                sub_i = int(sub)
            except ValueError:
                sub_i = 1
        else:
            page, sub_i = pid, 1
        page_db = rx_db
        if page_db is not None:
            page_db = page_db + random.uniform(-2.0, 2.0)
        pages_decoded[f"{tx_id}:{pid}"] = {
            "tx_id": tx_id,
            "page": page,
            "subpage": sub_i,
            "title": "Sample",
            "first_complete_rx_s": 1.0,
            "rx_db": page_db,
            "frequency": rx_frequency,
        }

    rx = {
        "schema": 1,
        "listener_callsign": rx_callsign,
        "listener_grid": rx_grid,
        "dest_filter": "CEEFAX",
        "started_at": _iso(generated_at + timedelta(minutes=1)),
        "station_callsign": tx_callsign,
        "station_grid": tx_grid,
        "tx_id": tx_id,
        "tx_ids_seen": [tx_id],
        "cfx_frames": 0,
        "stations_heard": {tx_callsign: 1},
        "pages_decoded": pages_decoded,
        "decoded_page_count": len(rx_ok_pages),
        "pages_seen_count": len(pages),
        "partial_page_count": max(0, len(pages) - len(rx_ok_pages)),
        "complete_by_progress_count": len(rx_ok_pages),
        "frequency": rx_frequency,
        "rx_db": rx_db,
        "updated_at": _iso(generated_at + timedelta(minutes=2)),
    }

    return (tx, rx)


def _ingest(server: str, token: str, *, callsign: str, grid: str, source: str, payload: dict[str, Any]) -> None:
    body = {
        "token": token,
        "uploader": {"callsign": callsign, "grid": grid},
        "source_path": source,
        "log": payload,
    }
    r = requests.post(server.rstrip("/") + "/api/ingest/log", json=body, timeout=20)
    r.raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate sample Ceefaxstation TX/RX logs and optionally ingest into ceefaxweb server.")
    ap.add_argument("--write", action="store_true", help="Write sample logs into ceefax/logs_tx and ceefax/logs_rx.")
    ap.add_argument("--ingest", default=None, help="Server base URL to ingest into, e.g. http://127.0.0.1:8088")
    ap.add_argument("--token", default="", help="Upload token (if server enforces).")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)

    # Mock UK Ceefax network (distinct from the previous M7TJF/G4ABC set).
    # 3 TX stations on different bands, several RX stations, mixed link quality.
    freq_40m = "7.040 MHz (40m)"
    freq_20m = "14.105 MHz (20m)"
    freq_2m = "144.800 MHz (2m)"
    freq_70cm = "433.500 MHz (70cm)"

    # (tx_callsign, tx_grid, rx_callsign, rx_grid, tx_freq, rx_freq, rx_db, hours_ago)
    samples = [
        # GW0CEF (Wales) on 40m — longer-haul HF links
        ("GW0CEF", "IO81JM", "G1RXA", "IO91OJ", freq_40m, freq_40m, -9.4, 2),
        ("GW0CEF", "IO81JM", "MM0SCO", "IO85JV", freq_40m, freq_40m, -18.6, 3),
        ("GW0CEF", "IO81JM", "GI0NIR", "IO64UJ", freq_40m, freq_40m, -21.2, 5),
        ("GW0CEF", "IO81JM", "GD0MAN", "IO74QD", freq_40m, freq_40m, -16.8, 4),

        # MM0FAX (Scotland) on 20m
        ("MM0FAX", "IO85FP", "G1RXA", "IO91OJ", freq_20m, freq_20m, -14.1, 1),
        ("MM0FAX", "IO85FP", "2E0LNK", "JO02AB", freq_20m, freq_20m, -17.5, 6),
        ("MM0FAX", "IO85FP", "M0RCV", "IO83QE", freq_20m, freq_20m, -12.0, 2),

        # G0PKT (SE England) on 2m / 70cm local VHF-UHF
        ("G0PKT", "JO01CE", "2E0LNK", "JO02AB", freq_2m, freq_2m, -7.8, 1),
        ("G0PKT", "JO01CE", "G7HEAR", "IO92XA", freq_2m, freq_2m, -11.6, 3),
        ("G0PKT", "JO01CE", "G1RXA", "IO91OJ", freq_70cm, freq_70cm, -22.4, 7),
        ("G0PKT", "JO01CE", "M0RCV", "IO83QE", freq_2m, freq_2m, -19.9, 8),
    ]

    # Listening-only stations (heard nothing yet in this window)
    listening_only = [
        ("G8IDLE", "IO93FB", freq_20m, 40),
        ("M7WAIT", "IO82PL", freq_40m, 55),
        ("2E1QUIET", "JO00AA", freq_70cm, 25),
    ]

    pages = ["101", "200", "301", "304", "402", "503", "503.2", "504", "600"]

    root = _repo_root()
    out_tx = root / "ceefax" / "logs_tx"
    out_rx = root / "ceefax" / "logs_rx"
    server = (args.ingest or "").rstrip("/") if args.ingest else None
    token = args.token or ""

    for i, (tx_cs, tx_grid, rx_cs, rx_grid, tx_freq, rx_freq, rx_db, hours_ago) in enumerate(samples):
        gen_at = now - timedelta(hours=hours_ago, minutes=i * 3)
        # Vary how many pages were decoded successfully.
        keep = max(3, len(pages) - (i % 5))
        rx_ok = pages[:keep]
        tx, rx = build_sample(
            tx_callsign=tx_cs,
            tx_grid=tx_grid,
            rx_callsign=rx_cs,
            rx_grid=rx_grid,
            generated_at=gen_at,
            pages=pages,
            rx_ok_pages=rx_ok,
            tx_frequency=tx_freq,
            rx_frequency=rx_freq,
            rx_db=rx_db,
        )

        if args.write:
            stamp = gen_at.strftime("%Y%m%d_%H%M%S")
            _write_json(out_tx / f"sample_tx_{tx_cs}_{rx_cs}_{stamp}.json", tx)
            _write_json(out_rx / f"sample_rx_{rx_cs}_from_{tx_cs}_{stamp}.json", rx)

        if server:
            _ingest(server, token, callsign=tx_cs, grid=tx_grid, source=f"sample:{tx_cs}:{rx_cs}:tx", payload=tx)
            _ingest(server, token, callsign=rx_cs, grid=rx_grid, source=f"sample:{tx_cs}:{rx_cs}:rx", payload=rx)

    for rx_cs, rx_grid, freq, minutes_ago in listening_only:
        gen_at = now - timedelta(minutes=minutes_ago)
        rx_listening = {
            "schema": 1,
            "listener_callsign": rx_cs,
            "listener_grid": rx_grid,
            "dest_filter": "CEEFAX",
            "rx_mode": "live",
            "started_at": _iso(gen_at),
            "updated_at": _iso(gen_at + timedelta(minutes=5)),
            "frequency": freq,
            "rx_db": -99.0,
            "station_callsign": None,
            "tx_id": None,
            "tx_ids_seen": [],
            "cfx_frames": 0,
            "stations_heard": {},
            "pages_decoded": {},
            "decoded_page_count": 0,
            "pages_seen_count": 0,
            "partial_page_count": 0,
            "complete_by_progress_count": 0,
        }

        if args.write:
            stamp = gen_at.strftime("%Y%m%d_%H%M%S")
            _write_json(out_rx / f"sample_rx_{rx_cs}_listening_{stamp}.json", rx_listening)

        if server:
            _ingest(
                server,
                token,
                callsign=rx_cs,
                grid=rx_grid,
                source=f"sample:{rx_cs}:listening",
                payload=rx_listening,
            )

    print("Sample data generated.")
    if args.write:
        print(f"Wrote logs to {out_tx} and {out_rx}")
    if server:
        print(f"Ingested into {server}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
