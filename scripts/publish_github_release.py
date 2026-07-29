#!/usr/bin/env python3
"""
Publish a GitHub Release for the Windows installer.

Uploads both:
  - CeefaxStation-Setup-X.Y.Z.exe  (versioned)
  - CeefaxStation-Setup.exe        (stable alias used by ceefaxstation.com/download)

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


def resolve_setup_exe(ver: str) -> Path:
    path = INSTALLERS / f"CeefaxStation-Setup-{ver}.exe"
    if path.is_file():
        return path
    raise SystemExit(
        f"Missing installer for version {ver}: {path}\n"
        "Build with build_installer.ps1 and commit installers/CeefaxStation-Setup-{ver}.exe first."
    )


def changelog_notes(label: str) -> str:
    if not CHANGELOG_FILE.exists():
        return f"Windows installer for Ceefax Station {label}."
    try:
        data = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return f"Windows installer for Ceefax Station {label}."

    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return f"Windows installer for Ceefax Station {label}."

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
            "Website **Download app** uses the stable asset "
            "`CeefaxStation-Setup.exe` from this latest release."
        )
        return "\n".join(lines)

    return f"Windows installer for Ceefax Station {label}."


def release_exists(tag: str) -> bool:
    result = _run(["gh", "release", "view", tag], check=False)
    return result.returncode == 0


def publish(*, version_label: str | None, dry_run: bool) -> None:
    label = (version_label or read_version_label()).strip()
    ver = numeric_version(label)
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        raise SystemExit(f"Invalid numeric version derived from {label!r}: {ver!r}")

    setup = resolve_setup_exe(ver)
    tag = f"v{ver}"
    title = label
    notes = changelog_notes(label)

    print(f"Version label : {label}")
    print(f"Numeric ver   : {ver}")
    print(f"Tag           : {tag}")
    print(f"Installer     : {setup} ({setup.stat().st_size} bytes)")
    print(f"Stable alias  : {STABLE_NAME}")

    with tempfile.TemporaryDirectory(prefix="ceefax-release-") as tmp:
        stable = Path(tmp) / STABLE_NAME
        shutil.copy2(setup, stable)

        if dry_run:
            print("--- dry-run notes ---")
            print(notes)
            print("--- end notes ---")
            print("Dry run only; no release created.")
            return

        if release_exists(tag):
            print(f"Release {tag} exists — uploading/replacing assets")
            _run(
                [
                    "gh",
                    "release",
                    "upload",
                    tag,
                    str(setup),
                    str(stable),
                    "--clobber",
                ]
            )
            # Keep release metadata fresh when re-publishing the same tag.
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
                    str(setup),
                    str(stable),
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
    print(
        "Download URL: "
        f"https://github.com/thaum-labs/ceefax_station/releases/latest/download/{STABLE_NAME}"
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
