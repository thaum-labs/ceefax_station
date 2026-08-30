"""Resolve writable Ceefax data paths (dev, PyInstaller, and Debian installs)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_DIR_NAME = "Ceefax Station"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

DEFAULT_CONFIG_TOML = """[general]
mode = "ax25_audio"
page_dir = "pages"
log_level = "INFO"
output_dir = "out"

[audio]
sample_rate = 48000
symbol_rate = 1200
frequency_mark = 1200.0
frequency_space = 2200.0
amplitude = 0.5
pre_tone_ms = 300
post_tone_ms = 300
vox_hold_ms = 250
output = "files"

[ax25]
enabled = true
callsign = "N0CALL-1"
kiss_port = "/dev/ttyUSB0"
baud_rate = 9600
dest_callsign = "CEEFAX"
max_info_bytes = 240
preamble_flags = 150
inter_frame_flags = 2
postamble_flags = 20
loops_per_hour = 3
refresh_lead_seconds = 180

[carousel]
page_duration_ms = 1500
loop_delay_ms = 200
"""

DEFAULT_RADIO_CONFIG_JSON = """{
  "callsign": "YOUR_CALLSIGN",
  "frequency": "2m (144.0-148.0 MHz)",
  "grid": "IO91WM"
}
"""


def install_root() -> Path:
    """Directory containing the installed EXE / package (may be read-only)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def is_packaged_install() -> bool:
    """
    True for Debian/system installs (code under /usr or /opt, or CEEFAX_PACKAGED=1).

    Dev checkouts keep using the repository tree so pages/config stay local.
    """
    flag = os.environ.get("CEEFAX_PACKAGED", "").strip().lower()
    if flag in _TRUE:
        return True
    if flag in _FALSE:
        return False
    posix = Path(__file__).resolve().as_posix()
    return posix.startswith("/usr/") or posix.startswith("/opt/")


def uses_user_data() -> bool:
    """True when runtime data must live outside the install/source tree."""
    return bool(getattr(sys, "frozen", False)) or is_packaged_install()


def _user_data_root() -> Path:
    override = os.environ.get("CEEFAX_DATA_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "ceefax-station"
    return Path.home() / ".ceefax_station"


def _seed_file(src: Path, dest: Path) -> None:
    if dest.exists() or not src.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _write_text_if_missing(dest: Path, text: str) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def seed_runtime_files(target: Path, *, install_ceefax: Path | None = None) -> None:
    """Copy default config into a writable ceefax/ directory on first run."""
    target.mkdir(parents=True, exist_ok=True)
    if install_ceefax is None:
        install_ceefax = install_root() / "ceefax"

    config_dest = target / "config.toml"
    radio_dest = target / "radio_config.json"

    _seed_file(install_ceefax / "config.toml", config_dest)
    _seed_file(install_ceefax / "config.default.toml", config_dest)
    _seed_file(install_ceefax / "radio_config.json", radio_dest)
    _seed_file(install_ceefax / "radio_config.default.json", radio_dest)

    _write_text_if_missing(config_dest, DEFAULT_CONFIG_TOML)
    _write_text_if_missing(radio_dest, DEFAULT_RADIO_CONFIG_JSON)


def ceefax_root() -> Path:
    """
    Return the writable `ceefax/` directory.

    Frozen and Debian installs cannot reliably write under Program Files / /usr.
    Runtime data (pages, config, cache, logs) lives under the user data root.
    On first run we seed config files from the install directory when present.
    """
    if uses_user_data():
        target = _user_data_root() / "ceefax"
        seed_runtime_files(target, install_ceefax=install_root() / "ceefax")
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

    Frozen / packaged: writable user data root (parent of `ceefax/`).
    Dev: repository root.
    """
    if uses_user_data():
        root = _user_data_root()
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(__file__).resolve().parent.parent.parent
