"""
Update page 900 with About Ceefax Station information.
"""
from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .page_pack import format_hub_pack_stamp, load_station_hub_manifest
from .paths import pages_dir, repo_root
from .providers import atomic_write_json


def _pad(text: str) -> str:
    txt = text[:PAGE_WIDTH]
    return txt.ljust(PAGE_WIDTH)


def detect_platform() -> str:
    """Detect the operating system/platform."""
    system = platform.system()
    machine = platform.machine()

    if system == "Windows":
        return "Windows"
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
                cpuinfo = handle.read()
                if "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo:
                    return "Raspberry Pi"
        except (FileNotFoundError, PermissionError):
            pass
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as handle:
                os_release = handle.read()
                if "Raspbian" in os_release or "Raspberry Pi OS" in os_release:
                    return "Raspberry Pi"
                if "Ubuntu" in os_release:
                    return "Linux (Ubuntu)"
                if "Debian" in os_release:
                    return "Linux (Debian)"
                if "Fedora" in os_release:
                    return "Linux (Fedora)"
                if "Arch" in os_release:
                    return "Linux (Arch)"
        except (FileNotFoundError, PermissionError):
            pass
        return "Linux"
    if system == "Darwin":
        return "Mac"
    return f"{system} ({machine})"


def get_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def get_app_version() -> str:
    """
    Installed app version from VERSION.

    Frozen builds prefer the file next to the EXE (updated by the installer).
    Writable LocalAppData is only a fallback so a stale user copy cannot hide upgrades.
    """
    try:
        from .paths import install_root, uses_user_data

        candidates: list[Path] = []
        if uses_user_data():
            # Prefer installer-deployed VERSION beside the EXE / package root.
            candidates.append(install_root() / "VERSION")
            # One-file PyInstaller also ships VERSION inside the extract dir.
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass) / "VERSION")
        candidates.append(repo_root() / "VERSION")
        for version_file in candidates:
            if version_file.exists():
                text = version_file.read_text(encoding="utf-8").strip()
                if text:
                    return text
    except OSError:
        pass
    return "0.1.1-alpha"


def build_about_page() -> List[str]:
    """Build the About page with project and system information."""
    platform_name = detect_platform()
    python_version = get_python_version()
    version = get_app_version()
    pack_stamp = format_hub_pack_stamp(load_station_hub_manifest())
    sep = "-" * PAGE_WIDTH

    lines = [
        "ABOUT CEEFAX STATION",
        "",
        "Classic BBC Ceefax teletext style on your PC,",
        "plus optional AX.25 packet radio TX / RX.",
        "",
        "SYSTEM",
        sep,
        f"Version: {version}",
        f"Platform: {platform_name}",
        f"Python: {python_version}",
        "",
        "PAGES FROM",
        sep,
        "Hub pack: ceefaxstation.com",
        f"Pack time: {pack_stamp}",
        "Local: 000, 102, 700, 900",
        "",
        "TRY",
        sep,
        "000 Start  100 Index  101 Weather",
        "200 News   300 Sport  900 About",
        "n/p browse   t TX   r RX   Esc quit",
        "Created by M7TJF",
    ]
    return [_pad(line) for line in lines[:PAGE_HEIGHT]]


def main() -> None:
    """Update page 900 with About Ceefax Station."""
    page_file = pages_dir() / "900.json"
    page = {
        "page": "900",
        "title": "About Ceefax Station",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "subpage": 1,
        "content": build_about_page(),
    }
    atomic_write_json(page_file, page)
    print(f"Updated {page_file} with About page ({detect_platform()})")


if __name__ == "__main__":
    main()
