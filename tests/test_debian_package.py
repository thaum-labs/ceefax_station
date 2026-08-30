from __future__ import annotations

import os
from pathlib import Path

from scripts.build_debian_package import (
    PACKAGE_NAME,
    control_file,
    debian_package_version,
    debian_upstream_version,
    stage_package,
    versioned_deb_name,
    wrapper_script,
)


def test_debian_upstream_version_prerelease() -> None:
    assert debian_upstream_version("0.1.5-alpha") == "0.1.5~alpha"
    assert debian_upstream_version("0.1.5") == "0.1.5"
    assert debian_package_version("0.1.5-alpha") == "0.1.5~alpha-1"
    assert versioned_deb_name("0.1.5-alpha") == "ceefax-station_0.1.5~alpha-1_all.deb"


def test_wrapper_sets_packaged_and_imports_cli() -> None:
    text = wrapper_script()
    assert "CEEFAX_PACKAGED" in text
    assert "ceefaxstation.__main__" in text
    assert "lib" in text and "ceefax-station" in text
    assert text.startswith("#!/usr/bin/python3")


def test_control_file_depends_on_python_requests() -> None:
    text = control_file(version="0.1.5~alpha-1", installed_size_kb=500)
    assert text.startswith(f"Package: {PACKAGE_NAME}")
    assert "python3 (>= 3.11)" in text
    assert "python3-requests" in text
    assert "python3-bs4" in text
    assert "direwolf" in text


def test_stage_package_layout(tmp_path: Path) -> None:
    staging = tmp_path / "pkg"
    stage_package(staging, label="0.1.5-alpha")

    wrapper = staging / "usr/bin/ceefaxstation"
    assert wrapper.is_file()
    assert os.access(wrapper, os.X_OK)
    assert (staging / "usr/lib/ceefax-station/ceefaxstation/__main__.py").is_file()
    assert (staging / "usr/lib/ceefax-station/ceefax/src/viewer.py").is_file()
    assert (staging / "usr/lib/ceefax-station/ceefax/config.default.toml").is_file()
    assert (staging / "usr/lib/ceefax-station/VERSION").is_file()
    assert (staging / "usr/share/applications/ceefax-station.desktop").is_file()
    assert (staging / "usr/lib/systemd/user/ceefax-station.service").is_file()
    assert (staging / "DEBIAN/control").is_file()
    control = (staging / "DEBIAN/control").read_text(encoding="utf-8")
    assert "Version: 0.1.5~alpha-1" in control
    assert "Architecture: all" in control

    # Windows Dire Wolf binaries must not ship in the Linux package.
    staged_files = [p.name for p in (staging / "usr/lib/ceefax-station").rglob("*") if p.is_file()]
    assert "direwolf.exe" not in staged_files
    assert not any(name.endswith(".exe") for name in staged_files)


def test_build_deb_creates_package(tmp_path: Path) -> None:
    from scripts.build_debian_package import build_deb

    deb = build_deb(output_dir=tmp_path, label="0.1.5-alpha")
    assert deb.is_file()
    assert deb.name == "ceefax-station_0.1.5~alpha-1_all.deb"
    assert (tmp_path / "ceefax-station.deb").is_file()
    assert deb.stat().st_size > 1024
