#!/usr/bin/env python3
"""
Build a Debian package for Ceefax Station.

Produces:
  installers/ceefax-station_<upstream>-1_all.deb
  installers/ceefax-station.deb   (stable alias)

Usage:
  python scripts/build_debian_package.py
  python scripts/build_debian_package.py --output-dir dist/debian
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
LICENSE_FILE = ROOT / "LICENSE"
PACKAGE_NAME = "ceefax-station"
MAINTAINER = "M7TJF <tobias.j.franklin@gmail.com>"
HOMEPAGE = "https://ceefaxstation.com"
LIBDIR = "usr/lib/ceefax-station"

SKIP_DIR_NAMES = {
    "__pycache__",
    ".venv",
    "venv",
    "cache",
    "logs_rx",
    "logs_tx",
    "pages",
    "out",
    ".pytest_cache",
}
SKIP_FILE_NAMES = {
    "config.toml",
    "radio_config.json",
    "activity_log.json",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".exe", ".wav", ".pdf", ".sqlite3"}


def read_version_label(repo_root: Path | None = None) -> str:
    path = (repo_root or ROOT) / "VERSION"
    if not path.is_file():
        raise SystemExit(f"Missing {path}")
    return path.read_text(encoding="utf-8").strip()


def debian_upstream_version(label: str) -> str:
    """
    Convert a project VERSION label into a Debian upstream version.

    0.1.5-alpha -> 0.1.5~alpha  (tilde so prereleases sort before the final)
    0.1.5       -> 0.1.5
    """
    raw = (label or "").strip()
    if not raw:
        raise ValueError("empty version label")
    if "-" in raw:
        numeric, suffix = raw.split("-", 1)
        suffix = suffix.strip().replace(" ", "")
        if not numeric or not suffix:
            raise ValueError(f"invalid version label: {label!r}")
        return f"{numeric}~{suffix}"
    return raw


def debian_package_version(label: str, *, revision: str = "1") -> str:
    return f"{debian_upstream_version(label)}-{revision}"


def versioned_deb_name(label: str, *, arch: str = "all") -> str:
    return f"{PACKAGE_NAME}_{debian_package_version(label)}_{arch}.deb"


def rfc2822_now() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _should_skip(path: Path, *, relative: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in relative.parts):
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def copy_python_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if _should_skip(item, relative=rel):
            continue
        target = dest / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def wrapper_script() -> str:
    return """#!/usr/bin/python3
import os
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent / "lib" / "ceefax-station")
os.environ["CEEFAX_PACKAGED"] = "1"
previous = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = ROOT + (os.pathsep + previous if previous else "")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ceefaxstation.__main__ import main

raise SystemExit(main())
"""


def desktop_entry() -> str:
    return """[Desktop Entry]
Type=Application
Name=Ceefax Station
Comment=Ceefax-style teletext viewer and amateur radio station
Exec=ceefaxstation
Icon=ceefax-station
Terminal=true
Categories=HamRadio;Network;Utility;
Keywords=ceefax;teletext;ham;ax25;packet;
StartupNotify=false
"""


def systemd_user_unit() -> str:
    return """[Unit]
Description=Ceefax Station hourly AX.25 audio
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ceefaxstation tx hourly --refresh-lead 300 --carousel-loops 3 --play --play-loops 1
Restart=on-failure
Environment=CEEFAX_PACKAGED=1

[Install]
WantedBy=default.target
"""


def man_page(label: str) -> str:
    return f""".TH CEEFAXSTATION 1 "{datetime.now(timezone.utc).strftime("%B %Y")}" "Ceefax Station {label}" "User Commands"
.SH NAME
ceefaxstation \\- Ceefax-style teletext viewer and amateur radio station
.SH SYNOPSIS
.B ceefaxstation
[\\fIcommand\\fR] [\\fIoptions\\fR]
.SH DESCRIPTION
Ceefax Station shows live-style teletext pages in a terminal viewer and can
transmit or receive them over amateur radio using AX.25 AFSK.
.PP
With no arguments the viewer opens after refreshing pages from
https://ceefaxstation.com (no API keys required).
.SH COMMANDS
.TP
.B debug
Refresh pages and open the terminal viewer (default).
.TP
.B pages pull
Download the shared hub page pack.
.TP
.B tx now
Transmit the current carousel once.
.TP
.B tx hourly
Refresh before :00 and transmit on the hour.
.TP
.B rx latest
Decode the latest received WAV via Dire Wolf.
.TP
.B rx live
Live soundcard receive via Dire Wolf.
.TP
.B update
Download and install a newer package from GitHub Releases.
.SH FILES
.TP
.I ~/.ceefax_station/ceefax
Writable pages, config, cache, and logs for packaged installs.
.TP
.I /usr/lib/ceefax-station
Installed application code.
.SH SEE ALSO
.BR direwolf (1)
"""


def debian_changelog(label: str) -> str:
    return (
        f"{PACKAGE_NAME} ({debian_package_version(label)}) unstable; urgency=low\n"
        "\n"
        "  * Debian package for Ceefax Station so it can be installed on Linux.\n"
        "\n"
        f" -- {MAINTAINER}  {rfc2822_now()}\n"
    )


def debian_copyright() -> str:
    license_text = LICENSE_FILE.read_text(encoding="utf-8") if LICENSE_FILE.is_file() else "MIT"
    return (
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
        f"Upstream-Name: Ceefax Station\n"
        f"Source: https://github.com/thaum-labs/ceefax_station\n"
        "\n"
        "Files: *\n"
        "Copyright: 2024 M7TJF\n"
        "License: MIT\n"
        "\n"
        "License: MIT\n"
        + "\n".join(" " + (line if line.strip() else ".") for line in license_text.splitlines())
        + "\n"
    )


def control_file(*, version: str, installed_size_kb: int) -> str:
    return f"""Package: {PACKAGE_NAME}
Version: {version}
Section: hamradio
Priority: optional
Architecture: all
Maintainer: {MAINTAINER}
Installed-Size: {installed_size_kb}
Depends: python3 (>= 3.11), python3-requests, python3-bs4
Recommends: direwolf, alsa-utils
Homepage: {HOMEPAGE}
Description: Ceefax-style teletext viewer and amateur radio station
 Ceefax Station shows live-style teletext pages (weather, news, football,
 TV, lottery) in a terminal viewer, and can transmit or receive them
 over amateur radio using AX.25 AFSK.
 .
 Stations download a shared page pack from ceefaxstation.com automatically.
 Live receive decode uses Dire Wolf when the direwolf package is installed.
 Runtime data is stored in ~/.ceefax_station.
"""


def postinst_script() -> str:
    return """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0
"""


def postrm_script() -> str:
    return """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0
"""


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _gzip_bytes(data: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wb") as handle:
        handle.write(data)


def stage_package(staging: Path, *, label: str) -> Path:
    """
    Populate a dpkg-deb staging tree. Returns the staging root.
    """
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    lib = staging / LIBDIR
    lib.mkdir(parents=True, exist_ok=True)
    copy_python_tree(ROOT / "ceefax", lib / "ceefax")
    copy_python_tree(ROOT / "ceefaxstation", lib / "ceefaxstation")
    shutil.copy2(VERSION_FILE, lib / "VERSION")
    if LICENSE_FILE.is_file():
        shutil.copy2(LICENSE_FILE, lib / "LICENSE")

    bindir = staging / "usr/bin"
    bindir.mkdir(parents=True, exist_ok=True)
    wrapper = bindir / "ceefaxstation"
    wrapper.write_text(wrapper_script(), encoding="utf-8")
    _make_executable(wrapper)

    apps = staging / "usr/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "ceefax-station.desktop").write_text(desktop_entry(), encoding="utf-8")

    icon_src = ROOT / "branding" / "logo.png"
    if icon_src.is_file():
        icons = staging / "usr/share/icons/hicolor/256x256/apps"
        icons.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, icons / "ceefax-station.png")

    systemd = staging / "usr/lib/systemd/user"
    systemd.mkdir(parents=True, exist_ok=True)
    (systemd / "ceefax-station.service").write_text(systemd_user_unit(), encoding="utf-8")

    doc = staging / "usr/share/doc" / PACKAGE_NAME
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "copyright").write_text(debian_copyright(), encoding="utf-8")
    _gzip_bytes(debian_changelog(label).encode("utf-8"), doc / "changelog.Debian.gz")
    if (ROOT / "README.md").is_file():
        _gzip_bytes((ROOT / "README.md").read_bytes(), doc / "README.gz")

    man = staging / "usr/share/man/man1"
    _gzip_bytes(man_page(label).encode("utf-8"), man / "ceefaxstation.1.gz")

    debian = staging / "DEBIAN"
    debian.mkdir(parents=True, exist_ok=True)
    installed_size = max(1, (_dir_size_bytes(staging) + 1023) // 1024)
    (debian / "control").write_text(
        control_file(version=debian_package_version(label), installed_size_kb=installed_size),
        encoding="utf-8",
    )
    postinst = debian / "postinst"
    postinst.write_text(postinst_script(), encoding="utf-8")
    _make_executable(postinst)
    postrm = debian / "postrm"
    postrm.write_text(postrm_script(), encoding="utf-8")
    _make_executable(postrm)
    return staging


def build_deb(
    *,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
    label: str | None = None,
) -> Path:
    global ROOT, VERSION_FILE, LICENSE_FILE
    if repo_root is not None:
        ROOT = repo_root
        VERSION_FILE = ROOT / "VERSION"
        LICENSE_FILE = ROOT / "LICENSE"

    version_label = (label or read_version_label()).strip()
    out_dir = output_dir or (ROOT / "installers")
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ceefax-deb-") as tmp:
        staging = Path(tmp) / "pkg"
        stage_package(staging, label=version_label)
        deb_name = versioned_deb_name(version_label)
        deb_path = out_dir / deb_name
        cmd = ["dpkg-deb", "--root-owner-group", "--build", str(staging), str(deb_path)]
        print("+", " ".join(cmd), flush=True)
        subprocess.run(cmd, check=True)
        alias = out_dir / "ceefax-station.deb"
        shutil.copy2(deb_path, alias)
        print(f"Built {deb_path} ({deb_path.stat().st_size} bytes)")
        print(f"Alias {alias}")
        return deb_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for the .deb (default: installers/)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="VERSION label override (default: VERSION file)",
    )
    args = parser.parse_args(argv)
    output = Path(args.output_dir) if args.output_dir else None
    try:
        build_deb(output_dir=output, label=args.version)
    except FileNotFoundError as exc:
        print(f"Missing tool: {exc}. Install dpkg-deb (Debian/Ubuntu: dpkg).", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
