<p align="center">
  <img src="screenshots/readme-logo.png" alt="Ceefax Station" width="260" />
</p>

# Ceefax Station

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License" /></a>
  <img src="https://img.shields.io/badge/version-0.1.0--alpha-orange" alt="Version 0.1.0-alpha" />
  <img src="https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white" alt="Windows" />
  <br/>
  <img src="https://img.shields.io/badge/AX.25-AFSK1200-0B3D0B" alt="AX.25 AFSK1200" />
  <img src="https://img.shields.io/badge/Dire%20Wolf-packet%20radio-2E8B57" alt="Dire Wolf" />
  <img src="https://img.shields.io/badge/curses-TUI-111111" alt="curses TUI" />
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-tracker%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="https://leafletjs.com/"><img src="https://img.shields.io/badge/Leaflet-map-199900?logo=leaflet&logoColor=white" alt="Leaflet" /></a>
  <a href="https://docs.pytest.org/"><img src="https://img.shields.io/badge/pytest-tested-0A9EDC?logo=pytest&logoColor=white" alt="pytest" /></a>
</p>

A modern recreation of the classic Ceefax teletext service for Windows amateur radio stations: live data pages, AX.25 packet radio TX/RX, a responsive terminal viewer, and a public web tracker.

## Features

### Teletext Pages
- **Weather** — UK forecasts, local weather, UK weather map (Open-Meteo)
- **News** — Headlines, UK, and world news (Guardian API with BBC RSS fallback)
- **Sport** — Headlines, live scores, league tables, fixtures (football-data.org + BBC RSS)
- **Entertainment** — TV highlights (TVMaze), film picks (TMDB), facts, quotes, jokes, quiz
- **Finance / travel** — Exchange rates, lottery results, TfL travel info
- **Radio** — Callsign / PSK Reporter activity on page 700

Live pages use durable providers with **last-known-good caching**. If a feed is down, Ceefax keeps showing the last good page and marks it stale instead of blanking out.

### Packet Radio (AX.25)
- Transmit pages via AFSK1200
- Receive and decode AX.25 packets (Dire Wolf)
- Hourly automatic TX with page refresh **before** the hour, then play on `:00`
- In-terminal TX / RX dashboards

### Terminal Viewer
- Authentic Ceefax-style layout
- Works in standard **80×24** PowerShell windows and larger terminals
- Three-digit page entry, unified Esc behaviour, TX/RX modes from the TUI

### Web Tracker
- Public map of transmitting and receiving stations
- Maidenhead grid squares and station-to-station links
- Live at [ceefaxstation.com](https://ceefaxstation.com)

## Screenshots

### Terminal viewer

<table>
  <tr>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-000.png">
        <img src="screenshots/ceefax-terminal/page-000.png" width="260" alt="Page 000 (Start)" />
      </a>
      <br/><sub><b>Page 000</b> — Start</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-101.png">
        <img src="screenshots/ceefax-terminal/page-101.png" width="260" alt="Weather (Page 101)" />
      </a>
      <br/><sub><b>Page 101</b> — Weather</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-103.png">
        <img src="screenshots/ceefax-terminal/page-103.png" width="260" alt="UK Weather Map (Page 103)" />
      </a>
      <br/><sub><b>Page 103</b> — UK weather map</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-200.png">
        <img src="screenshots/ceefax-terminal/page-200.png" width="260" alt="News (Page 200)" />
      </a>
      <br/><sub><b>Page 200</b> — News</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-304.png">
        <img src="screenshots/ceefax-terminal/page-304.png" width="260" alt="Football (Page 304)" />
      </a>
      <br/><sub><b>Page 304</b> — Fixtures</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-402.png">
        <img src="screenshots/ceefax-terminal/page-402.png" width="260" alt="Lottery (Page 402)" />
      </a>
      <br/><sub><b>Page 402</b> — Lottery</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-503.png">
        <img src="screenshots/ceefax-terminal/page-503.png" width="260" alt="TV Highlights (Page 503)" />
      </a>
      <br/><sub><b>Page 503</b> — TV highlights</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-504.png">
        <img src="screenshots/ceefax-terminal/page-504.png" width="260" alt="Film Picks (Page 504)" />
      </a>
      <br/><sub><b>Page 504</b> — Film picks</sub>
    </td>
    <td></td>
  </tr>
</table>

### Web tracker

![Desktop tracker](screenshots/desktop-main.png)

| Mobile map | Mobile panel |
| --- | --- |
| <img src="screenshots/mobile-map.png" width="220" alt="Mobile map" /> | <img src="screenshots/mobile-panel-expanded.png" width="220" alt="Mobile panel" /> |

## Quick Start

### Prerequisites
- **Python 3.11** (required for special-character support)
- **Windows** (primary supported platform)
- Optional: Dire Wolf for live RX decode

### Installation

#### Option 1: Windows Installer

1. Download the latest installer from `installers/` (for example `CeefaxStation-Setup-0.1.0.exe`)
2. Run the setup wizard
3. Configure callsign / frequency / grid via Start Menu → **Configure Station**, or edit `ceefax/radio_config.json`

The packaged installer can lag behind GitHub `main`. For the newest code, use Option 2.

#### Option 2: From Git

```bash
git clone https://github.com/thaum-labs/ceefax_station.git
cd ceefax_station
python -m pip install -r ceefax/requirements.txt
```

On Windows, also install curses support:

```bash
python -m pip install windows-curses
```

Edit `ceefax/radio_config.json`:

```json
{
  "callsign": "YOUR_CALLSIGN",
  "frequency": "2m (144.0-148.0 MHz)",
  "grid": "IO91WM"
}
```

### Optional API keys

Most pages work without keys. These unlock richer / required live sources:

| Variable | Pages | Provider | Free? |
|---|---:|---|---|
| `GUARDIAN_API_KEY` | 200–202 | Guardian Open Platform (BBC RSS fallback) | Yes (non-commercial) |
| `FOOTBALL_DATA_API_KEY` | 301–304 | football-data.org | Yes (free tier) |
| `LOTTERY_RESULTS_API_KEY` | 402 | Lottery Results Feed | Yes (100 calls/month) |
| `TMDB_API_KEY` | 504 | The Movie Database | Yes (non-commercial) |
| `CEEFAX_PROVIDER_CACHE` | all | Optional cache directory override | — |

**macOS / Linux** (add to `~/.zshrc` or `~/.bashrc`):

```bash
export GUARDIAN_API_KEY="..."
export FOOTBALL_DATA_API_KEY="..."
export LOTTERY_RESULTS_API_KEY="..."
export TMDB_API_KEY="..."
```

**Windows PowerShell** (permanent for your user; reopen the terminal after):

```powershell
[Environment]::SetEnvironmentVariable("GUARDIAN_API_KEY", "...", "User")
[Environment]::SetEnvironmentVariable("FOOTBALL_DATA_API_KEY", "...", "User")
[Environment]::SetEnvironmentVariable("LOTTERY_RESULTS_API_KEY", "...", "User")
[Environment]::SetEnvironmentVariable("TMDB_API_KEY", "...", "User")
```

Do **not** commit API keys to the repository.

Lottery tip: each live refresh uses **2** API calls. Successful results are reused for 24 hours so the free monthly quota lasts.

## Usage

### Viewer (debug)
```bash
ceefaxstation debug --view
ceefaxstation debug --refresh --view
```

Viewer controls:
- Type a **three-digit** page number (for example `503`)
- `n` / Right / Page Down — next page
- `p` / Left / Page Up — previous page
- `r` — receive mode · `t` — transmit mode
- `F5` — reload pages from disk
- `Esc` / `q` — exit or leave TX/RX

### Receive
```bash
ceefaxstation rx latest
ceefaxstation rx live
```

### Transmit
```bash
ceefaxstation tx now --play
ceefaxstation tx hourly --play
```

Hourly mode refreshes pages shortly before the hour, prepares the WAV, then plays on the hour.

### Upload logs to the web tracker

No token required — uploads go to the public tracker:

```bash
ceefaxstation upload
```

Or:

```powershell
.\start_uploader.ps1
```

## Project Structure

```
.
├── ceefax/                 # Station app, pages, providers, viewer
│   ├── src/                # Updaters, AX.25, terminal UI
│   ├── pages/              # Generated teletext JSON (local / runtime)
│   ├── cache/providers/    # Last-known-good provider cache
│   └── requirements.txt
├── ceefaxstation/          # CLI entrypoint
├── ceefaxweb/              # Public tracker server (central host)
├── screenshots/            # README images
├── scripts/                # Screenshot / logo generators
└── installers/             # Windows setup builds
```

## Regenerating screenshots

From a machine with refreshed `ceefax/pages/*.json` and Playwright installed:

```bash
python -m pip install playwright
python -m playwright install chromium
python scripts/generate_ceefax_viewer_screenshots.py
python scripts/generate_readme_logo.py
python scripts/generate_tracker_screenshots.py
```

## Development

- Versioning: semantic, currently alpha (`VERSION` + `CHANGELOG.json`)
- Tests: `python -m pytest`
- Preferred base branch: `main`

## License

MIT License — see [LICENSE](LICENSE).

Created by M7TJF

## Links

- **Live Tracker**: [ceefaxstation.com](https://ceefaxstation.com)
- **Repository**: [github.com/thaum-labs/ceefax_station](https://github.com/thaum-labs/ceefax_station)

---

**Ceefax Station** — bringing teletext to the modern era with packet radio
