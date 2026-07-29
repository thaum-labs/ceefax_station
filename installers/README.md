# Ceefax Station Installers

This directory contains Windows installer executables for Ceefax Station.

## Current Installer

- **CeefaxStation-Setup-0.1.2.exe** - Version 0.1.2-alpha (bundles Dire Wolf 1.8.1 for live RX)
- **CeefaxStation-Setup-0.1.1.exe** - Version 0.1.1-alpha (previous)
- **CeefaxStation-Setup-0.1.0.exe** - Version 0.1.0-alpha (previous)

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

5. **Commit and push** (only when you intend to publish):
   ```bash
   git add installers/
   git commit -m "Add installer for version X.X.X"
   git push
   ```

6. **Publish a GitHub Release** (required for the website Download button):

   The site path `/download` redirects to:

   `https://github.com/thaum-labs/ceefax_station/releases/latest/download/CeefaxStation-Setup.exe`

   So each release must include a **stable-named** asset as well as the versioned one:

   ```powershell
   $ver = "0.1.2"   # match the Setup filename / tag without -alpha
   $setup = "installers\CeefaxStation-Setup-$ver.exe"
   Copy-Item $setup "$env:TEMP\CeefaxStation-Setup.exe" -Force

   gh release create "v$ver" $setup "$env:TEMP\CeefaxStation-Setup.exe" `
     --title "$ver-alpha" `
     --notes "Windows installer for Ceefax Station $ver-alpha." `
     --target main
   ```

   If the release already exists, upload/replace the alias:

   ```powershell
   gh release upload "v$ver" "$env:TEMP\CeefaxStation-Setup.exe" --clobber
   ```

   Without `CeefaxStation-Setup.exe` on the **latest** release, **Download app** on ceefaxstation.com will 404.

## Notes

- Installers are built using PyInstaller and Inno Setup
- The installer bundles the app EXE (Python runtime) plus Dire Wolf for live RX
- Installers may lag behind the latest code on GitHub
- Users can always use the manual installation method for the latest code
- Website download always uses the latest GitHub release’s `CeefaxStation-Setup.exe` alias (not a file served from the droplet)
