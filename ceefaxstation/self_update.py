"""Check GitHub Releases and apply app updates via the platform installer."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_REPO = "thaum-labs/ceefax_station"
STABLE_ASSET_WINDOWS = "CeefaxStation-Setup.exe"
STABLE_ASSET_LINUX = "ceefax-station.deb"
STABLE_ASSET_MAC_INTEL = "CeefaxStation-Intel.pkg"
STABLE_ASSET_MAC_ARM = "CeefaxStation-AppleSilicon.pkg"
STABLE_ASSET = STABLE_ASSET_WINDOWS
GITHUB_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
GITHUB_DOWNLOAD_LATEST = (
    "https://github.com/{repo}/releases/latest/download/{asset}"
)


ProgressCb = Callable[[str], None]


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version_label: str
    numeric_version: str
    download_url: str
    asset_name: str
    published_at: str | None = None


def normalize_version(value: str) -> tuple[int, ...]:
    """
    Compare versions numerically, ignoring a leading 'v' and prerelease suffix.

    Examples: 'v0.1.3', '0.1.3-alpha' -> (0, 1, 3)
    """
    raw = (value or "").strip()
    if raw.lower().startswith("v"):
        raw = raw[1:]
    raw = re.sub(r"[-+].*$", "", raw)
    parts = [int(p) for p in re.findall(r"\d+", raw)]
    return tuple(parts) if parts else (0,)


def is_remote_newer(local_version: str, remote_version: str) -> bool:
    return normalize_version(remote_version) > normalize_version(local_version)


def local_app_version() -> str:
    from ceefax.src.update_about_page import get_app_version

    return get_app_version()


def updates_dir() -> Path:
    from ceefax.src.paths import repo_root

    path = repo_root() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def installer_asset_for_platform() -> str:
    if sys.platform.startswith("linux"):
        return STABLE_ASSET_LINUX
    if sys.platform == "darwin":
        machine = (platform.machine() or "").lower()
        if machine in {"arm64", "aarch64"}:
            return STABLE_ASSET_MAC_ARM
        return STABLE_ASSET_MAC_INTEL
    return STABLE_ASSET_WINDOWS


def _is_linux_deb_name(name: str) -> bool:
    lower = name.lower()
    return lower == STABLE_ASSET_LINUX or (
        lower.startswith("ceefax-station_") and lower.endswith(".deb")
    )


def _is_windows_setup_name(name: str) -> bool:
    lower = name.lower()
    return lower == STABLE_ASSET_WINDOWS or (
        lower.startswith("ceefaxstation-setup-") and lower.endswith(".exe")
    )


def _is_mac_intel_pkg_name(name: str) -> bool:
    lower = name.lower()
    return lower == STABLE_ASSET_MAC_INTEL.lower() or (
        lower.startswith("ceefaxstation-intel-") and lower.endswith(".pkg")
    )


def _is_mac_arm_pkg_name(name: str) -> bool:
    lower = name.lower()
    return lower == STABLE_ASSET_MAC_ARM.lower() or (
        lower.startswith("ceefaxstation-applesilicon-") and lower.endswith(".pkg")
    )


def _http_json(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "CeefaxStation-Updater/1.0",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("GitHub release response was not a JSON object")
    return data


def fetch_latest_release(
    *,
    repo: str = DEFAULT_REPO,
    asset: str | None = None,
) -> ReleaseInfo:
    """Load latest GitHub release metadata and resolve the platform installer URL."""
    wanted = (asset or installer_asset_for_platform()).strip()
    payload = _http_json(GITHUB_API_LATEST.format(repo=repo))
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("Latest GitHub release has no tag_name")

    assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []
    download_url = ""
    asset_name = wanted
    fallback_url = ""
    fallback_name = ""
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        url = str(item.get("browser_download_url") or "")
        if not name or not url:
            continue
        if name.lower() == wanted.lower():
            download_url = url
            asset_name = name
            break
        wanted_l = wanted.lower()
        linux_wanted = wanted_l.endswith(".deb")
        mac_intel_wanted = _is_mac_intel_pkg_name(wanted)
        mac_arm_wanted = _is_mac_arm_pkg_name(wanted)
        if linux_wanted and _is_linux_deb_name(name) and not fallback_url:
            fallback_url = url
            fallback_name = name
        elif mac_intel_wanted and _is_mac_intel_pkg_name(name) and not fallback_url:
            fallback_url = url
            fallback_name = name
        elif mac_arm_wanted and _is_mac_arm_pkg_name(name) and not fallback_url:
            fallback_url = url
            fallback_name = name
        elif (
            not linux_wanted
            and not mac_intel_wanted
            and not mac_arm_wanted
            and _is_windows_setup_name(name)
            and not fallback_url
        ):
            fallback_url = url
            fallback_name = name

    if not download_url and fallback_url:
        download_url = fallback_url
        asset_name = fallback_name

    if not download_url:
        download_url = GITHUB_DOWNLOAD_LATEST.format(repo=repo, asset=wanted)
        asset_name = wanted

    numeric = re.sub(r"^v", "", tag, flags=re.IGNORECASE)
    numeric = re.sub(r"[-+].*$", "", numeric)
    label = str(payload.get("name") or tag).strip() or tag
    published = str(payload.get("published_at") or "").strip() or None
    return ReleaseInfo(
        tag=tag,
        version_label=label,
        numeric_version=numeric,
        download_url=download_url,
        asset_name=asset_name,
        published_at=published,
    )


def check_for_update(*, repo: str = DEFAULT_REPO) -> tuple[str, ReleaseInfo | None, bool]:
    """
    Returns (local_version, latest_release_or_None, update_available).
    """
    local = local_app_version()
    latest = fetch_latest_release(repo=repo)
    return local, latest, is_remote_newer(local, latest.tag)


def download_file(url: str, dest: Path, *, progress: ProgressCb | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "CeefaxStation-Updater/1.0"})
    if progress:
        progress(f"Downloading {dest.name} ...")
    with urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = resp.headers.get("Content-Length")
        try:
            total_n = int(total) if total else 0
        except ValueError:
            total_n = 0
        read_n = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            read_n += len(chunk)
            if progress and total_n > 0:
                pct = min(100, int(read_n * 100 / total_n))
                progress(f"Downloading {dest.name} ... {pct}%")
    if progress:
        progress(f"Downloaded {dest.name}")
    return dest


def launch_installer(setup_path: Path, *, silent: bool = True) -> None:
    """
    Launch the downloaded installer.

    Windows: Inno Setup with UAC elevation.
    Linux: `pkexec dpkg -i` (or sudo) for the Debian package.
    macOS: `installer -pkg` with an admin privileges prompt.
    """
    setup_path = setup_path.resolve()
    if not setup_path.is_file():
        raise FileNotFoundError(setup_path)

    if setup_path.suffix.lower() == ".deb" or (
        sys.platform.startswith("linux") and setup_path.name.lower().endswith(".deb")
    ):
        _launch_deb(setup_path)
        return

    if setup_path.suffix.lower() == ".pkg" or (
        sys.platform == "darwin" and setup_path.name.lower().endswith(".pkg")
    ):
        _launch_pkg(setup_path)
        return

    args = [str(setup_path)]
    if silent:
        # CLOSEAPPLICATIONS helps replace the running EXE after we exit.
        args.extend(
            [
                "/VERYSILENT",
                "/NORESTART",
                "/SUPPRESSMSGBOXES",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
            ]
        )

    if sys.platform.startswith("win"):
        # ShellExecute 'runas' triggers UAC elevation when needed.
        try:
            import ctypes

            params = subprocess.list2cmdline(args[1:]) if len(args) > 1 else ""
            rc = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
                None,
                "runas",
                str(setup_path),
                params,
                str(setup_path.parent),
                1,
            )
            # ShellExecute returns value > 32 on success.
            if int(rc) <= 32:
                raise OSError(f"ShellExecute failed with code {rc}")
            return
        except Exception:
            # Fall back to normal spawn (may fail without admin).
            pass

    subprocess.Popen(args, cwd=str(setup_path.parent))


def _launch_deb(deb_path: Path) -> None:
    deb = str(deb_path)
    if shutil.which("pkexec"):
        subprocess.Popen(["pkexec", "dpkg", "-i", deb])
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        subprocess.Popen(["dpkg", "-i", deb])
        return
    if shutil.which("sudo"):
        subprocess.Popen(["sudo", "dpkg", "-i", deb])
        return
    raise OSError(
        "Need pkexec or sudo to install the Debian package. "
        f"You can install it manually with: sudo dpkg -i {deb}"
    )


def _launch_pkg(pkg_path: Path) -> None:
    pkg = str(pkg_path)
    quoted = pkg.replace("\\", "\\\\").replace('"', '\\"')
    if shutil.which("osascript"):
        subprocess.Popen(
            [
                "osascript",
                "-e",
                f'do shell script "installer -pkg \\"{quoted}\\" -target /" with administrator privileges',
            ]
        )
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        subprocess.Popen(["installer", "-pkg", pkg, "-target", "/"])
        return
    if shutil.which("sudo"):
        subprocess.Popen(["sudo", "installer", "-pkg", pkg, "-target", "/"])
        return
    raise OSError(
        "Need an admin password to install the macOS package. "
        f"You can install it manually with: sudo installer -pkg {pkg} -target /"
    )


def apply_update(
    *,
    repo: str = DEFAULT_REPO,
    force: bool = False,
    silent: bool = True,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """
    Check GitHub for a newer release, download the platform installer, and launch it.

    Returns a result dict with keys: status, local, remote, path (optional).
    status: up_to_date | ready | launched | error
    """
    def note(msg: str) -> None:
        if progress:
            progress(msg)

    local = local_app_version()
    note(f"Local version: {local}")
    try:
        latest = fetch_latest_release(repo=repo)
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        return {"status": "error", "local": local, "error": str(exc)}

    note(f"Latest release: {latest.tag} ({latest.version_label})")
    if not force and not is_remote_newer(local, latest.tag):
        note("Already up to date.")
        return {"status": "up_to_date", "local": local, "remote": latest.tag}

    dest = updates_dir() / latest.asset_name
    try:
        download_file(latest.download_url, dest, progress=progress)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {
            "status": "error",
            "local": local,
            "remote": latest.tag,
            "error": f"download failed: {exc}",
        }

    if dest.suffix.lower() == ".deb":
        note("Starting Debian installer (authenticate if prompted)...")
    elif dest.suffix.lower() == ".pkg":
        note("Starting macOS installer (authenticate if prompted)...")
    else:
        note("Starting installer (approve UAC if prompted)...")
    try:
        launch_installer(dest, silent=silent)
    except OSError as exc:
        return {
            "status": "error",
            "local": local,
            "remote": latest.tag,
            "path": str(dest),
            "error": f"could not launch installer: {exc}",
        }

    return {
        "status": "launched",
        "local": local,
        "remote": latest.tag,
        "path": str(dest),
    }


def run_cli_update(*, check_only: bool = False, yes: bool = False, force: bool = False) -> int:
    """CLI entry used by `ceefaxstation update`."""
    try:
        local, latest, available = check_for_update()
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError, OSError) as exc:
        print(f"Update check failed: {exc}", file=sys.stderr)
        return 1

    print(f"Installed: {local}")
    print(f"Latest:    {latest.tag} ({latest.version_label})")
    if check_only:
        return 0 if not available else 2

    if not available and not force:
        print("Already up to date.")
        return 0

    if not yes and sys.stdin.isatty():
        ans = input(f"Download and install {latest.tag} now? [y/N] ").strip().lower()
        if ans not in {"y", "yes"}:
            print("Cancelled.")
            return 1

    result = apply_update(force=force, silent=True, progress=print)
    status = result.get("status")
    if status == "up_to_date":
        print("Already up to date.")
        return 0
    if status == "launched":
        if sys.platform.startswith("linux"):
            print("Installer started. Authenticate if prompted, then relaunch Ceefax Station.")
        elif sys.platform == "darwin":
            print("Installer started. Authenticate if prompted, then relaunch Ceefax Station.")
        else:
            print("Installer started. Ceefax Station will exit so files can be replaced.")
            print("If the app does not reopen, launch it from the Start Menu.")
        return 0
    print(f"Update failed: {result.get('error')}", file=sys.stderr)
    return 1
