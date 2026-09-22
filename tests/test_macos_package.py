from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest

from scripts.build_macos_package import (
    ARCH_SPECS,
    MIN_OS_VERSION,
    PYTHON_VERSION,
    app_launcher_script,
    arch_spec,
    distribution_xml,
    info_plist,
    numeric_version,
    python_download_url,
    stage_package,
    versioned_pkg_name,
    wrapper_script,
)


def test_numeric_and_pkg_names() -> None:
    assert numeric_version("0.1.6-alpha") == "0.1.6"
    assert versioned_pkg_name("0.1.6-alpha", arch="intel") == "CeefaxStation-Intel-0.1.6.pkg"
    assert (
        versioned_pkg_name("0.1.6-alpha", arch="apple-silicon")
        == "CeefaxStation-AppleSilicon-0.1.6.pkg"
    )
    assert versioned_pkg_name("v0.1.6", arch="arm64") == "CeefaxStation-AppleSilicon-0.1.6.pkg"


def test_arch_aliases() -> None:
    assert arch_spec("intel")["ls_arch"] == "x86_64"
    assert arch_spec("x86_64")["id"] == "intel"
    assert arch_spec("apple-silicon")["ls_arch"] == "arm64"
    assert arch_spec("arm64")["id"] == "apple-silicon"
    assert arch_spec("aarch64")["pip_platform"] == "macosx_13_0_arm64"


def test_intel_targets_macos_13() -> None:
    intel = arch_spec("intel")
    assert intel["pip_platform"] == "macosx_13_0_x86_64"
    assert intel["host_architectures"] == "x86_64"
    assert intel["triple"] == "x86_64-apple-darwin"
    assert MIN_OS_VERSION == "13.0"
    assert PYTHON_VERSION.startswith("3.11")
    url = python_download_url(intel)
    assert "x86_64-apple-darwin" in url
    assert "install_only.tar.gz" in url
    assert "cpython-3.11" in url


def test_apple_silicon_is_native_arm() -> None:
    arm = arch_spec("apple-silicon")
    assert arm["pip_platform"] == "macosx_13_0_arm64"
    assert arm["host_architectures"] == "arm64"
    assert "aarch64-apple-darwin" in python_download_url(arm)
    assert arm["stable_name"] == "CeefaxStation-AppleSilicon.pkg"
    assert ARCH_SPECS["intel"]["stable_name"] == "CeefaxStation-Intel.pkg"


def test_unknown_arch_rejected() -> None:
    with pytest.raises(ValueError, match="unknown macOS arch"):
        arch_spec("sparc")


def test_wrapper_uses_bundled_python() -> None:
    text = wrapper_script()
    assert text.startswith("#!/usr/local/lib/ceefax-station/python/bin/python3")
    assert "CEEFAX_PACKAGED" in text
    assert "ceefaxstation.__main__" in text
    assert "/usr/local/lib/ceefax-station" in text


def test_app_launcher_opens_terminal_without_tty() -> None:
    text = app_launcher_script()
    assert "/usr/local/bin/ceefaxstation" in text
    assert "Terminal" in text
    assert "do script" in text


def test_info_plist_min_os_and_arch() -> None:
    intel = plistlib.loads(info_plist(label="0.1.6-alpha", spec=arch_spec("intel")))
    assert intel["LSMinimumSystemVersion"] == "13.0"
    assert intel["LSArchitecturePriority"] == ["x86_64"]
    assert intel["CFBundleShortVersionString"] == "0.1.6"
    assert intel["CFBundleIdentifier"].endswith(".intel")

    arm = plistlib.loads(info_plist(label="0.1.6-alpha", spec=arch_spec("apple-silicon")))
    assert arm["LSMinimumSystemVersion"] == "13.0"
    assert arm["LSArchitecturePriority"] == ["arm64"]
    assert arm["CFBundleIdentifier"].endswith(".applesilicon")


def test_distribution_xml_pins_arch_and_min_os() -> None:
    xml = distribution_xml(
        label="0.1.6-alpha",
        spec=arch_spec("intel"),
        component_file="component.pkg",
    )
    assert 'hostArchitectures="x86_64"' in xml
    assert 'os-version min="13.0"' in xml
    assert "com.ceefaxstation.pkg.intel" in xml


def test_stage_intel_layout_without_runtime(tmp_path: Path) -> None:
    staging = tmp_path / "root"
    stage_package(
        staging,
        label="0.1.6-alpha",
        arch="intel",
        bundle_python=False,
        install_deps=False,
    )

    wrapper = staging / "usr/local/bin/ceefaxstation"
    assert wrapper.is_file()
    assert os.access(wrapper, os.X_OK)
    assert (staging / "usr/local/lib/ceefax-station/ceefaxstation/__main__.py").is_file()
    assert (staging / "usr/local/lib/ceefax-station/ceefax/src/viewer.py").is_file()
    assert (staging / "usr/local/lib/ceefax-station/VERSION").is_file()

    plist_path = staging / "Applications/CeefaxStation.app/Contents/Info.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["LSMinimumSystemVersion"] == "13.0"
    assert plist["LSArchitecturePriority"] == ["x86_64"]

    launcher = staging / "Applications/CeefaxStation.app/Contents/MacOS/CeefaxStation"
    assert launcher.is_file()
    assert os.access(launcher, os.X_OK)

    staged_files = [
        p.name for p in (staging / "usr/local/lib/ceefax-station").rglob("*") if p.is_file()
    ]
    assert "direwolf.exe" not in staged_files
    assert not any(name.endswith(".exe") for name in staged_files)
    assert not (staging / "usr/local/lib/ceefax-station/python").exists()


def test_stage_cli_skip_runtime(tmp_path: Path) -> None:
    from scripts.build_macos_package import main

    staging = tmp_path / "root"
    assert (
        main(
            [
                "--arch",
                "intel",
                "--skip-runtime",
                "--stage-dir",
                str(staging),
                "--version",
                "0.1.6-alpha",
            ]
        )
        == 0
    )
    assert (staging / "usr/local/bin/ceefaxstation").is_file()


def test_stage_apple_silicon_plist(tmp_path: Path) -> None:
    staging = tmp_path / "root"
    stage_package(
        staging,
        label="0.1.6-alpha",
        arch="apple-silicon",
        bundle_python=False,
        install_deps=False,
    )
    plist = plistlib.loads(
        (staging / "Applications/CeefaxStation.app/Contents/Info.plist").read_bytes()
    )
    assert plist["LSArchitecturePriority"] == ["arm64"]
    assert plist["LSMinimumSystemVersion"] == "13.0"


def test_build_pkg_requires_macos_tools(tmp_path: Path) -> None:
    import shutil

    from scripts.build_macos_package import build_pkg

    if shutil.which("pkgbuild"):
        pytest.skip("pkgbuild is available on this host")
    with pytest.raises(FileNotFoundError, match="macOS installer tools"):
        build_pkg(
            arch="intel",
            output_dir=tmp_path,
            label="0.1.6-alpha",
            bundle_python=False,
            install_deps=False,
        )
