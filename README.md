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

## What is this?

Remember old-school **Ceefax** on TV — the blocky pages for news, weather, and sport?

**Ceefax Station** brings that back on your computer, and (if you want) over amateur radio.

In plain English, it can:

1. **Show teletext-style pages** on your screen (weather, news, football, TV, lottery, and more)
2. **Send those pages over radio** as packet radio audio (for licensed amateur radio operators)
3. **Receive pages** from other stations
4. **Show who’s on air** on a public map: [ceefaxstation.com](https://ceefaxstation.com)

You do **not** need a radio to try it. You can just install it and browse the pages.

> This project is still **alpha** — it works, but things may change as we improve it.

---

## What you’ll see

### On your computer (the Ceefax viewer)

<table>
  <tr>
    <td align="center">
      <img src="screenshots/ceefax-terminal/page-000.png" width="260" alt="Start page" />
      <br/><sub>Start page</sub>
    </td>
    <td align="center">
      <img src="screenshots/ceefax-terminal/page-101.png" width="260" alt="Weather" />
      <br/><sub>Weather</sub>
    </td>
    <td align="center">
      <img src="screenshots/ceefax-terminal/page-200.png" width="260" alt="News" />
      <br/><sub>News</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="screenshots/ceefax-terminal/page-304.png" width="260" alt="Football" />
      <br/><sub>Football</sub>
    </td>
    <td align="center">
      <img src="screenshots/ceefax-terminal/page-402.png" width="260" alt="Lottery" />
      <br/><sub>Lottery</sub>
    </td>
    <td align="center">
      <img src="screenshots/ceefax-terminal/page-504.png" width="260" alt="Films" />
      <br/><sub>Films</sub>
    </td>
  </tr>
</table>

### On the web (who is transmitting / receiving)

![Map of stations](screenshots/desktop-main.png)

---

## Quick start (easiest path)

Best for most people: use the **Windows installer**.

### You need

- A **Windows** PC
- About 10 minutes
- (Optional later) a free Python install if you prefer running from source

### Steps

1. Open the [`installers/`](installers/) folder in this repo
2. Download **`CeefaxStation-Setup-0.1.0.exe`**
3. Run it and click through the installer
4. From the Start Menu, open **Configure Station** and enter:
   - your **callsign** (or a temporary name if you’re just testing on screen)
   - your **frequency** (if you use radio)
   - your **Maidenhead grid** (a short location code like `IO91WM` — used on the map)
5. Start Ceefax Station and open the viewer

That’s enough to browse pages on your PC.

> Tip: the installer may be a little behind the newest code on GitHub. If you want the absolute latest, use the “From source” section below.

---

## Try it without a radio

Once installed, open a terminal in the Ceefax Station folder (or use the Start Menu shortcuts) and run:

```bash
ceefaxstation debug --refresh --view
```

What that means:

- `--refresh` = download the latest weather/news/etc.
- `--view` = open the Ceefax-style screen

### How to move around the pages

| Key | What it does |
| --- | --- |
| Type `101`, `200`, `304`… | Jump to that page (like old Ceefax) |
| `n` or → | Next page |
| `p` or ← | Previous page |
| `F5` | Reload pages |
| `t` | Transmit menu |
| `r` | Receive menu |
| `Esc` or `q` | Go back / quit |

---

## Optional: make pages richer with free API keys

Most stations **don’t need their own API keys**.

By default (`CEEFAX_PAGES_SOURCE=auto`), Ceefax Station tries to download a shared **page pack** from [ceefaxstation.com](https://ceefaxstation.com) first. Your local weather (page 102) and callsign page (700) still update on your PC.

```bash
# Download shared pages from the hub now
ceefaxstation pages pull

# Or refresh as usual (hub first, then local fallback)
ceefaxstation debug --refresh --view
```

| Mode (`CEEFAX_PAGES_SOURCE`) | Behaviour |
| --- | --- |
| `auto` (default) | Try hub pack, fall back to local refresh |
| `hub` | Hub pack only (error if hub is down) |
| `local` | Always refresh on this PC (needs keys for some pages) |

If you run your **own** local refresh instead of the hub, a few pages are better with free keys:

| What it’s for | Env variable name | Free? | Sign up |
| --- | --- | --- | --- |
| Better news | `GUARDIAN_API_KEY` | Yes | [Guardian Open Platform](https://openplatform.theguardian.com/) |
| Football tables / scores | `FOOTBALL_DATA_API_KEY` | Yes | [football-data.org](https://www.football-data.org/client/register) |
| Lottery | `LOTTERY_RESULTS_API_KEY` | Yes (100 calls/month) | [Lottery Results Feed](https://www.lotteryresultsfeed.com/) |
| Film picks | `TMDB_API_KEY` | Yes | [TMDB](https://www.themoviedb.org/settings/api) |

### How to add keys on Windows (only if using local refresh)

1. Open **PowerShell**
2. Paste these (put your real keys between the quotes):

```powershell
[Environment]::SetEnvironmentVariable("GUARDIAN_API_KEY", "paste-key-here", "User")
[Environment]::SetEnvironmentVariable("FOOTBALL_DATA_API_KEY", "paste-key-here", "User")
[Environment]::SetEnvironmentVariable("LOTTERY_RESULTS_API_KEY", "paste-key-here", "User")
[Environment]::SetEnvironmentVariable("TMDB_API_KEY", "paste-key-here", "User")
```

3. **Close PowerShell and open a new one**
4. Run a refresh again:

```bash
ceefaxstation debug --refresh --view
```

### How to add keys on a Mac

```bash
echo 'export GUARDIAN_API_KEY="paste-key-here"' >> ~/.zshrc
echo 'export FOOTBALL_DATA_API_KEY="paste-key-here"' >> ~/.zshrc
echo 'export LOTTERY_RESULTS_API_KEY="paste-key-here"' >> ~/.zshrc
echo 'export TMDB_API_KEY="paste-key-here"' >> ~/.zshrc
source ~/.zshrc
```

**Never put your keys into GitHub or commit them into the project.**

Lottery note: each live lottery update uses 2 API calls. Ceefax remembers the result for 24 hours so you don’t burn through the free monthly limit.

---

## If you want to use radio

You’ll need:

- A valid **amateur radio licence** and to follow your local rules
- A radio + audio interface into your PC
- (For live receive decode) **[Dire Wolf](https://github.com/wb2osz/direwolf)**

### Common commands

```bash
# Send pages once (plays audio)
ceefaxstation tx now --play

# Send automatically every hour
ceefaxstation tx hourly --play

# Decode the latest received audio file
ceefaxstation rx latest

# Listen live from your sound card
ceefaxstation rx live
```

Hourly mode updates the pages shortly **before** the hour, then transmits on the hour.

### Show up on the public map

Run this on your station PC (no login token needed):

```bash
ceefaxstation upload
```

Or double-click / run:

```powershell
.\start_uploader.ps1
```

Then check [ceefaxstation.com](https://ceefaxstation.com).

Your station needs a **grid square** in `ceefax/radio_config.json` to appear on the map.

---

## Install from source (latest code)

Use this if you want the newest GitHub version, or you’re comfortable with Python.

### 1. Install Python 3.11

Download from [python.org](https://www.python.org/downloads/).  
On Windows, tick **“Add Python to PATH”** during install.

### 2. Download the project

```bash
git clone https://github.com/thaum-labs/ceefax_station.git
cd ceefax_station
```

Don’t have Git? You can also download the ZIP from the green **Code** button on GitHub and unzip it.

### 3. Install Python packages

```bash
python -m pip install -r ceefax/requirements.txt
python -m pip install windows-curses
```

(`windows-curses` is only needed on Windows — it makes the coloured Ceefax screen work.)

### 4. Set your station details

Edit `ceefax/radio_config.json`:

```json
{
  "callsign": "YOUR_CALLSIGN",
  "frequency": "2m (144.0-148.0 MHz)",
  "grid": "IO91WM"
}
```

### 5. Run it

```bash
ceefaxstation debug --refresh --view
```

If that command isn’t found, try:

```bash
python -m ceefaxstation debug --refresh --view
```

---

## What’s on the pages?

| Page range | Content |
| --- | --- |
| 101–103 | Weather + UK map |
| 200–202 | News |
| 300–305 | Sport / football |
| 400–402 | Money, travel, lottery |
| 500–504 | Facts, quotes, TV, films |
| 600–602 | Jokes, ASCII art, quiz |
| 700 | Radio / callsign activity |
| 900 | About |

If the internet blips, Ceefax usually **keeps the last good page** instead of going blank.

More technical detail: see [`ceefax/README.md`](ceefax/README.md).

---

## Mini glossary

| Word | Meaning |
| --- | --- |
| **Ceefax / teletext** | Old TV information pages (blocky text + colours) |
| **Callsign** | Your amateur radio ID (like `M7TJF`) |
| **Grid / Maidenhead** | Short location code for maps (like `IO91WM`) |
| **TX** | Transmit (send) |
| **RX** | Receive |
| **AX.25 / AFSK1200** | The packet-radio “language” used to send pages as audio |
| **Dire Wolf** | Free software that helps decode packet radio audio |
| **API key** | A free password from a website so Ceefax can fetch their data |

---

## Helpful links

- Live map: [ceefaxstation.com](https://ceefaxstation.com)
- This project: [github.com/thaum-labs/ceefax_station](https://github.com/thaum-labs/ceefax_station)
- DigitalOcean env vars: [DIGITALOCEAN.md](DIGITALOCEAN.md)
- Licence: [MIT](LICENSE) (free to use)

---

## For developers

<details>
<summary>Click to expand project layout, tests, and screenshot tools</summary>

### Folders

```
ceefax/           main station app + page updaters + viewer
ceefaxstation/    command-line entrypoint
ceefaxweb/        public tracker website/server code
installers/       Windows setup .exe
screenshots/      images used in this README
scripts/          tools to regenerate screenshots
```

### Tests

```bash
python -m pytest
```

### Regenerate README screenshots

```bash
python -m pip install playwright
python -m playwright install chromium
python scripts/generate_ceefax_viewer_screenshots.py
python scripts/generate_readme_logo.py
python scripts/generate_tracker_screenshots.py
```

Version is tracked in `VERSION` and `CHANGELOG.json`.

</details>

---

Created by **M7TJF**

**Ceefax Station** — old-school teletext, new-school packet radio
