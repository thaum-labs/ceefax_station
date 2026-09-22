# Ceefax Station Installers

This directory contains installer artifacts for Ceefax Station.

## Current Linux installer

- **ceefax-station_0.1.9~alpha-1_all.deb** — Version 0.1.9-alpha (and `ceefax-station.deb` alias)

```bash
sudo apt install ./installers/ceefax-station.deb
ceefaxstation
```

## Linux (Debian package)

Build from the repo (Debian, Ubuntu, Raspberry Pi OS):

```bash
python scripts/build_debian_package.py
```

Output:

- `installers/ceefax-station_<version>-1_all.deb`
- `installers/ceefax-station.deb` (stable alias)

Install:

```bash
sudo apt install ./installers/ceefax-station.deb
ceefaxstation
```

Website **Download Linux** (`https://ceefaxstation.com/download/linux`) redirects to the GitHub latest-release asset `ceefax-station.deb` (tag **v0.1.9**).

Direct from `main`:

https://github.com/thaum-labs/ceefax_station/raw/main/installers/ceefax-station.deb

See [`packaging/debian/README.md`](../packaging/debian/README.md).

## Current macOS installers

Built on GitHub Actions (not stored in git — the `.pkg` files are large and need macOS `pkgbuild`):

- **CeefaxStation-Intel.pkg** — Intel x86_64, **macOS 13 Ventura** and later
- **CeefaxStation-AppleSilicon.pkg** — Apple Silicon (arm64), macOS 13+

```bash
# Apple Silicon
curl -L -o CeefaxStation-AppleSilicon.pkg \
  https://github.com/thaum-labs/ceefax_station/releases/latest/download/CeefaxStation-AppleSilicon.pkg
sudo installer -pkg ./CeefaxStation-AppleSilicon.pkg -target /
ceefaxstation
```

Website **Download Mac** (`https://ceefaxstation.com/download/mac`) links both packages.
Direct Intel: `https://ceefaxstation.com/download/mac/intel`
Direct Apple Silicon: `https://ceefaxstation.com/download/mac/apple-silicon`

See [`packaging/macos/README.md`](../packaging/macos/README.md).

## Current Windows installer

- **CeefaxStation-Setup-0.1.9.exe** - Version 0.1.9-alpha (HF transmit paces by frame time and no longer aborts while modem73 is sending; in-app self-update from GitHub Releases)
- **CeefaxStation-Setup-0.1.8.exe** - Version 0.1.8-alpha (HF transmit no longer drops frames after 256; in-app self-update from GitHub Releases)
- **CeefaxStation-Setup-0.1.7.exe** - Version 0.1.7-alpha (HF modem73 path; in-app self-update from GitHub Releases)
- **CeefaxStation-Setup-0.1.4.exe** - Version 0.1.4-alpha (in-app self-update from GitHub Releases)
- **CeefaxStation-Setup-0.1.3.exe** - Version 0.1.3-alpha (ASCII art + football table off-season fix)
- **CeefaxStation-Setup-0.1.2.exe** - Version 0.1.2-alpha (bundles Dire Wolf 1.8.1 for live RX)
- **CeefaxStation-Setup-0.1.1.exe** - Version 0.1.1-alpha (previous)
- **CeefaxStation-Setup-0.1.0.exe** - Version 0.1.0-alpha (previous)

## Updating an installed app

Installed stations can upgrade without uninstalling:

- In the viewer: press **U**, confirm, approve UAC if prompted
- From a terminal: `ceefaxstation update` (or `ceefaxstation update --check`)

This downloads the platform installer from the latest GitHub Release (Windows Setup EXE, Linux `.deb`, or macOS `.pkg`) and runs the upgrade.

## Building New Installers

When you want to create a new installer for a new version:

1. **Update the version** (if needed):
   - Update `VERSION` file in the repository root
   - Update `CHANGELOG.json` with new changes

2. **Build the installer**:
   ```powershell
   cd "C:\Users\tobot\Documents\Ceefax Station App\ceefax-installer-build"
   .\build_installer.ps1 -RepoRoot "C:\Users\tobot\Documents\GitHub\ceefax_station"
   ```

   The build script downloads Dire Wolf (Windows x64) into `vendor\direwolf` and modem73-win into `vendor\modem73`. Inno Setup installs them to `{app}\ceefax\tools\direwolf` and `{app}\ceefax\tools\modem73`. modem73 is only launched when the station band is HF.

3. **Output locations**:
   - Build output: `...\ceefax-installer-build\dist\CeefaxStation-Setup-X.X.X.exe`
   - Automatically copied to: `installers\CeefaxStation-Setup-X.X.X.exe`

4. **Remove the old installer** (if replacing):
   ```powershell
   Remove-Item "installers\CeefaxStation-Setup-OLD_VERSION.exe"
   ```

5. **Commit and push** (publishes the release automatically):
   ```bash
   git add installers/ VERSION CHANGELOG.json
   git commit -m "Ship installer for version X.X.X"
   git push
   ```

   Pushing a new `installers/CeefaxStation-Setup-*.exe` (or `VERSION` / changelog) to `main`
   runs **Publish installer release**, which creates/updates the GitHub Release with:

   - `CeefaxStation-Setup-X.Y.Z.exe`
   - `CeefaxStation-Setup.exe` (stable alias)
   - `ceefax-station.deb` when a Debian package is present in `installers/`
   - `CeefaxStation-Intel.pkg` / `CeefaxStation-AppleSilicon.pkg` when Mac packages are present

   Windows download: `https://ceefaxstation.com/download`
   (`…/releases/latest/download/CeefaxStation-Setup.exe`).

   Linux download: `https://ceefaxstation.com/download/linux`
   (`…/releases/latest/download/ceefax-station.deb`).

   Mac download: `https://ceefaxstation.com/download/mac`
   (`…/releases/latest/download/CeefaxStation-Intel.pkg` and `CeefaxStation-AppleSilicon.pkg`).

   Manual / local publish (same script CI uses):

   ```powershell
   python scripts/publish_github_release.py
   # or
   python scripts/publish_github_release.py --version 0.1.2-alpha
   ```

   Or run the workflow from GitHub Actions → **Publish installer release** → Run workflow.

## Building macOS installers

On a Mac (or via **Build macOS installers** in GitHub Actions):

```bash
python scripts/build_macos_package.py --arch intel
python scripts/build_macos_package.py --arch apple-silicon
```

Intel packages set `LSMinimumSystemVersion` / installer `os-version` to **13.0** and bundle the x86_64 CPython standalone runtime. Apple Silicon packages bundle the arm64 runtime.

## Notes

- Windows Setup EXEs are built with PyInstaller and Inno Setup (app + Dire Wolf + modem73)
- Linux `.deb` files are built with `python scripts/build_debian_package.py` (system Python)
- macOS `.pkg` files are built on GitHub Actions with `python scripts/build_macos_package.py` (bundled CPython 3.11)
- Installers may lag behind the latest code on GitHub
- Users can always use the manual installation method for the latest code
- Website **Download Windows** always uses the latest GitHub release’s `CeefaxStation-Setup.exe` alias
- Website **Download Linux** always uses the latest GitHub release’s `ceefax-station.deb` alias
- Website **Download Mac** always uses the latest GitHub release’s `CeefaxStation-Intel.pkg` and `CeefaxStation-AppleSilicon.pkg` aliases
- Do **not** skip the GitHub Release step: without the stable alias on the latest release, **Download app** on ceefaxstation.com will 404
