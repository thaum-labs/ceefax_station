"""Resolve writable Ceefax data paths (dev + PyInstaller installs)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_DIR_NAME = "Ceefax Station"


def install_root() -> Path:
    """Directory containing the installed EXE (may be read-only Program Files)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def _user_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".ceefax_station"


def _seed_file(src: Path, dest: Path) -> None:
    if dest.exists() or not src.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def ceefax_root() -> Path:
    """
    Return the writable `ceefax/` directory.

    Frozen installs cannot reliably write under Program Files. Runtime data
    (pages, config, cache, logs) lives under LocalAppData instead. On first
    run we seed config files from the install directory when present.
    """
    if getattr(sys, "frozen", False):
        target = _user_data_root() / "ceefax"
        target.mkdir(parents=True, exist_ok=True)
        install_ceefax = install_root() / "ceefax"
        _seed_file(install_ceefax / "config.toml", target / "config.toml")
        _seed_file(install_ceefax / "radio_config.json", target / "radio_config.json")
        return target
    return Path(__file__).resolve().parent.parent


def pages_dir() -> Path:
    path = ceefax_root() / "pages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """Preferred config.toml location (writable)."""
    root = ceefax_root()
    candidate = root / "config.toml"
    if candidate.exists():
        return candidate
    # Dev fallback: allow missing until created.
    return candidate


def repo_root() -> Path:
    """
    Logical app root.

    Frozen: writable user data root (parent of `ceefax/`).
    Dev: repository root.
    """
    if getattr(sys, "frozen", False):
        root = _user_data_root()
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(__file__).resolve().parent.parent.parent
