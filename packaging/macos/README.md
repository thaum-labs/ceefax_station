# macOS packaging

Build a `.pkg` so Ceefax Station can be installed on Macs.

Two architecture-specific installers:

| Installer | CPU | Oldest macOS |
|-----------|-----|----------------|
| `CeefaxStation-Intel.pkg` | Intel (x86_64) | **13 Ventura** |
| `CeefaxStation-AppleSilicon.pkg` | Apple Silicon (arm64) | 13 Ventura |

Each package bundles a relocatable CPython 3.11, so Homebrew / Xcode Python is not required.

Must be built on macOS (`pkgbuild` and `productbuild`). GitHub Actions does this
on an Apple Silicon runner and packages both the Intel and arm64 Python runtimes
without executing them.

```bash
python scripts/build_macos_package.py --arch intel
python scripts/build_macos_package.py --arch apple-silicon
```

Output:

- `installers/CeefaxStation-Intel-<version>.pkg` and `installers/CeefaxStation-Intel.pkg` (stable alias)
- `installers/CeefaxStation-AppleSilicon-<version>.pkg` and `installers/CeefaxStation-AppleSilicon.pkg` (stable alias)

Install:

```bash
sudo installer -pkg installers/CeefaxStation-AppleSilicon.pkg -target /
# or open the .pkg in Finder
ceefaxstation
```

Or double-click **Ceefax Station** in `/Applications`.

Runtime data lives in `~/.ceefax_station`.

Optional live RX:

```bash
brew install direwolf
```

Unsigned packages downloaded from the browser may need **System Settings →
Privacy & Security → Open Anyway** the first time.
