# Debian packaging

Build a `.deb` so Ceefax Station can be installed on Debian, Ubuntu, and Raspberry Pi OS.

```bash
python scripts/build_debian_package.py
```

Output:

- `installers/ceefax-station_<version>-1_all.deb`
- `installers/ceefax-station.deb` (stable alias)

Install:

```bash
sudo apt install ./installers/ceefax-station.deb
# or
sudo dpkg -i installers/ceefax-station.deb
sudo apt-get install -f
```

Then run `ceefaxstation` (opens the viewer). Runtime data lives in `~/.ceefax_station`.

Optional live RX on FM (VHF):

```bash
sudo apt install direwolf alsa-utils
```

HF (RDM-600S / RDM-300S) is not inside this package. Debian policy rules out shipping the modem73 binary under `/usr/lib/ceefax-station`. An HF station installs the official build for its CPU instead, then leaves `modem73` on `PATH`:

- https://github.com/RFnexus/modem73/releases — `debian` or `ubuntu` packages for amd64, arm64, and armhf (Raspberry Pi).

A station left on `band = "vhf"` never starts modem73. FM receive stays on the distro `direwolf` package.
