# Ceefax Station (core app)

Ceefax/Teletext-style information broadcast system. **Windows and Linux** are supported (Debian package or from source). Raspberry Pi remains useful for radio TX/RX.

## Overview

- Pages defined as JSON under `pages/`
- JSON pages compiled into 50×23 teletext-like text frames
- Carousel scheduler cycles through pages for TX
- Audio / AX.25 encoders produce WAV streams for AFSK transmission
- Responsive curses terminal viewer with TX / RX modes
- Durable live-data providers with last-known-good caching

This is **not** a full broadcast Teletext encoder. It provides a Ceefax-style page format, carousel, AX.25 packaging, and AFSK audio suitable for amateur radio use.

## Requirements

- Python 3.11+ recommended (3.11 preferred on Windows for character support)
- Windows: `pip install windows-curses`
- Optional: Dire Wolf for live RX decode

```bash
pip install -r requirements.txt
```

## Configuration

Edit `config.toml` (typically `ceefax/config.toml` when present locally — it is gitignored):

- `general.mode`: `"audio"` or `"ax25"`
- `general.page_dir` — directory containing JSON pages
- `audio.*` — tone / sample-rate / output (`files` or `stdout`)
- `carousel.*` — page duration (set `page_duration_ms = 0` for continuous stream)

Station identity lives in `radio_config.json`:

```json
{
  "callsign": "YOUR_CALLSIGN",
  "frequency": "2m (144.0-148.0 MHz)",
  "grid": "IO91WM"
}
```

### Optional provider credentials

Read from environment variables. Never commit secrets.

| Variable | Pages | Provider |
|---|---:|---|
| `GUARDIAN_API_KEY` | 200–202 | Guardian Open Platform (BBC RSS fallback) |
| `FOOTBALL_DATA_API_KEY` | 301–304 | football-data.org v4 |
| `LOTTERY_RESULTS_API_KEY` | 402 | Lottery Results Feed (`lotto` + `euromillions`, UK) |
| `TMDB_API_KEY` | 504 | The Movie Database v3 |
| `CEEFAX_PROVIDER_CACHE` | all live pages | Optional cache directory override |

Lottery free tier allows **100 calls/month**. Each live refresh makes **two** calls; successful results are reused for **24 hours**. Stale cache is kept if the key or service fails.

```bash
export GUARDIAN_API_KEY="..."
export FOOTBALL_DATA_API_KEY="..."
export LOTTERY_RESULTS_API_KEY="..."
export TMDB_API_KEY="..."
```

`MET_OFFICE_API_KEY` is reserved for a future Met Office DataHub integration and is not used today.

## Running

From the **repo root**:

```bash
python -m ceefaxstation debug --refresh --view
```

Debug mode refreshes live feeds/pages and opens the terminal viewer (no RF).

### CLI

```bash
# Debug viewer
python -m ceefaxstation debug --refresh --view

# RX: decode latest AX.25 WAV
python -m ceefaxstation rx latest --listener M7TJF

# RX: live soundcard via Dire Wolf
python -m ceefaxstation rx live --device USB --listener M7TJF

# TX: hourly (refresh before :00, generate WAV, play on the hour)
python -m ceefaxstation tx hourly --refresh-lead 300 --carousel-loops 3 --play --play-loops 1
```

Legacy `python -m ceefax ...` commands still map onto `ceefaxstation`.

## Terminal viewer

```bash
python -m ceefax.src.viewer
```

Controls:
- Type any three-digit page number (for example `503`)
- `n` / Right / Page Down — next page
- `p` / Left / Page Up — previous page
- `r` — receive mode
- `t` — transmit mode
- `F5` — reload pages from disk
- `Esc` / `q` — exit or return from TX/RX

Designed for authentic classic Ceefax look on **80×24** and larger terminals.

## Hub page packs

By default stations use `CEEFAX_PAGES_SOURCE=auto`:

1. Download shared pages from `CEEFAX_PAGES_HUB_URL` (default `https://ceefaxstation.com`)
2. Refresh local-only pages **102** and **700** on the station
3. If the hub is unreachable, fall back to a full local `update_all()`

```bash
ceefaxstation pages pull
ceefaxstation debug --refresh --view --pages-source auto
```

Shared pages come from the official hub at [ceefaxstation.com](https://ceefaxstation.com). Stations should not run their own hub/website.

## Live data pages

Providers write pages atomically and keep a last-known-good cache under `cache/providers/` (override with `CEEFAX_PROVIDER_CACHE`).

| Pages | Source notes |
|---|---|
| 101–103 | Open-Meteo (no key) |
| 200–202 | Guardian if keyed, else BBC RSS |
| 300 | BBC Sport RSS |
| 301–304 | football-data.org (key required for live tables/scores/fixtures) |
| 305 | BBC RSS aggregated |
| 400 | Frankfurter / ECB |
| 401 | TfL |
| 402 | Lottery Results Feed |
| 500 / 602 | Fact / quiz APIs + cache |
| 501 | Bundled public-domain quotes |
| 502 | Wikimedia On This Day |
| 503 | TVMaze full schedule (BBC One/Two, ITV1, Channel 4; 24h window) |
| 504 | TMDB |
| 600 | JokeAPI + local fallback |
| 700 | PSK Reporter |

Bulk refresh:

```bash
python -m ceefax.src.update_all
```

Or single updaters, for example:

```bash
python -m ceefax.src.update_news_page
python -m ceefax.src.update_football_page
python -m ceefax.src.update_lottery_page
python -m ceefax.src.update_film_picks_page
```

## JSON page format

```json
{
  "page": "100",
  "title": "News Headlines",
  "timestamp": "2026-07-28T12:34:00Z",
  "subpage": 1,
  "content": [
    "Headline one goes here.",
    "Headline two goes here."
  ]
}
```

- `page`: `"000"`–`"999"`
- `subpage`: optional integer
- `title`: single-line title
- `timestamp`: ISO 8601 (or source label)
- `content`: lines padded/wrapped to 50 columns

## Linux / Raspberry Pi notes

Install the Debian package (recommended):

```bash
python scripts/build_debian_package.py
sudo apt install ./installers/ceefax-station.deb
ceefaxstation
```

Or run from a git checkout as on other platforms. Example continuous VOX stream:

- `audio.output = "stdout"`
- `carousel.page_duration_ms = 0`

```bash
python -m src.main | aplay -f S16_LE -c 1 -r 48000
```

Optional systemd user unit ships in the Debian package as `ceefax-station.service`. Sample unit: `service/ceefax.service`.

```bash
systemctl --user enable --now ceefax-station.service
```

## Related docs

- Root [README.md](../README.md) — installers, screenshots, tracker upload
- Live map: [ceefaxstation.com](https://ceefaxstation.com)
