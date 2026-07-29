"""Resolve the newest Windows installer under installers/."""

from __future__ import annotations

import re
from pathlib import Path


_SETUP_RE = re.compile(
    r"^CeefaxStation-Setup-(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?\.exe$",
    re.IGNORECASE,
)


def installer_version_key(path: Path) -> tuple[int, int, int, str] | None:
    match = _SETUP_RE.match(path.name)
    if not match:
        return None
    major, minor, patch = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    # Empty prerelease sorts after named prerelease for same x.y.z (prefer final).
    pre = match.group(4) or ""
    return (major, minor, patch, "" if not pre else pre)


def latest_installer(installers_dir: Path) -> Path | None:
    """
    Return the highest-versioned CeefaxStation-Setup-*.exe in installers_dir.

    Prefers a stable alias CeefaxStation-Setup.exe only when no versioned files exist.
    """
    if not installers_dir.is_dir():
        return None

    versioned: list[tuple[tuple[int, int, int, str], Path]] = []
    for path in installers_dir.glob("CeefaxStation-Setup-*.exe"):
        key = installer_version_key(path)
        if key is None:
            continue
        versioned.append((key, path))

    if versioned:
        # Highest x.y.z wins; for the same x.y.z prefer a build without prerelease suffix.
        versioned.sort(
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                1 if item[0][3] == "" else 0,
                item[0][3],
            )
        )
        return versioned[-1][1]

    alias = installers_dir / "CeefaxStation-Setup.exe"
    return alias if alias.is_file() else None
