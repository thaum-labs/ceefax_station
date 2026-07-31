<p align="center">
  <img src="screenshots/ceefax-station-logo.png" alt="Ceefax Station" width="220" />
</p>

# Ceefax Station

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License" /></a>
  <img src="https://img.shields.io/badge/version-0.1.4--alpha-orange" alt="Version 0.1.4-alpha" />
  <img src="https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white" alt="Windows" />
  <br/>
  <img src="https://img.shields.io/badge/AX.25-AFSK1200-0B3D0B" alt="AX.25 AFSK1200" />
  <img src="https://img.shields.io/badge/Dire%20Wolf-packet%20radio-2E8B57" alt="Dire Wolf" />
  <img src="https://img.shields.io/badge/curses-TUI-111111" alt="curses TUI" />
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-tracker%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="https://leafletjs.com/"><img src="https://img.shields.io/badge/Leaflet-map-199900?logo=leaflet&logoColor=white" alt="Leaflet" /></a>
  <a href="https://docs.pytest.org/"><img src="https://img.shields.io/badge/pytest-tested-0A9EDC?logo=pytest&logoColor=white" alt="pytest" /></a>
</p>

## What is this?

Old-school **Ceefax** teletext pages — on your PC, and optionally over amateur radio.

With Ceefax Station you can:

1. Browse live-style pages (weather, news, football, TV, lottery, …)
2. Transmit those pages over radio (licensed operators)
3. Receive pages from other stations
4. Appear on the public map: [ceefaxstation.com](https://ceefaxstation.com)

**You do not need API keys.** Stations download a shared page pack from ceefaxstation.com automatically.  
**You do not need a radio** just to try the viewer.

> Alpha software — it works, but things may still change.

---

## Screenshots

<table>
  <tr>
    <td align="center"><img src="screenshots/ceefax-terminal/page-000.png" width="260" alt="Start" /><br/><sub>Start</sub></td>
    <td align="center"><img src="screenshots/ceefax-terminal/page-101.png" width="260" alt="Weather" /><br/><sub>Weather</sub></td>
    <td align="center"><img src="screenshots/ceefax-terminal/page-200.png" width="260" alt="News" /><br/><sub>News</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="screenshots/ceefax-terminal/page-304.png" width="260" alt="Football" /><br/><sub>Football</sub></td>
    <td align="center"><img src="screenshots/ceefax-terminal/page-402.png" width="260" alt="Lottery" /><br/><sub>Lottery</sub></td>
    <td align="center"><img src="screenshots/ceefax-terminal/page-504.png" width="260" alt="Films" /><br/><sub>Films</sub></td>
  </tr>
</table>

![Station map](screenshots/desktop-tracker.png)

---

## Quick start (recommended)

Best way to get the **latest** version: install from GitHub. Windows installs can also self-update later (`U` in the viewer or `ceefaxstation update`).

### 1. Install Python 3.11

- Download: [python.org/downloads](https://www.python.org/downloads/)
- On Windows: tick **Add Python to PATH**

### 2. Download Ceefax Station

```bash
git clone https://github.com/thaum-labs/ceefax_station.git
cd ceefax_station
```

No Git? On GitHub click the green **Code → Download ZIP**, then unzip.

### 3. Install packages

```bash
python -m pip install -r ceefax/requirements.txt
```

On Windows also run:

```bash
python -m pip install windows-curses
```

### 4. Set your station name

Edit `ceefax/radio_config.json`:

```json
{
  "callsign": "YOUR_CALLSIGN",
  "frequency": "2m (144.0-148.0 MHz)",
  "grid": "IO91WM"
}
```

- **callsign** — your amateur callsign, or any short name for testing  
- **grid** — Maidenhead locator (e.g. `IO91WM`) so you can appear on the map  
- **frequency** — only needed if you transmit

### 5. Run it

```bash
python -m ceefaxstation debug --refresh --view
```

That will:

1. Download shared pages from [ceefaxstation.com](https://ceefaxstation.com) (no keys needed)
2. Update your local weather / callsign pages
3. Open the Ceefax viewer

---

## Using the viewer

| Key | What it does |
| --- | --- |
| Type `101`, `200`, `304`… | Go to that page |
| `n` or → | Next page |
| `p` or ← | Previous page |
| `F5` | Reload pages (hub pack if newer) |
| `U` | Check GitHub and update the Windows app |
| `t` | Transmit menu |
| `r` | Receive menu |
| `s` | Station setup |
| `Esc` or `q` | Back / quit |

Useful pages: **101** weather · **200** news · **304** football · **402** lottery · **503** TV · **504** films

---

## Pages without doing anything fancy

By default, refresh uses the **hub page pack**:

```bash
python -m ceefaxstation pages pull
python -m ceefaxstation debug --refresh --view
```

| What | Where it comes from |
| --- | --- |
| News, sport, lottery, TV, films, UK weather… | Downloaded from ceefaxstation.com |
| Local weather (102) | Updated on your PC |
| Callsign / radio page (700) | Updated on your PC |

If the hub is briefly down, Ceefax falls back to building pages on your PC (some pages then need API keys — usually you can ignore this).

---

## Optional: Windows installer

There is an installer in [`installers/`](installers/) (`CeefaxStation-Setup-0.1.4.exe`).

The website **Download app** button (`https://ceefaxstation.com/download`) always redirects to the GitHub **latest** release asset named `CeefaxStation-Setup.exe`. Pushing a new installer to `main` publishes that release automatically (versioned file + stable alias) — see [`installers/README.md`](installers/README.md).

Once installed, the app can upgrade itself from GitHub Releases: press **U** in the viewer, or run `ceefaxstation update` (no uninstall required).

It is the easiest install (bundles the app **and Dire Wolf** for live RX). After install, use **U** / `ceefaxstation update` to pull newer GitHub Releases without uninstalling. Prefer the Quick start above if you want bleeding-edge source.

---

## Radio (TX / RX)

You need a valid licence, a radio, and audio into the PC. For live receive decode you need [Dire Wolf](https://github.com/wb2osz/direwolf) — the Windows installer bundles it under `ceefax/tools/direwolf`. Manual installs should put `direwolf.exe` on `PATH` or in that folder.

```bash
# Transmit once
python -m ceefaxstation tx now --play

# Transmit every hour (refreshes pages first)
python -m ceefaxstation tx hourly --play

# Receive latest WAV / live audio
python -m ceefaxstation rx latest
python -m ceefaxstation rx live
```

In the interactive viewer, **T** transmits now (3 loops) and then **stays armed**: it refreshes before the next hour and retransmits at `:00` until you press ESC.

### Appear on the map

After a TX or RX session, Ceefax Station **automatically uploads** the new log to [ceefaxstation.com](https://ceefaxstation.com) (needs `callsign` + `grid` in `radio_config.json`).

You can still run a background watcher if you prefer:

```bash
python -m ceefaxstation upload
```

Or on Windows: `.\start_uploader.ps1`

Disable automatic uploads with environment variable `CEEFAX_AUTO_UPLOAD=0`.

---

## Page guide

| Pages | Content |
| --- | --- |
| 101–103 | Weather + UK map |
| 200–202 | News |
| 300–305 | Sport / football |
| 400–402 | Money, travel, lottery |
| 500–504 | Facts, quotes, TV, films |
| 600–602 | Jokes, art, quiz |
| 700 | Radio / callsign activity |
| 900 | About |

---

## Mini glossary

| Word | Meaning |
| --- | --- |
| **Hub / page pack** | Shared pages hosted on ceefaxstation.com so stations don’t need API keys |
| **Callsign** | Your amateur radio ID |
| **Grid** | Short location code for the map (Maidenhead) |
| **TX / RX** | Transmit / receive |
| **AX.25** | Packet radio format used to send pages as audio |

---

## Helpful links

- Live map + hub: [ceefaxstation.com](https://ceefaxstation.com)
- Extra technical notes: [ceefax/README.md](ceefax/README.md)
- Licence: [MIT](LICENSE)

---

## For developers

<details>
<summary>Click to expand</summary>

```
ceefax/           station app, page updaters, viewer
ceefaxstation/    CLI (`python -m ceefaxstation ...`)
ceefaxweb/        official site source (ceefaxstation.com — not for self-hosting)
installers/       Windows setup .exe (may lag main)
```

```bash
python -m pytest
```

**Hub page pack note:** the official site refreshes shared teletext pages about every **2 hours**. That cadence (plus provider cache TTLs and request pacing) is sized for free API rate limits used by the hub — notably football-data.org (10 req/min), Guardian developer (500/day), Lottery Results Feed free (100/month), and Open-Meteo (10k/day). Stations still pull the published pack; they do not need those API keys.

</details>

---

Created by **M7TJF**

**Ceefax Station** — old-school teletext, new-school packet radio
