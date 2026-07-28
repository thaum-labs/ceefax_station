#!/usr/bin/env python3
"""
Delete all sample data from the database and optionally re-upload it.

This script identifies sample data by source_path containing "sample:".
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path to import ceefaxweb modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ceefaxweb.db import connect, default_db_path


def delete_sample_data(db_path: Path) -> dict[str, int]:
    """
    Delete all sample data from the database.
    
    Returns dict with counts of deleted records.
    """
    conn = connect(db_path)
    
    deleted_counts = {
        "ingested_logs": 0,
        "transmissions": 0,
        "receptions": 0,
        "stations": 0,
    }
    
    try:
        # Find all sample log IDs
        sample_logs = conn.execute(
            "SELECT id, payload_json FROM ingested_logs WHERE source_path LIKE 'sample:%'"
        ).fetchall()
        
        print(f"Found {len(sample_logs)} sample log entries")
        
        # Extract TX IDs and callsigns from sample logs
        import json
        tx_ids_to_delete = set()
        tx_callsigns = set()
        rx_callsigns = set()
        
        for row in sample_logs:
            try:
                payload = json.loads(row["payload_json"])
                # TX logs
                if payload.get("kind") == "ceefax_tx_report":
                    tx_id = payload.get("tx_id")
                    if tx_id:
                        tx_ids_to_delete.add(tx_id)
                    tx_cs = payload.get("station_callsign")
                    if tx_cs:
                        tx_callsigns.add(tx_cs.strip().upper())
                # RX logs
                if payload.get("schema") == 1:
                    rx_cs = payload.get("listener_callsign")
                    if rx_cs:
                        rx_callsigns.add(rx_cs.strip().upper())
                    tx_cs = payload.get("station_callsign")
                    if tx_cs:
                        tx_callsigns.add(tx_cs.strip().upper())
            except Exception:
                pass
        
        print(f"Found {len(tx_ids_to_delete)} unique TX IDs")
        print(f"Found {len(tx_callsigns)} TX callsigns: {', '.join(sorted(tx_callsigns))}")
        print(f"Found {len(rx_callsigns)} RX callsigns: {', '.join(sorted(rx_callsigns))}")
        
        # Delete receptions for these TX IDs
        if tx_ids_to_delete:
            placeholders = ",".join("?" * len(tx_ids_to_delete))
            cursor = conn.execute(
                f"DELETE FROM receptions WHERE tx_id IN ({placeholders})",
                list(tx_ids_to_delete)
            )
            deleted_counts["receptions"] = cursor.rowcount
            print(f"Deleted {deleted_counts['receptions']} receptions")
        
        # Delete transmissions for these TX IDs
        if tx_ids_to_delete:
            placeholders = ",".join("?" * len(tx_ids_to_delete))
            cursor = conn.execute(
                f"DELETE FROM transmissions WHERE tx_id IN ({placeholders})",
                list(tx_ids_to_delete)
            )
            deleted_counts["transmissions"] = cursor.rowcount
            print(f"Deleted {deleted_counts['transmissions']} transmissions")
        
        # Delete ingested_logs
        cursor = conn.execute(
            "DELETE FROM ingested_logs WHERE source_path LIKE 'sample:%'"
        )
        deleted_counts["ingested_logs"] = cursor.rowcount
        print(f"Deleted {deleted_counts['ingested_logs']} ingested logs")
        
        # Delete stations that are only sample stations (if they have no other data)
        all_sample_callsigns = tx_callsigns | rx_callsigns
        for callsign in all_sample_callsigns:
            # Check if this callsign has any remaining transmissions or receptions
            tx_count = conn.execute(
                "SELECT COUNT(*) FROM transmissions WHERE tx_callsign = ?",
                (callsign,)
            ).fetchone()[0]
            rx_count = conn.execute(
                "SELECT COUNT(*) FROM receptions WHERE rx_callsign = ? OR tx_callsign = ?",
                (callsign, callsign)
            ).fetchone()[0]
            
            if tx_count == 0 and rx_count == 0:
                cursor = conn.execute(
                    "DELETE FROM stations WHERE callsign = ?",
                    (callsign,)
                )
                if cursor.rowcount > 0:
                    deleted_counts["stations"] += cursor.rowcount
                    print(f"Deleted station: {callsign}")
        
        conn.commit()
        print("\nSample data deletion complete!")
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        conn.close()
    
    return deleted_counts


def main() -> int:
    import argparse
    import os
    
    ap = argparse.ArgumentParser(description="Delete all sample data from the database")
    ap.add_argument(
        "--db",
        help="Path to database file (default: CEEFAXWEB_DB or ceefax/cache/ceefaxweb.sqlite3)",
    )
    ap.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")
    args = ap.parse_args()
    
    root = Path(__file__).resolve().parent.parent.parent
    if args.db:
        db_path = Path(args.db).expanduser()
    elif os.environ.get("CEEFAXWEB_DB"):
        db_path = Path(os.environ["CEEFAXWEB_DB"]).expanduser()
    else:
        db_path = default_db_path(root)
    
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        return 1
    
    print(f"Database: {db_path}")
    
    if not args.confirm:
        response = input("\nDelete all sample data? This cannot be undone. (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            return 0
    
    print()
    counts = delete_sample_data(db_path)
    
    print()
    print("Summary:")
    print(f"  Ingested logs deleted: {counts['ingested_logs']}")
    print(f"  Transmissions deleted: {counts['transmissions']}")
    print(f"  Receptions deleted: {counts['receptions']}")
    print(f"  Stations deleted: {counts['stations']}")
    print(f"  Total records deleted: {sum(counts.values())}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

