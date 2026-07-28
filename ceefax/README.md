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

## Running

From the repo root (the directory that contains `ceefax/`):

```bash
python -m ceefaxstation debug --refresh --view
```

This will (debug/viewer mode):

1. Load config from `config.toml`
2. Load pages from `pages/`
3. Compile them to 50×30 page frames
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

## Live Weather Page (Frome)

There is a small helper that can fetch **live weather data for Frome, UK** from `wttr.in` (similar to the Rust project [`shift/ceefax-weather`](https://github.com/shift/ceefax-weather?tab=readme-ov-file)) and write it into page `101`.

From the repo root (with your venv active):

```bash
python -m ceefax.src.update_weather_page
```

This will:

1. Call `wttr.in` for `Frome,UK`.
2. Build a Ceefax-style panel sized to your page width.
3. Overwrite `pages/101.json` with the latest data.

Then open the viewer and press `F5` to reload pages:

```bash
python -m ceefax.src.viewer
```

## UK Weather Map Page

You can also generate a simple **UK weather map** (with icons and temperatures for a few cities including Frome) on page `120`:

```bash
python -m ceefax.src.update_weather_map_page
```

Then in the viewer, press `r` and go to **page 120** to see the map.

## Auto-updated News & Football Pages

There are helpers to keep the **news (page 100)** and **football (page 150)** pages fresh using BBC RSS feeds.

### News (page 100)

```bash
python -m ceefax.src.update_news_page
```

This fetches the latest headlines from the BBC Somerset RSS feed and writes them into `pages/100.json` in a Ceefax-style list.

### Football (page 150)

```bash
python -m ceefax.src.update_football_page
```

This fetches recent football headlines/results from BBC Sport Football RSS and writes them into `pages/150.json`.

### Running Updates Periodically

On a Raspberry Pi or Linux box you can call these scripts from `cron` or a `systemd` timer (e.g. every 15 minutes) so pages 100 and 150 refresh automatically.


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
- `content`: array of text lines; will be wrapped/padded to 40 columns

## Next Steps

- Replace the simple audio encoder with a real Teletext/AX.25 encoder
- Add a small web UI or API to edit JSON pages
- Implement live reload (watch `pages/` for changes)
- Implement a proper continuous audio stream rather than per-page WAVs


