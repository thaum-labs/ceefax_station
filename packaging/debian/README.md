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

Optional live RX:

```bash
sudo apt install direwolf alsa-utils
```
