#!/usr/bin/env python3
"""
Publish a GitHub Release for Ceefax Station installers.

Uploads:
  - CeefaxStation-Setup-X.Y.Z.exe  (versioned, if present)
  - CeefaxStation-Setup.exe        (stable Windows alias used by /download)
  - ceefax-station_*.deb           (versioned, if present)
  - ceefax-station.deb             (stable Linux alias used by /download/linux)

Usage:
    python scripts/publish_github_release.py
    python scripts/publish_github_release.py --version 0.1.2
    python scripts/publish_github_release.py --dry-run

Requires: gh CLI authenticated with repo release write access.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = ROOT / "installers"
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.json"
STABLE_NAME = "CeefaxStation-Setup.exe"
LINUX_STABLE_NAME = "ceefax-station.deb"


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )
    return result


def read_version_label() -> str:
    if not VERSION_FILE.exists():
        raise SystemExit(f"Missing {VERSION_FILE}")
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def numeric_version(label: str) -> str:
    """Strip prerelease suffix: 0.1.2-alpha -> 0.1.2"""
    return re.sub(r"-.*$", "", label.strip())


def resolve_setup_exe(ver: str) -> Path | None:
    path = INSTALLERS / f"CeefaxStation-Setup-{ver}.exe"
    if path.is_file():
        return path
    return None


def resolve_linux_deb(label: str) -> Path | None:
    alias = INSTALLERS / LINUX_STABLE_NAME
    matches = sorted(INSTALLERS.glob("ceefax-station_*.deb"))
    if matches:
        return matches[-1]
    if alias.is_file():
        return alias
    return None


def changelog_notes(label: str) -> str:
    if not CHANGELOG_FILE.exists():
        return f"Installers for Ceefax Station {label}."
    try:
        data = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return f"Installers for Ceefax Station {label}."

    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return f"Installers for Ceefax Station {label}."

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("version") or "").strip() != label:
            continue
        changes = entry.get("changes")
        date = str(entry.get("date") or "").strip()
        lines = [f"## Ceefax Station {label}", ""]
        if date:
            lines.append(f"Date: {date}")
            lines.append("")
        if isinstance(changes, list) and changes:
            lines.append("### Changes")
            for item in changes:
                lines.append(f"- {item}")
        lines.append("")
        lines.append("### Download")
        lines.append(
            "Windows: website **Download Windows** uses the stable asset "
            "`CeefaxStation-Setup.exe` from this latest release."
        )
        lines.append(
            "Linux: website **Download Linux** uses the stable asset "
            "`ceefax-station.deb` from this latest release."
        )
        return "\n".join(lines)

    return f"Installers for Ceefax Station {label}."


def release_exists(tag: str) -> bool:
    result = _run(["gh", "release", "view", tag], check=False)
    return result.returncode == 0


def publish(*, version_label: str | None, dry_run: bool) -> None:
    label = (version_label or read_version_label()).strip()
    ver = numeric_version(label)
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        raise SystemExit(f"Invalid numeric version derived from {label!r}: {ver!r}")

    setup = resolve_setup_exe(ver)
    linux_deb = resolve_linux_deb(label)
    if setup is None and linux_deb is None:
        raise SystemExit(
            f"No installer found in {INSTALLERS} for version {label}.\n"
            "Build the Windows Setup EXE or run: python scripts/build_debian_package.py"
        )

    tag = f"v{ver}"
    title = label
    notes = changelog_notes(label)

    print(f"Version label : {label}")
    print(f"Numeric ver   : {ver}")
    print(f"Tag           : {tag}")
    if setup is not None:
        print(f"Windows       : {setup} ({setup.stat().st_size} bytes)")
        print(f"Stable alias  : {STABLE_NAME}")
    else:
        print("Windows       : (missing)")
    if linux_deb is not None:
        print(f"Linux         : {linux_deb} ({linux_deb.stat().st_size} bytes)")
        print(f"Linux alias   : {LINUX_STABLE_NAME}")
    else:
        print("Linux         : (missing)")

    with tempfile.TemporaryDirectory(prefix="ceefax-release-") as tmp:
        upload_paths: list[str] = []
        if setup is not None:
            stable = Path(tmp) / STABLE_NAME
            shutil.copy2(setup, stable)
            upload_paths.extend([str(setup), str(stable)])
        if linux_deb is not None:
            linux_stable = Path(tmp) / LINUX_STABLE_NAME
            shutil.copy2(linux_deb, linux_stable)
            if linux_deb.name != LINUX_STABLE_NAME:
                upload_paths.append(str(linux_deb))
            upload_paths.append(str(linux_stable))

        if dry_run:
            print("--- dry-run notes ---")
            print(notes)
            print("--- end notes ---")
            print("Assets:", *upload_paths, sep="\n  ")
            print("Dry run only; no release created.")
            return

        if release_exists(tag):
            print(f"Release {tag} exists — uploading/replacing assets")
            _run(["gh", "release", "upload", tag, *upload_paths, "--clobber"])
            notes_file = Path(tmp) / "notes.md"
            notes_file.write_text(notes, encoding="utf-8")
            _run(
                [
                    "gh",
                    "release",
                    "edit",
                    tag,
                    "--title",
                    title,
                    "--notes-file",
                    str(notes_file),
                    "--latest",
                ],
                check=False,
            )
        else:
            notes_file = Path(tmp) / "notes.md"
            notes_file.write_text(notes, encoding="utf-8")
            _run(
                [
                    "gh",
                    "release",
                    "create",
                    tag,
                    *upload_paths,
                    "--title",
                    title,
                    "--notes-file",
                    str(notes_file),
                    "--latest",
                    "--target",
                    "main",
                ]
            )

    view = _run(["gh", "release", "view", tag, "--json", "url,assets"])
    print(view.stdout)
    print(f"Published {tag}")
    if setup is not None:
        print(
            "Windows URL: "
            f"https://github.com/thaum-labs/ceefax_station/releases/latest/download/{STABLE_NAME}"
        )
    if linux_deb is not None:
        print(
            "Linux URL: "
            f"https://github.com/thaum-labs/ceefax_station/releases/latest/download/{LINUX_STABLE_NAME}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=None,
        help="VERSION label (default: read VERSION file), e.g. 0.1.2-alpha",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve files and print notes without calling gh release",
    )
    args = parser.parse_args()
    try:
        publish(version_label=args.version, dry_run=args.dry_run)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stdout or "")
        sys.stderr.write(exc.stderr or "")
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
