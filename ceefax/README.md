# Ceefax Station Broadcast System

A Ceefax/Teletext-style information broadcast system for Raspberry Pi.

## Overview

- Pages defined as JSON (`pages/*.json`)
-- JSON pages compiled into 50×30 "Teletext-like" text frames
- Carousel scheduler cycles through pages
- Audio encoder converts frames into a simple FSK-like audio stream
- Main loop runs on a Raspberry Pi and can be managed via systemd

**Note:** This is a starter implementation and does **not** implement the full Teletext broadcast spec. It gives you:
- A 50×30 text page format
- A basic page compiler and carousel
- A simple FSK audio generator that writes `.wav` files you can pipe to a transmitter or `aplay`

You can evolve this into proper Teletext line encoding and real-time audio streaming.

## Requirements

- Python 3.9+
- On Raspberry Pi (Linux) for real use

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Edit `config.toml`:

- `general.mode`:
  - `"audio"` – audio output (WAV files or stdout stream)
  - `"ax25"` – (placeholder) for future AX.25 mode
- `general.page_dir` – directory containing JSON pages
- `audio.*` – audio parameters, tone frequencies, etc.
  - `audio.output`:
    - `"files"` – generate per-page WAV files in `out/`
    - `"stdout"` – stream raw PCM to stdout for piping to `aplay`/VOX
- `carousel.*` – how long each page is displayed / transmitted (set `page_duration_ms = 0` for continuous streaming without extra gaps)

Optional provider credentials are read from environment variables and must not
be committed to the repository:

| Variable | Pages | Provider |
|---|---:|---|
| `GUARDIAN_API_KEY` | 200–202 | Guardian Open Platform (BBC RSS fallback) |
| `FOOTBALL_DATA_API_KEY` | 301–304 | football-data.org |
| `LOTTERY_RESULTS_API_KEY` | 402 | Lottery Results Feed |
| `TMDB_API_KEY` | 504 | The Movie Database |
| `CEEFAX_PROVIDER_CACHE` | all live pages | Optional cache directory override |

Page 402 uses the Lottery Results Feed structured API. Set its bearer token in
the environment before refreshing pages:

```bash
export LOTTERY_RESULTS_API_KEY="your-lottery-results-feed-token"
```

The free tier allows 100 calls per month. Each live lottery refresh makes two
calls (Lotto and EuroMillions), so successful results are reused for 24 hours
(about 60 calls per month).
The last-known-good result remains available as a stale fallback if the key or
service is unavailable.

## Running

From the repo root (the directory that contains `ceefax/`):

```bash
python -m ceefaxstation debug --refresh --view
```

This will (debug/viewer mode):

1. Load config from `config.toml`
2. Load pages from `pages/`
3. Compile them to 50×23 page frames
4. Refresh live API feeds/pages
5. Open the terminal viewer (no signal RX/TX processing)

### CLI (new)

All commands start with `ceefaxstation`:

```bash
# Debug viewer mode (refresh + view)
python -m ceefaxstation debug --refresh --view

# RX: decode latest generated AX.25 WAV and view
python -m ceefaxstation rx latest --listener M7TJF

# RX: decode live soundcard input via Dire Wolf and view
python -m ceefaxstation rx live --device USB --listener M7TJF

# TX: hourly scheduler (refresh 5 minutes before the hour, generate WAV, play on the hour)
python -m ceefaxstation tx hourly --refresh-lead 300 --carousel-loops 3 --play --play-loops 1
```

**Note:** The old `python -m ceefax ...` commands still work, but are now a compatibility shim that maps onto `ceefaxstation`.

You can play per-page WAVs with:

```bash
aplay out/page_100.wav
```

For **continuous VOX streaming** (no extra gaps), set:

- `audio.output = "stdout"`
- `carousel.page_duration_ms = 0`

Then run:

```bash
python -m src.main | aplay -f S16_LE -c 1 -r 48000
```

## Text Viewer (Ceefax-style)

There is a responsive terminal viewer that shows the 50×23 frames in an authentic Ceefax-style layout using `curses`. It supports standard 80×24 PowerShell windows and expands cleanly in larger terminals.

From the repo root:

```bash
python -m ceefax.src.viewer
```

Controls:
- Type any three-digit page number (for example `503`) – open that page
- `n` / Right arrow / Page Down – next page
- `p` / Left arrow / Page Up – previous page
- `r` – receive mode
- `t` – transmit mode
- `F5` – reload pages from disk
- `Esc` / `q` – exit or return from TX/RX mode

**Note for Windows:** full `curses` support may require installing `windows-curses` via:

```bash
pip install windows-curses
```

## Live Weather Pages

Pages 101-103 use Open-Meteo's no-key geocoding and forecast APIs. Page 101
contains the six established UK cities, page 102 uses the configured or detected
local location, and page 103 contains the UK map. Successful responses are cached
and a cached response is displayed as stale when the live service is unavailable.
Page files and provider caches are replaced atomically.

`MET_OFFICE_API_KEY` is reserved for a future Met Office DataHub integration. It
is not currently used: DataHub products have endpoint-specific configuration, so
the application deliberately does not guess an endpoint from the key alone.

From the repo root (with your venv active):

```bash
python -m ceefax.src.update_weather_page
```

This builds a Ceefax-style local panel and atomically updates `pages/102.json`.

Then open the viewer and press `F5` to reload pages:

```bash
python -m ceefax.src.viewer
```

## UK Weather Map Page

You can also generate a simple **UK weather map** (with icons and temperatures for a few cities including Frome) on page `103`:

```bash
python -m ceefax.src.update_weather_map_page
```

Then in the viewer, press `F5` and go to **page 103** to see the map.

## Auto-updated News & Football Pages

News pages 200-202 use the Guardian Open Platform when `GUARDIAN_API_KEY` is
set, with the corresponding BBC RSS feed as fallback. Last-known-good headlines
are cached and marked stale if both live providers fail. Set
`CEEFAX_PROVIDER_CACHE` to override the default `ceefax/cache/providers` cache
directory.

### Local news (page 200)

```bash
python -m ceefax.src.update_news_page
```

This fetches Somerset headlines from Guardian (when configured) or BBC RSS and
writes them into `pages/200.json` in a Ceefax-style list. The world and UK
updaters write pages 201 and 202 respectively.

### Football (pages 300-304)

```bash
python -m ceefax.src.update_football_page
python -m ceefax.src.update_football_scores_page
python -m ceefax.src.update_fixtures_page
```

Page 300 contains BBC Sport headlines, page 301 contains live and recent Premier
League scores, pages 302-303 contain the Premier League and Championship tables,
and page 304 contains Premier League fixtures and results.

Set `FOOTBALL_DATA_API_KEY` to a football-data.org v4 API token before generating
pages 301-304. The token is sent in the `X-Auth-Token` header; page 300 uses BBC
Sport RSS and does not require it. For example:

```bash
export FOOTBALL_DATA_API_KEY="your-football-data.org-token"
```

Page 504 uses The Movie Database (TMDB) for current, popular, and upcoming films.
Set `TMDB_API_KEY` to a TMDB v3 API key before running
`python -m ceefax.src.update_film_picks_page`:

```bash
export TMDB_API_KEY="your-tmdb-v3-api-key"
```

### Running Updates Periodically

On a Raspberry Pi or Linux box you can call these scripts from `cron` or a
`systemd` timer (e.g. every 15 minutes) so news pages 200-202 and football pages
300-304 refresh automatically.


## systemd Service (Raspberry Pi)

Copy `service/ceefax.service` to:

```bash
sudo cp service/ceefax.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ceefax
sudo systemctl start ceefax
```

Ensure `ExecStart` inside `ceefax.service` points at your Python interpreter and project path.

## JSON Page Format

Example (`pages/100.json`):

```json
{
  "page": "100",
  "title": "News Headlines",
  "timestamp": "2025-01-15T12:34:00Z",
  "subpage": 1,
  "content": [
    "Headline one goes here.",
    "Headline two goes here.",
    "Headline three goes here."
  ]
}
```

Fields:
- `page`: string page number `"100"`–`"999"`
- `subpage`: optional integer, e.g. `1` for `100.1`
- `title`: single-line title
- `timestamp`: ISO 8601 string
- `content`: array of text lines; will be wrapped/padded to 50 columns

## Next Steps

- Replace the simple audio encoder with a real Teletext/AX.25 encoder
- Add a small web UI or API to edit JSON pages
- Implement live reload (watch `pages/` for changes)
- Implement a proper continuous audio stream rather than per-page WAVs


