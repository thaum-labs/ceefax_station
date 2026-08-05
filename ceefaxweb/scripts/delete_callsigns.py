#!/usr/bin/env python3
"""
Delete all tracker rows for one or more callsigns.

Usage:
  python -m ceefaxweb.scripts.delete_callsigns G0CEF TEST1 --confirm
  python -m ceefaxweb.scripts.delete_callsigns G0CEF --keep M7TJF --confirm
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ceefaxweb.db import connect, default_db_path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_dotenv(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists() or os.environ.get("CEEFAXWEB_DB"):
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _resolve_db(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("CEEFAXWEB_DB"):
        return Path(os.environ["CEEFAXWEB_DB"]).expanduser()
    return default_db_path(_repo_root())


def delete_callsigns(db_path: Path, callsigns: list[str], *, keep: set[str]) -> dict[str, int]:
    targets = sorted({c.strip().upper() for c in callsigns if c.strip()})
    keep_u = {c.strip().upper() for c in keep if c.strip()}
    blocked = [c for c in targets if c in keep_u]
    if blocked:
        raise SystemExit(f"Refusing to delete keep-list callsign(s): {', '.join(blocked)}")
    if not targets:
        raise SystemExit("No callsigns to delete")

    conn = connect(db_path)
    deleted = {"stations": 0, "transmissions": 0, "receptions": 0, "ingested_logs": 0}
    try:
        for cs in targets:
            print(f"\n=== {cs} ===")
            cur = conn.execute("DELETE FROM receptions WHERE rx_callsign = ? OR tx_callsign = ?", (cs, cs))
            deleted["receptions"] += cur.rowcount
            print(f"  receptions: {cur.rowcount}")

            cur = conn.execute("DELETE FROM transmissions WHERE tx_callsign = ?", (cs,))
            deleted["transmissions"] += cur.rowcount
            print(f"  transmissions: {cur.rowcount}")

            # Uploader column plus payload text references (verify scripts, etc.)
            cur = conn.execute(
                "DELETE FROM ingested_logs WHERE callsign = ? OR payload_json LIKE ?",
                (cs, f"%{cs}%"),
            )
            deleted["ingested_logs"] += cur.rowcount
            print(f"  ingested_logs: {cur.rowcount}")

            cur = conn.execute("DELETE FROM stations WHERE callsign = ?", (cs,))
            deleted["stations"] += cur.rowcount
            print(f"  stations: {cur.rowcount}")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(description="Delete tracker rows for given callsigns")
    ap.add_argument("callsigns", nargs="+", help="Callsigns to delete")
    ap.add_argument("--db", help="SQLite path (default: CEEFAXWEB_DB)")
    ap.add_argument(
        "--keep",
        action="append",
        default=[],
        help="Callsign that must never be deleted (repeatable). Default includes M7TJF.",
    )
    ap.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")
    args = ap.parse_args()

    root = _repo_root()
    _load_dotenv(root)
    db_path = _resolve_db(args.db)
    keep = {"M7TJF", *(args.keep or [])}

    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        return 1

    targets = [c.strip().upper() for c in args.callsigns]
    print(f"Database: {db_path}")
    print(f"Delete: {', '.join(targets)}")
    print(f"Keep:   {', '.join(sorted(keep))}")

    if not args.confirm:
        response = input("\nDelete these callsigns permanently? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            return 0

    counts = delete_callsigns(db_path, targets, keep=keep)
    print("\nSummary:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"  total: {sum(counts.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
