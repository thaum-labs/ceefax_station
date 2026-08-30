# Ceefax Station Installers

This directory contains installer artifacts for Ceefax Station.

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

Website **Download Linux** (`https://ceefaxstation.com/download/linux`) redirects to the GitHub latest-release asset `ceefax-station.deb`.

See [`packaging/debian/README.md`](../packaging/debian/README.md).

## Current Windows installer

- **CeefaxStation-Setup-0.1.4.exe** - Version 0.1.4-alpha (in-app self-update from GitHub Releases)
- **CeefaxStation-Setup-0.1.3.exe** - Version 0.1.3-alpha (ASCII art + football table off-season fix)
- **CeefaxStation-Setup-0.1.2.exe** - Version 0.1.2-alpha (bundles Dire Wolf 1.8.1 for live RX)
- **CeefaxStation-Setup-0.1.1.exe** - Version 0.1.1-alpha (previous)
- **CeefaxStation-Setup-0.1.0.exe** - Version 0.1.0-alpha (previous)

## Updating an installed app

Installed stations can upgrade without uninstalling:

- In the viewer: press **U**, confirm, approve UAC if prompted
- From a terminal: `ceefaxstation update` (or `ceefaxstation update --check`)

This downloads `CeefaxStation-Setup.exe` from the latest GitHub Release and runs the silent Setup upgrade.

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

   The build script downloads Dire Wolf (Windows x64) into `vendor\direwolf` and Inno Setup installs it to `{app}\ceefax\tools\direwolf`.

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
   runs **Publish Windows installer release**, which creates/updates the GitHub Release with:

   - `CeefaxStation-Setup-X.Y.Z.exe`
   - `CeefaxStation-Setup.exe` (stable alias)
   - `ceefax-station.deb` when a Debian package is present in `installers/`

   Windows download: `https://ceefaxstation.com/download`
   (`…/releases/latest/download/CeefaxStation-Setup.exe`).

   Linux download: `https://ceefaxstation.com/download/linux`
   (`…/releases/latest/download/ceefax-station.deb`).

   Manual / local publish (same script CI uses):

   ```powershell
   python scripts/publish_github_release.py
   # or
   python scripts/publish_github_release.py --version 0.1.2-alpha
   ```

   Or run the workflow from GitHub Actions → **Publish Windows installer release** → Run workflow.

## Notes

- Installers are built using PyInstaller and Inno Setup
- The installer bundles the app EXE (Python runtime) plus Dire Wolf for live RX
- Installers may lag behind the latest code on GitHub
- Users can always use the manual installation method for the latest code
- Website **Download Windows** always uses the latest GitHub release’s `CeefaxStation-Setup.exe` alias
- Website **Download Linux** always uses the latest GitHub release’s `ceefax-station.deb` alias
- Do **not** skip the GitHub Release step: without the stable alias on the latest release, **Download app** on ceefaxstation.com will 404
