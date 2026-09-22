#!/usr/bin/env python3
"""
Build macOS .pkg installers for Ceefax Station.

Produces (per architecture):
  installers/CeefaxStation-Intel-<numeric>.pkg
  installers/CeefaxStation-Intel.pkg
  installers/CeefaxStation-AppleSilicon-<numeric>.pkg
  installers/CeefaxStation-AppleSilicon.pkg

Intel packages target macOS 13 (Ventura) and later (x86_64).
Apple Silicon packages are native arm64, also advertised for macOS 13+.

Each installer bundles a relocatable CPython 3.11 runtime so Macs do not
need Homebrew or a system Python. Live RX still uses Dire Wolf from PATH
(`brew install direwolf`) when present.

Must be run on macOS to produce a real .pkg (`pkgbuild` + `productbuild`).
Staging, wrappers, and Info.plist can be tested on Linux:

  python scripts/build_macos_package.py --arch intel --skip-runtime --stage-dir /tmp/mac
  python scripts/build_macos_package.py --arch apple-silicon
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_debian_package import copy_python_tree, read_version_label


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
LICENSE_FILE = ROOT / "LICENSE"
PACKAGE_NAME = "ceefax-station"
HOMEPAGE = "https://ceefaxstation.com"
LIBDIR = "usr/local/lib/ceefax-station"
BINDIR = "usr/local/bin"
APP_BUNDLE_NAME = "CeefaxStation.app"
MIN_OS_VERSION = "13.0"
PYTHON_STANDALONE_TAG = "20260901"
PYTHON_VERSION = "3.11.16"
PYTHON_BASE_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    + PYTHON_STANDALONE_TAG
)
RUNTIME_PACKAGES = ("requests>=2.32.0", "beautifulsoup4>=4.12.0")

# Pinned install_only CPython builds (macOS 11+, so OS X 13 Intel is in range).
ARCH_SPECS: dict[str, dict[str, str]] = {
    "intel": {
        "id": "intel",
        "triple": "x86_64-apple-darwin",
        "pip_platform": "macosx_13_0_x86_64",
        "host_architectures": "x86_64",
        "ls_arch": "x86_64",
        "pkg_id": "com.ceefaxstation.pkg.intel",
        "bundle_id": "com.ceefaxstation.app.intel",
        "stable_name": "CeefaxStation-Intel.pkg",
        "display_arch": "Intel",
        "sha256": "167cc15cf4eeb72944a67bbd2f7120c45fded17d5043d5db64b3144d7adc30ae",
        "python_filename": (
            f"cpython-{PYTHON_VERSION}+{PYTHON_STANDALONE_TAG}-"
            "x86_64-apple-darwin-install_only.tar.gz"
        ),
    },
    "apple-silicon": {
        "id": "apple-silicon",
        "triple": "aarch64-apple-darwin",
        "pip_platform": "macosx_13_0_arm64",
        "host_architectures": "arm64",
        "ls_arch": "arm64",
        "pkg_id": "com.ceefaxstation.pkg.applesilicon",
        "bundle_id": "com.ceefaxstation.app.applesilicon",
        "stable_name": "CeefaxStation-AppleSilicon.pkg",
        "display_arch": "Apple Silicon",
        "sha256": "50424fa409e8ae84b82a3052522f64695b47dff2158b70bb7358e0ebd6c085c9",
        "python_filename": (
            f"cpython-{PYTHON_VERSION}+{PYTHON_STANDALONE_TAG}-"
            "aarch64-apple-darwin-install_only.tar.gz"
        ),
    },
}


def numeric_version(label: str) -> str:
    raw = (label or "").strip()
    if raw.lower().startswith("v"):
        raw = raw[1:]
    return raw.split("-", 1)[0].split("+", 1)[0]


def versioned_pkg_name(label: str, *, arch: str) -> str:
    spec = arch_spec(arch)
    return spec["stable_name"].replace(".pkg", f"-{numeric_version(label)}.pkg")


def arch_spec(arch: str) -> dict[str, str]:
    key = (arch or "").strip().lower().replace("_", "-")
    aliases = {
        "x86-64": "intel",
        "x86_64": "intel",
        "x64": "intel",
        "amd64": "intel",
        "intel": "intel",
        "arm64": "apple-silicon",
        "aarch64": "apple-silicon",
        "apple-silicon": "apple-silicon",
        "applesilicon": "apple-silicon",
    }
    resolved = aliases.get(key)
    if resolved is None or resolved not in ARCH_SPECS:
        raise ValueError(f"unknown macOS arch {arch!r}; use intel or apple-silicon")
    return ARCH_SPECS[resolved]


def python_download_url(spec: dict[str, str]) -> str:
    return f"{PYTHON_BASE_URL}/{spec['python_filename']}"


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def wrapper_script() -> str:
    """CLI entry at /usr/local/bin/ceefaxstation using the bundled CPython."""
    return """#!/usr/local/lib/ceefax-station/python/bin/python3
import os
import sys
from pathlib import Path

ROOT = str(Path("/usr/local/lib/ceefax-station"))
os.environ["CEEFAX_PACKAGED"] = "1"
previous = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = ROOT + (os.pathsep + previous if previous else "")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ceefaxstation.__main__ import main

raise SystemExit(main())
"""


def app_launcher_script() -> str:
    """Finder double-click opens Terminal; CLI invocations run in-place."""
    return r"""#!/bin/bash
set -euo pipefail
BIN="/usr/local/bin/ceefaxstation"
if [[ ! -x "$BIN" ]]; then
  osascript -e 'display alert "Ceefax Station" message "The ceefaxstation command is missing. Reinstall the .pkg from ceefaxstation.com/download/mac." as critical'
  exit 1
fi
if [[ -t 0 || -n "${SSH_TTY:-}" ]]; then
  exec "$BIN" "$@"
fi
# Finder / Dock launch: give the TUI a real terminal.
quoted=$(printf "%q" "$BIN")
osascript <<EOF
tell application "Terminal"
  activate
  do script "exec ${quoted}"
end tell
EOF
"""


def info_plist(*, label: str, spec: dict[str, str]) -> bytes:
    ver = numeric_version(label)
    data = {
        "CFBundleName": "Ceefax Station",
        "CFBundleDisplayName": "Ceefax Station",
        "CFBundleIdentifier": spec["bundle_id"],
        "CFBundleVersion": ver,
        "CFBundleShortVersionString": ver,
        "CFBundleExecutable": "CeefaxStation",
        "CFBundlePackageType": "APPL",
        "CFBundleSignature": "????",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": MIN_OS_VERSION,
        "LSArchitecturePriority": [spec["ls_arch"]],
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleIconFile": "AppIcon",
    }
    return plistlib.dumps(data, sort_keys=False)


def component_plist() -> bytes:
    # pkgbuild --component-plist expects an array of bundle dicts.
    return plistlib.dumps(
        [
            {
                "RootRelativeBundlePath": f"Applications/{APP_BUNDLE_NAME}",
                "BundleIsRelocatable": False,
                "BundleOverwriteAction": "upgrade",
                "BundleHasStrictIdentifier": False,
            }
        ],
        sort_keys=False,
    )


def postinstall_script() -> str:
    return """#!/bin/sh
set -e
chmod 755 /usr/local/bin/ceefaxstation 2>/dev/null || true
chmod 755 /Applications/CeefaxStation.app/Contents/MacOS/CeefaxStation 2>/dev/null || true
if [ -d /usr/local/lib/ceefax-station ]; then
  chmod -R a+rX /usr/local/lib/ceefax-station
  find /usr/local/lib/ceefax-station/python -type f \\( -name 'python*' -o -name 'pip*' \\) -exec chmod a+x {} + 2>/dev/null || true
fi
exit 0
"""


def distribution_xml(*, label: str, spec: dict[str, str], component_file: str) -> str:
    ver = numeric_version(label)
    title = f"Ceefax Station ({spec['display_arch']})"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>{escape(title)}</title>
    <organization>com.ceefaxstation</organization>
    <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
    <options customize="never" require-scripts="false" hostArchitectures="{escape(spec['host_architectures'])}"/>
    <allowed-os-versions>
        <os-version min="{MIN_OS_VERSION}"/>
    </allowed-os-versions>
    <welcome file="welcome.txt" mime-type="text/plain"/>
    <license file="LICENSE" mime-type="text/plain"/>
    <pkg-ref id="{escape(spec['pkg_id'])}"/>
    <choices-outline>
        <line choice="default">
            <line choice="{escape(spec['pkg_id'])}"/>
        </line>
    </choices-outline>
    <choice id="default"/>
    <choice id="{escape(spec['pkg_id'])}" visible="false">
        <pkg-ref id="{escape(spec['pkg_id'])}"/>
    </choice>
    <pkg-ref id="{escape(spec['pkg_id'])}" version="{escape(ver)}" onConclusion="none">{escape(component_file)}</pkg-ref>
</installer-gui-script>
"""


def welcome_text(*, label: str, spec: dict[str, str]) -> str:
    return (
        f"This installs Ceefax Station {label} for {spec['display_arch']} Macs.\n"
        f"Minimum macOS: {MIN_OS_VERSION} (Ventura).\n"
        "\n"
        "It adds:\n"
        "  • CeefaxStation.app in /Applications (opens the terminal viewer)\n"
        "  • the ceefaxstation command in /usr/local/bin\n"
        "\n"
        "Runtime data lives in ~/.ceefax_station.\n"
        "Optional live receive: brew install direwolf\n"
        "\n"
        f"More: {HOMEPAGE}\n"
    )


def cache_dir() -> Path:
    override = os.environ.get("CEEFAX_MACOS_CACHE")
    if override:
        path = Path(override).expanduser()
    else:
        path = ROOT / "packaging" / "macos" / ".cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_python_runtime(spec: dict[str, str], *, dest_dir: Path) -> Path:
    """
    Download and verify the pinned CPython standalone tarball.

    Returns the path to the tarball.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    tarball = dest_dir / spec["python_filename"]
    expected = spec["sha256"].lower()
    if tarball.is_file() and _sha256_file(tarball) == expected:
        return tarball

    url = python_download_url(spec)
    print(f"Downloading {url}", flush=True)
    req = Request(url, headers={"User-Agent": "CeefaxStation-MacPackager/1.0"})
    tmp = tarball.with_suffix(tarball.suffix + ".partial")
    with urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    actual = _sha256_file(tmp)
    if actual != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 mismatch for {tarball.name}: expected {expected}, got {actual}"
        )
    tmp.replace(tarball)
    return tarball


def extract_python_runtime(tarball: Path, dest_python: Path) -> None:
    if dest_python.exists():
        shutil.rmtree(dest_python)
    dest_python.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        try:
            tar.extractall(dest_python.parent, filter="data")
        except TypeError:
            tar.extractall(dest_python.parent)
    extracted = dest_python.parent / "python"
    if extracted.resolve() != dest_python.resolve():
        if dest_python.exists():
            shutil.rmtree(dest_python)
        extracted.rename(dest_python)


def install_python_deps(python_root: Path, *, spec: dict[str, str]) -> None:
    """Install runtime deps with the bundled CPython (Rosetta for Intel-on-ARM)."""
    python = python_root / "bin" / "python3"
    if not python.is_file():
        raise FileNotFoundError(f"bundled python missing: {python}")
    _make_executable(python)
    cmd = [str(python), "-m", "pip", "install", "--upgrade", *RUNTIME_PACKAGES]
    host = (platform.machine() or "").lower()
    if spec["ls_arch"] == "x86_64" and host in {"arm64", "aarch64"} and shutil.which("arch"):
        cmd = ["arch", "-x86_64", *cmd]
    env = os.environ.copy()
    env["MACOSX_DEPLOYMENT_TARGET"] = MIN_OS_VERSION
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def _maybe_copy_icon(app_contents: Path) -> None:
    resources = app_contents / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    png = ROOT / "branding" / "logo.png"
    if png.is_file():
        shutil.copy2(png, resources / "AppIcon.png")
    icns_tool = shutil.which("iconutil")
    sips = shutil.which("sips")
    if not (icns_tool and sips and png.is_file()):
        return
    iconset = app_contents / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True, exist_ok=True)
    mapping = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for px, name in mapping:
        subprocess.run(
            [sips, "-z", str(px), str(px), str(png), "--out", str(iconset / name)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    icns = resources / "AppIcon.icns"
    subprocess.run([icns_tool, "-c", "icns", "-o", str(icns), str(iconset)], check=False)
    shutil.rmtree(iconset, ignore_errors=True)


def stage_package(
    staging: Path,
    *,
    label: str,
    arch: str,
    bundle_python: bool = True,
    install_deps: bool = True,
    python_tarball: Path | None = None,
) -> Path:
    """
    Populate a pkgbuild root. Returns the staging root.
    """
    spec = arch_spec(arch)
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

    if bundle_python:
        tarball = python_tarball or download_python_runtime(spec, dest_dir=cache_dir())
        extract_python_runtime(tarball, lib / "python")
        if install_deps:
            install_python_deps(lib / "python", spec=spec)

    bindir = staging / BINDIR
    bindir.mkdir(parents=True, exist_ok=True)
    wrapper = bindir / "ceefaxstation"
    wrapper.write_text(wrapper_script(), encoding="utf-8")
    _make_executable(wrapper)

    app = staging / "Applications" / APP_BUNDLE_NAME
    macos_dir = app / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_bytes(info_plist(label=label, spec=spec))
    launcher = macos_dir / "CeefaxStation"
    launcher.write_text(app_launcher_script(), encoding="utf-8")
    _make_executable(launcher)
    _maybe_copy_icon(app / "Contents")

    pkginfo = app / "Contents" / "PkgInfo"
    pkginfo.write_text("APPL????", encoding="ascii")
    return staging


def _run_pkgbuild(
    *,
    staging: Path,
    spec: dict[str, str],
    version_label: str,
    scripts_dir: Path,
    component_plist_path: Path,
    component_path: Path,
) -> None:
    """Run pkgbuild, dropping optional flags if this pkgbuild is older."""
    extras = [
        ["--component-plist", str(component_plist_path), "--min-os-version", MIN_OS_VERSION],
        ["--component-plist", str(component_plist_path)],
        ["--min-os-version", MIN_OS_VERSION],
        [],
    ]
    last: subprocess.CompletedProcess[str] | None = None
    cmd: list[str] = []
    for extra in extras:
        cmd = [
            "pkgbuild",
            "--root",
            str(staging),
            "--identifier",
            spec["pkg_id"],
            "--version",
            numeric_version(version_label),
            "--install-location",
            "/",
            "--scripts",
            str(scripts_dir),
            *extra,
            str(component_path),
        ]
        print("+", " ".join(cmd), flush=True)
        last = subprocess.run(cmd, check=False, text=True, capture_output=True)
        if last.stdout:
            print(last.stdout, end="" if last.stdout.endswith("\n") else "\n")
        if last.returncode == 0:
            return
        if last.stderr:
            print(last.stderr, end="" if last.stderr.endswith("\n") else "\n", file=sys.stderr)
    assert last is not None
    raise subprocess.CalledProcessError(
        last.returncode, cmd, output=last.stdout, stderr=last.stderr
    )


def _require_macos_tools() -> None:
    missing = [name for name in ("pkgbuild", "productbuild") if shutil.which(name) is None]
    if missing:
        raise FileNotFoundError(
            "macOS installer tools not found: "
            + ", ".join(missing)
            + ". Run this script on macOS 13+ (GitHub Actions macos runner)."
        )


def build_pkg(
    *,
    arch: str,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
    label: str | None = None,
    bundle_python: bool = True,
    install_deps: bool = True,
) -> Path:
    global ROOT, VERSION_FILE, LICENSE_FILE
    if repo_root is not None:
        ROOT = repo_root
        VERSION_FILE = ROOT / "VERSION"
        LICENSE_FILE = ROOT / "LICENSE"

    spec = arch_spec(arch)
    version_label = (label or read_version_label()).strip()
    out_dir = output_dir or (ROOT / "installers")
    out_dir.mkdir(parents=True, exist_ok=True)
    _require_macos_tools()

    with tempfile.TemporaryDirectory(prefix="ceefax-mac-") as tmp:
        tmp_path = Path(tmp)
        staging = tmp_path / "root"
        stage_package(
            staging,
            label=version_label,
            arch=spec["id"],
            bundle_python=bundle_python,
            install_deps=install_deps,
        )

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        postinst = scripts_dir / "postinstall"
        postinst.write_text(postinstall_script(), encoding="utf-8")
        _make_executable(postinst)

        component_plist_path = tmp_path / "component.plist"
        component_plist_path.write_bytes(component_plist())

        component_name = f"{PACKAGE_NAME}-{spec['id']}-component.pkg"
        component_path = tmp_path / component_name
        _run_pkgbuild(
            staging=staging,
            spec=spec,
            version_label=version_label,
            scripts_dir=scripts_dir,
            component_plist_path=component_plist_path,
            component_path=component_path,
        )

        resources = tmp_path / "resources"
        resources.mkdir()
        (resources / "welcome.txt").write_text(
            welcome_text(label=version_label, spec=spec), encoding="utf-8"
        )
        if LICENSE_FILE.is_file():
            shutil.copy2(LICENSE_FILE, resources / "LICENSE")
        else:
            (resources / "LICENSE").write_text("MIT\n", encoding="utf-8")

        dist_path = tmp_path / "distribution.xml"
        dist_path.write_text(
            distribution_xml(label=version_label, spec=spec, component_file=component_name),
            encoding="utf-8",
        )

        pkg_name = versioned_pkg_name(version_label, arch=spec["id"])
        pkg_path = out_dir / pkg_name
        product_cmd = [
            "productbuild",
            "--distribution",
            str(dist_path),
            "--resources",
            str(resources),
            "--package-path",
            str(tmp_path),
            str(pkg_path),
        ]
        print("+", " ".join(product_cmd), flush=True)
        subprocess.run(product_cmd, check=True)
        alias = out_dir / spec["stable_name"]
        shutil.copy2(pkg_path, alias)
        print(f"Built {pkg_path} ({pkg_path.stat().st_size} bytes)")
        print(f"Alias {alias}")
        print(f"Minimum macOS: {MIN_OS_VERSION}  arch: {spec['display_arch']}")
        return pkg_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arch",
        required=True,
        help="intel (x86_64, macOS 13+) or apple-silicon (arm64)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for the .pkg (default: installers/)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="VERSION label override (default: VERSION file)",
    )
    parser.add_argument(
        "--skip-runtime",
        action="store_true",
        help="Stage app files without downloading CPython (layout tests only)",
    )
    parser.add_argument(
        "--stage-dir",
        default=None,
        help="Only populate a staging tree; do not run pkgbuild",
    )
    args = parser.parse_args(argv)
    try:
        spec = arch_spec(args.arch)
        label = args.version
        if args.stage_dir:
            staging = Path(args.stage_dir)
            stage_package(
                staging,
                label=(label or read_version_label()).strip(),
                arch=spec["id"],
                bundle_python=not args.skip_runtime,
                install_deps=not args.skip_runtime,
            )
            print(f"Staged {staging} ({spec['display_arch']})")
            return 0
        output = Path(args.output_dir) if args.output_dir else None
        build_pkg(
            arch=spec["id"],
            output_dir=output,
            label=label,
            bundle_python=not args.skip_runtime,
            install_deps=not args.skip_runtime,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
