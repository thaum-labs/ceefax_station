from __future__ import annotations

from pathlib import Path

from ceefaxweb.installer_download import latest_installer


def test_latest_installer_picks_highest_version(tmp_path: Path) -> None:
    installers = tmp_path / "installers"
    installers.mkdir()
    (installers / "CeefaxStation-Setup-0.1.0.exe").write_bytes(b"old")
    (installers / "CeefaxStation-Setup-0.1.2.exe").write_bytes(b"new")
    (installers / "CeefaxStation-Setup-0.1.1.exe").write_bytes(b"mid")
    (installers / "README.md").write_text("ignore", encoding="utf-8")

    latest = latest_installer(installers)
    assert latest is not None
    assert latest.name == "CeefaxStation-Setup-0.1.2.exe"


def test_latest_installer_prefers_final_over_prerelease(tmp_path: Path) -> None:
    installers = tmp_path / "installers"
    installers.mkdir()
    (installers / "CeefaxStation-Setup-0.1.2-alpha.exe").write_bytes(b"pre")
    (installers / "CeefaxStation-Setup-0.1.2.exe").write_bytes(b"final")

    latest = latest_installer(installers)
    assert latest is not None
    assert latest.name == "CeefaxStation-Setup-0.1.2.exe"


def test_latest_installer_missing_dir(tmp_path: Path) -> None:
    assert latest_installer(tmp_path / "nope") is None
