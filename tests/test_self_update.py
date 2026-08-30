from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ceefaxstation.self_update import (
    ReleaseInfo,
    apply_update,
    fetch_latest_release,
    is_remote_newer,
    normalize_version,
    run_cli_update,
)


def test_normalize_version_strips_prefix_and_prerelease() -> None:
    assert normalize_version("v0.1.3") == (0, 1, 3)
    assert normalize_version("0.1.3-alpha") == (0, 1, 3)
    assert normalize_version("0.1.4") == (0, 1, 4)
    assert normalize_version("") == (0,)


def test_is_remote_newer() -> None:
    assert is_remote_newer("0.1.3-alpha", "v0.1.4")
    assert is_remote_newer("0.1.2", "0.1.3-alpha")
    assert not is_remote_newer("0.1.4-alpha", "v0.1.4")
    assert not is_remote_newer("0.1.4", "0.1.3")


def test_fetch_latest_release_prefers_stable_asset() -> None:
    payload = {
        "tag_name": "v0.1.4",
        "name": "Ceefax Station 0.1.4",
        "published_at": "2026-07-31T12:00:00Z",
        "assets": [
            {
                "name": "CeefaxStation-Setup-0.1.4.exe",
                "browser_download_url": "https://example.com/versioned.exe",
            },
            {
                "name": "CeefaxStation-Setup.exe",
                "browser_download_url": "https://example.com/stable.exe",
            },
        ],
    }
    with patch("ceefaxstation.self_update._http_json", return_value=payload):
        info = fetch_latest_release(asset="CeefaxStation-Setup.exe")
    assert info.tag == "v0.1.4"
    assert info.numeric_version == "0.1.4"
    assert info.asset_name == "CeefaxStation-Setup.exe"
    assert info.download_url == "https://example.com/stable.exe"


def test_apply_update_up_to_date(tmp_path: Path) -> None:
    latest = ReleaseInfo(
        tag="v0.1.3",
        version_label="0.1.3",
        numeric_version="0.1.3",
        download_url="https://example.com/setup.exe",
        asset_name="CeefaxStation-Setup.exe",
    )
    with (
        patch("ceefaxstation.self_update.local_app_version", return_value="0.1.3-alpha"),
        patch("ceefaxstation.self_update.fetch_latest_release", return_value=latest),
        patch("ceefaxstation.self_update.updates_dir", return_value=tmp_path),
        patch("ceefaxstation.self_update.download_file") as download,
        patch("ceefaxstation.self_update.launch_installer") as launch,
    ):
        result = apply_update()
    assert result["status"] == "up_to_date"
    download.assert_not_called()
    launch.assert_not_called()


def test_apply_update_downloads_and_launches(tmp_path: Path) -> None:
    latest = ReleaseInfo(
        tag="v0.1.4",
        version_label="0.1.4",
        numeric_version="0.1.4",
        download_url="https://example.com/setup.exe",
        asset_name="CeefaxStation-Setup.exe",
    )
    dest = tmp_path / "CeefaxStation-Setup.exe"

    def fake_download(url: str, path: Path, *, progress=None):  # noqa: ANN001
        path.write_bytes(b"MZ")
        if progress:
            progress("100%")
        return path

    with (
        patch("ceefaxstation.self_update.local_app_version", return_value="0.1.3-alpha"),
        patch("ceefaxstation.self_update.fetch_latest_release", return_value=latest),
        patch("ceefaxstation.self_update.updates_dir", return_value=tmp_path),
        patch("ceefaxstation.self_update.download_file", side_effect=fake_download),
        patch("ceefaxstation.self_update.launch_installer") as launch,
    ):
        result = apply_update()
    assert result["status"] == "launched"
    assert result["remote"] == "v0.1.4"
    assert Path(result["path"]) == dest
    launch.assert_called_once()


def test_fetch_latest_release_prefers_linux_deb() -> None:
    payload = {
        "tag_name": "v0.1.5",
        "name": "Ceefax Station 0.1.5-alpha",
        "published_at": "2026-08-30T12:00:00Z",
        "assets": [
            {
                "name": "ceefax-station_0.1.5~alpha-1_all.deb",
                "browser_download_url": "https://example.com/versioned.deb",
            },
            {
                "name": "ceefax-station.deb",
                "browser_download_url": "https://example.com/stable.deb",
            },
            {
                "name": "CeefaxStation-Setup.exe",
                "browser_download_url": "https://example.com/stable.exe",
            },
        ],
    }
    with patch("ceefaxstation.self_update._http_json", return_value=payload):
        info = fetch_latest_release(asset="ceefax-station.deb")
    assert info.asset_name == "ceefax-station.deb"
    assert info.download_url == "https://example.com/stable.deb"


def test_apply_update_linux_deb_dest(tmp_path: Path) -> None:
    latest = ReleaseInfo(
        tag="v0.1.5",
        version_label="0.1.5-alpha",
        numeric_version="0.1.5",
        download_url="https://example.com/stable.deb",
        asset_name="ceefax-station.deb",
    )
    dest = tmp_path / "ceefax-station.deb"

    def fake_download(url: str, path: Path, *, progress=None):  # noqa: ANN001
        path.write_bytes(b"!debian")
        if progress:
            progress("100%")
        return path

    with (
        patch("ceefaxstation.self_update.local_app_version", return_value="0.1.4-alpha"),
        patch("ceefaxstation.self_update.fetch_latest_release", return_value=latest),
        patch("ceefaxstation.self_update.updates_dir", return_value=tmp_path),
        patch("ceefaxstation.self_update.download_file", side_effect=fake_download),
        patch("ceefaxstation.self_update.launch_installer") as launch,
    ):
        result = apply_update()
    assert result["status"] == "launched"
    assert Path(result["path"]) == dest
    launch.assert_called_once()


def test_run_cli_update_check_only_exit_codes() -> None:
    latest = ReleaseInfo(
        tag="v0.1.4",
        version_label="0.1.4",
        numeric_version="0.1.4",
        download_url="https://example.com/setup.exe",
        asset_name="CeefaxStation-Setup.exe",
    )
    with patch(
        "ceefaxstation.self_update.check_for_update",
        return_value=("0.1.3-alpha", latest, True),
    ):
        assert run_cli_update(check_only=True) == 2

    with patch(
        "ceefaxstation.self_update.check_for_update",
        return_value=("0.1.4-alpha", latest, False),
    ):
        assert run_cli_update(check_only=True) == 0
