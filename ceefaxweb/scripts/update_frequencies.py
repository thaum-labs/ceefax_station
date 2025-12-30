#!/usr/bin/env python3
"""
Update frequency values in the database from range format to specific frequency format.

Converts:
- "2m (144.0-148.0 MHz)" -> "144.800 MHz (2m)"
- "10m (28.0-29.7 MHz)" -> "28.120 MHz (10m)"
- etc.

This script updates both transmissions and receptions tables.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add parent directory to path to import ceefaxweb modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ceefaxweb.db import connect, default_db_path


# Mapping from old range format to new specific frequency format
# Include case variations and spacing differences
FREQ_MAPPING = {
    # 2m variations
    "2m (144.0-148.0 MHz)": "144.800 MHz (2m)",
    "2M (144.0-148.0 MHz)": "144.800 MHz (2m)",
    "2m(144.0-148.0 MHz)": "144.800 MHz (2m)",
    "2m (144.0-148.0MHz)": "144.800 MHz (2m)",
    "2m(144.0-148.0MHz)": "144.800 MHz (2m)",
    # 10m variations
    "10m (28.0-29.7 MHz)": "28.120 MHz (10m)",
    "10M (28.0-29.7 MHz)": "28.120 MHz (10m)",
    "10m(28.0-29.7 MHz)": "28.120 MHz (10m)",
    # 6m
    "6m (50.0-54.0 MHz)": "50.200 MHz (6m)",
    # 70cm
    "70cm (430.0-440.0 MHz)": "433.500 MHz (70cm)",
    # 20m
    "20m (14.0-14.35 MHz)": "14.105 MHz (20m)",
    # 40m
    "40m (7.0-7.2 MHz)": "7.040 MHz (40m)",
    # 30m
    "30m (10.1-10.15 MHz)": "10.147 MHz (30m)",
    # 17m
    "17m (18.068-18.168 MHz)": "18.105 MHz (17m)",
    # 15m
    "15m (21.0-21.45 MHz)": "21.105 MHz (15m)",
    # 12m
    "12m (24.89-24.99 MHz)": "24.930 MHz (12m)",
    # 80m
    "80m (3.5-3.8 MHz)": "3.580 MHz (80m)",
}


def update_frequencies(conn, dry_run: bool = False) -> dict[str, int]:
    """
    Update frequency values in transmissions and receptions tables.
    
    Args:
        conn: SQLite connection (from ceefaxweb.db.connect)
        dry_run: If True, only show what would be updated
    
    Returns dict with counts of updated records.
    """
    
    updated_counts = {
        "transmissions": 0,
        "receptions": 0,
    }
    
    # First, show what 2m frequencies actually exist in the database
    print("Checking for 2m frequency patterns in database...")
    tx_2m = conn.execute(
        "SELECT DISTINCT freq FROM transmissions WHERE freq LIKE '%2m%' OR freq LIKE '%144%' ORDER BY freq"
    ).fetchall()
    rx_2m = conn.execute(
        "SELECT DISTINCT freq FROM receptions WHERE freq LIKE '%2m%' OR freq LIKE '%144%' ORDER BY freq"
    ).fetchall()
    
    if tx_2m or rx_2m:
        print("Found 2m-related frequencies:")
        for row in set(tx_2m + rx_2m):
            freq = row[0] if isinstance(row, tuple) else row["freq"]
            if freq:
                print(f"  '{freq}'")
    print()
    
    # Update transmissions table
    for old_freq, new_freq in FREQ_MAPPING.items():
        if dry_run:
            count = conn.execute(
                "SELECT COUNT(*) FROM transmissions WHERE freq = ?",
                (old_freq,)
            ).fetchone()[0]
            if count > 0:
                print(f"Would update {count} transmissions: {old_freq} -> {new_freq}")
            updated_counts["transmissions"] += count
        else:
            cursor = conn.execute(
                "UPDATE transmissions SET freq = ? WHERE freq = ?",
                (new_freq, old_freq)
            )
            count = cursor.rowcount
            if count > 0:
                print(f"Updated {count} transmissions: {old_freq} -> {new_freq}")
            updated_counts["transmissions"] += count
    
    # Update receptions table
    for old_freq, new_freq in FREQ_MAPPING.items():
        if dry_run:
            count = conn.execute(
                "SELECT COUNT(*) FROM receptions WHERE freq = ?",
                (old_freq,)
            ).fetchone()[0]
            if count > 0:
                print(f"Would update {count} receptions: {old_freq} -> {new_freq}")
            updated_counts["receptions"] += count
        else:
            cursor = conn.execute(
                "UPDATE receptions SET freq = ? WHERE freq = ?",
                (new_freq, old_freq)
            )
            count = cursor.rowcount
            if count > 0:
                print(f"Updated {count} receptions: {old_freq} -> {new_freq}")
            updated_counts["receptions"] += count
    
    if not dry_run:
        conn.commit()
    
    return updated_counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Update frequency values in database from range format to specific frequencies")
    ap.add_argument("--db", help="Path to database file (default: ceefax/cache/ceefaxweb.sqlite3)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be updated without making changes")
    args = ap.parse_args()
    
    root = Path(__file__).resolve().parent.parent.parent
    if args.db:
        db_path = Path(args.db)
    else:
        db_path = default_db_path(root)
    
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        return 1
    
    print(f"Database: {db_path}")
    if args.dry_run:
        print("DRY RUN - No changes will be made")
    print()
    
    conn = connect(db_path)
    try:
        counts = update_frequencies(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    
    print()
    print(f"Summary:")
    print(f"  Transmissions updated: {counts['transmissions']}")
    print(f"  Receptions updated: {counts['receptions']}")
    print(f"  Total: {counts['transmissions'] + counts['receptions']}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

