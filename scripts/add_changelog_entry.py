#!/usr/bin/env python3
"""
Helper script to add changelog entries.

Usage:
    python scripts/add_changelog_entry.py "Added new feature" "Fixed bug" "Improved performance"

This will:
1. Read the current VERSION file
2. Add the changes to CHANGELOG.json for today's date
3. If an entry for today already exists, it will append to that entry
4. If a new version is needed, increment the version number
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def read_version(repo_root: Path) -> tuple[str, str]:
    """Read version from VERSION file. Returns (version, stage)."""
    version_path = repo_root / "VERSION"
    if not version_path.exists():
        return ("0.1.0-alpha", "alpha")
    
    version = version_path.read_text(encoding="utf-8").strip()
    if "-alpha" in version:
        stage = "alpha"
    elif "-beta" in version:
        stage = "beta"
    else:
        stage = "release"
    
    return (version, stage)


def increment_version(version: str, stage: str, increment_type: str = "patch") -> str:
    """
    Increment version number.
    
    increment_type: "patch", "minor", or "major"
    """
    # Remove stage suffix
    base_version = version.split("-")[0]
    parts = base_version.split(".")
    
    if len(parts) != 3:
        # Default to 0.1.0 if format is unexpected
        parts = ["0", "1", "0"]
    
    major, minor, patch = map(int, parts)
    
    if increment_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif increment_type == "minor":
        minor += 1
        patch = 0
    else:  # patch
        patch += 1
    
    new_version = f"{major}.{minor}.{patch}"
    if stage != "release":
        new_version += f"-{stage}"
    
    return new_version


def read_changelog(repo_root: Path) -> dict:
    """Read changelog from CHANGELOG.json."""
    changelog_path = repo_root / "CHANGELOG.json"
    if not changelog_path.exists():
        version, stage = read_version(repo_root)
        return {
            "current_version": version,
            "stage": stage,
            "entries": []
        }
    
    return json.loads(changelog_path.read_text(encoding="utf-8"))


def write_changelog(repo_root: Path, changelog: dict) -> None:
    """Write changelog to CHANGELOG.json."""
    changelog_path = repo_root / "CHANGELOG.json"
    changelog_path.write_text(
        json.dumps(changelog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )


def write_version(repo_root: Path, version: str) -> None:
    """Write version to VERSION file."""
    version_path = repo_root / "VERSION"
    version_path.write_text(version + "\n", encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/add_changelog_entry.py \"Change 1\" \"Change 2\" ...")
        print("\nOptions:")
        print("  --patch    Increment patch version (default)")
        print("  --minor    Increment minor version")
        print("  --major    Increment major version")
        print("  --no-bump  Don't increment version, just add to today's entry")
        sys.exit(1)
    
    repo_root = Path(__file__).resolve().parent.parent
    
    # Parse arguments
    changes = []
    increment_type = "patch"
    bump_version = True
    
    for arg in sys.argv[1:]:
        if arg == "--patch":
            increment_type = "patch"
        elif arg == "--minor":
            increment_type = "minor"
        elif arg == "--major":
            increment_type = "major"
        elif arg == "--no-bump":
            bump_version = False
        else:
            changes.append(arg)
    
    if not changes:
        print("Error: No changes provided")
        sys.exit(1)
    
    # Read current state
    version, stage = read_version(repo_root)
    changelog = read_changelog(repo_root)
    
    # Get today's date
    today = datetime.now().date().isoformat()
    
    # Check if entry for today exists
    today_entry = None
    for entry in changelog["entries"]:
        if entry["date"] == today:
            today_entry = entry
            break
    
    # If bumping version, increment it
    if bump_version:
        new_version = increment_version(version, stage, increment_type)
        version = new_version
        changelog["current_version"] = new_version
        changelog["stage"] = stage
        write_version(repo_root, version)
    
    # Add or update today's entry
    if today_entry:
        # Append to existing entry
        today_entry["changes"].extend(changes)
        if bump_version:
            today_entry["version"] = version
    else:
        # Create new entry
        changelog["entries"].append({
            "date": today,
            "version": version if bump_version else changelog.get("current_version", version),
            "changes": changes
        })
    
    # Write changelog
    write_changelog(repo_root, changelog)
    
    print(f"[OK] Added {len(changes)} change(s) to changelog for {today}")
    if bump_version:
        print(f"[OK] Version bumped to {version}")
    else:
        print(f"  (Version unchanged: {changelog['current_version']})")


if __name__ == "__main__":
    main()

