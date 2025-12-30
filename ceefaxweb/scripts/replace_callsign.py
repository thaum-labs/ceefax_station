#!/usr/bin/env python3
"""
Replace a callsign in the database with an anonymous one.
Usage: python -m ceefaxweb.scripts.replace_callsign OLD_CALLSIGN NEW_CALLSIGN
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path to import ceefaxweb modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ceefaxweb.db import connect, default_db_path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def replace_callsign(old_callsign: str, new_callsign: str) -> None:
    """Replace all occurrences of old_callsign with new_callsign in the database."""
    old_cs = old_callsign.strip().upper()
    new_cs = new_callsign.strip().upper()
    
    if not old_cs or not new_cs:
        print("Error: Both callsigns must be non-empty")
        return
    
    if old_cs == new_cs:
        print("Error: Old and new callsigns are the same")
        return
    
    # Connect to database
    repo_root = _repo_root()
    db_path = default_db_path(repo_root)
    
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return
    
    conn = connect(db_path)
    
    try:
        # Check if old callsign exists
        old_station = conn.execute("SELECT * FROM stations WHERE callsign = ?", (old_cs,)).fetchone()
        if not old_station:
            print(f"Warning: Callsign {old_cs} not found in stations table")
        else:
            print(f"Found station: {old_cs} ({old_station['grid']})")
        
        # Count occurrences in each table
        tx_count = conn.execute("SELECT COUNT(*) FROM transmissions WHERE tx_callsign = ?", (old_cs,)).fetchone()[0]
        rx_count = conn.execute("SELECT COUNT(*) FROM receptions WHERE rx_callsign = ? OR tx_callsign = ?", (old_cs, old_cs)).fetchone()[0]
        log_count = conn.execute("SELECT COUNT(*) FROM ingested_logs WHERE callsign = ?", (old_cs,)).fetchone()[0]
        
        print(f"\nFound {tx_count} transmissions, {rx_count} receptions, {log_count} logs")
        
        if tx_count == 0 and rx_count == 0 and log_count == 0 and not old_station:
            print("No data to replace. Exiting.")
            return
        
        # Confirm
        response = input(f"\nReplace {old_cs} with {new_cs}? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled.")
            return
        
        # Update stations table
        if old_station:
            # Check if new callsign already exists
            existing = conn.execute("SELECT * FROM stations WHERE callsign = ?", (new_cs,)).fetchone()
            if existing:
                print(f"Warning: {new_cs} already exists. Merging data...")
                # Merge: keep earliest first_seen, latest last_seen, prefer non-null grid
                first_seen = min(old_station['first_seen_utc'] or '', existing['first_seen_utc'] or '') or existing['first_seen_utc'] or old_station['first_seen_utc']
                last_seen = max(old_station['last_seen_utc'] or '', existing['last_seen_utc'] or '') or existing['last_seen_utc'] or old_station['last_seen_utc']
                grid = existing['grid'] or old_station['grid']
                lat = existing['lat'] or old_station['lat']
                lon = existing['lon'] or old_station['lon']
                conn.execute(
                    "UPDATE stations SET grid=?, lat=?, lon=?, first_seen_utc=?, last_seen_utc=? WHERE callsign=?",
                    (grid, lat, lon, first_seen, last_seen, new_cs)
                )
                conn.execute("DELETE FROM stations WHERE callsign = ?", (old_cs,))
            else:
                conn.execute("UPDATE stations SET callsign = ? WHERE callsign = ?", (new_cs, old_cs))
            print(f"Updated stations table")
        
        # Update transmissions table
        if tx_count > 0:
            conn.execute("UPDATE transmissions SET tx_callsign = ? WHERE tx_callsign = ?", (new_cs, old_cs))
            print(f"Updated {tx_count} transmissions")
        
        # Update receptions table
        if rx_count > 0:
            conn.execute("UPDATE receptions SET rx_callsign = ? WHERE rx_callsign = ?", (new_cs, old_cs))
            conn.execute("UPDATE receptions SET tx_callsign = ? WHERE tx_callsign = ?", (new_cs, old_cs))
            print(f"Updated {rx_count} receptions")
        
        # Update ingested_logs table (callsign field)
        if log_count > 0:
            conn.execute("UPDATE ingested_logs SET callsign = ? WHERE callsign = ?", (new_cs, old_cs))
            print(f"Updated {log_count} ingested logs")
        
        # Also update JSON payloads in ingested_logs (more complex)
        logs_with_payload = conn.execute("SELECT id, payload_json FROM ingested_logs WHERE payload_json LIKE ?", (f'%{old_cs}%',)).fetchall()
        if logs_with_payload:
            import json
            updated_payloads = 0
            for row in logs_with_payload:
                try:
                    payload = json.loads(row['payload_json'])
                    # Replace in various fields
                    changed = False
                    if payload.get('station_callsign') == old_cs:
                        payload['station_callsign'] = new_cs
                        changed = True
                    if payload.get('listener_callsign') == old_cs:
                        payload['listener_callsign'] = new_cs
                        changed = True
                    if changed:
                        conn.execute(
                            "UPDATE ingested_logs SET payload_json = ? WHERE id = ?",
                            (json.dumps(payload, ensure_ascii=False), row['id'])
                        )
                        updated_payloads += 1
                except Exception:
                    pass
            if updated_payloads > 0:
                print(f"Updated {updated_payloads} log payloads")
        
        conn.commit()
        print(f"\nSuccessfully replaced {old_cs} with {new_cs}")
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m ceefaxweb.scripts.replace_callsign OLD_CALLSIGN NEW_CALLSIGN")
        sys.exit(1)
    
    replace_callsign(sys.argv[1], sys.argv[2])

