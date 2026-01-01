<p align="center">
<span style="color: #ffd34d; font-family: monospace; white-space: pre; display: block; line-height: 1.2;">  ░█▀▀░█▀▀░█▀▀░█▀▀░█▀█░█░█░░
  ░█░░░█▀▀░█▀▀░█▀▀░█▀█░▄▀▄░░
  ░▀▀▀░▀▀▀░▀▀▀░▀░░░▀░▀░▀░▀░░
░█▀▀░▀█▀░█▀█░▀█▀░▀█▀░█▀█░█▀█
░▀▀█░░█░░█▀█░░█░░░█░░█░█░█░█
░▀▀▀░░▀░░▀░▀░░▀░░▀▀▀░▀▀▀░▀░▀</span>
</p>

# Ceefax Station

A modern recreation of the classic Ceefax teletext service, running on Windows with live data feeds, AX.25 packet radio transmission, and a public web tracker.

## Features

### 📺 Teletext Pages
- **Weather**: UK forecasts, local weather, weather maps
- **News**: Headlines, UK news, world news
- **Sport**: Live scores, league tables, fixtures & results
- **Entertainment**: TV highlights, film picks, facts, quotes
- **Finance**: Exchange rates, lottery results
- **Travel**: Travel information and updates

### 📡 Packet Radio (AX.25)
- Transmit pages via AFSK1200 modulation
- Receive and decode AX.25 packets
- Hourly automatic transmission with page refresh
- Integration with Dire Wolf for decoding

### 🌐 Web Tracker
- Public website showing transmitting and receiving stations
- Real-time map visualization with Maidenhead grid squares
- Station-to-station link tracking
- Page transmission/reception statistics
- View at [ceefaxstation.com](https://ceefaxstation.com)

## Quick Start

### Prerequisites
- Python 3.11 (specific version required for special character support)
- Windows

### Installation

You have two options for installing Ceefax Station:

#### Option 1: Windows Installer (Recommended for most users)

1. Download the latest installer from the `installers/` directory in this repository:
   - Latest: `installers/CeefaxStation-Setup-0.1.0.exe`

2. Run the installer and follow the setup wizard

3. Configure your station:
   - After installation, edit `C:\Program Files\Ceefax Station\ceefax\radio_config.json` (or use the "Configure Station" shortcut from the Start menu)
   - Set your callsign, frequency, and grid square

**Note:** The installer may be behind the latest code available on GitHub. For the most up-to-date version, use Option 2 below.

#### Option 2: Manual Installation (Latest code from Git)

1. Clone the repository:
```bash
git clone https://github.com/thaum-labs/ceefax_station.git
cd ceefax_station
```

2. Install dependencies:
```bash
python -m pip install -r ceefax/requirements.txt
```

3. Configure your station:
Edit `ceefax/radio_config.json`:
```json
{
  "callsign": "YOUR_CALLSIGN",
  "frequency": "2m (144.0-148.0 MHz)",
  "grid": "IO91WM"
}
```

## Usage

### Viewer Mode (Debug)
View pages locally without transmission:
```bash
ceefaxstation debug --view
```

Refresh all API feeds and view:
```bash
ceefaxstation debug --refresh --view
```

### Receive Mode (RX)
Decode from a WAV file:
```bash
ceefaxstation rx latest
```

Listen live from soundcard:
```bash
ceefaxstation rx live
```

### Transmit Mode (TX)
Transmit now:
```bash
ceefaxstation tx now --play
```

Hourly automatic transmission:
```bash
ceefaxstation tx hourly --play
```

### Upload Logs to Web Tracker

Upload your logs to the public tracker website automatically. **No configuration needed!**

Simply run:
```bash
ceefaxstation upload
```

The uploader will:
- Automatically use the public tracker at https://ceefaxstation.com
- Read your callsign and grid from `ceefax/radio_config.json`
- Watch for new log files and upload them automatically
- No token or additional configuration required

Or use the provided PowerShell script (reads config automatically):
```powershell
.\start_uploader.ps1
```

**Note:** The public tracker at [ceefaxstation.com](https://ceefaxstation.com) is the only supported upload destination. Users should not run their own tracker servers.

## Project Structure

```
.
├── ceefax/              # Main application
│   ├── src/            # Source code
│   ├── pages/          # Page definitions (JSON)
│   ├── logs_tx/        # Transmission logs
│   ├── logs_rx/        # Reception logs
│   └── requirements.txt
├── ceefaxstation/       # CLI interface
├── ceefaxweb/          # Web tracker application
└── README.md
```

## Web Tracker

The web tracker is a public website that visualizes:
- Transmitting stations (green markers)
- Receiving stations (yellow/blue markers)
- Station-to-station links
- Page transmission statistics
- Reception quality (dB, frequency, age)

### Screenshots

![Desktop Main View](screenshots/desktop-main.png)

The desktop interface features a split layout with an interactive map on the left showing station locations and transmission links, and a control panel on the right with filters, settings, and station information.

## Ceefax Terminal Viewer

### Screenshots

<table>
  <tr>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-000.png">
        <img src="screenshots/ceefax-terminal/page-000.png" width="260" alt="Page 000 (Start)" />
      </a>
      <br/><sub><b>Page 000</b> (Start)</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-503.png">
        <img src="screenshots/ceefax-terminal/page-503.png" width="260" alt="TV Guide (Page 503)" />
      </a>
      <br/><sub><b>TV Guide</b> (Page 503)</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-304.png">
        <img src="screenshots/ceefax-terminal/page-304.png" width="260" alt="Football Fixtures (Page 304)" />
      </a>
      <br/><sub><b>Football</b> (Fixtures, Page 304)</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-101.png">
        <img src="screenshots/ceefax-terminal/page-101.png" width="260" alt="London Weather (Page 101)" />
      </a>
      <br/><sub><b>London</b> (Weather, Page 101)</sub>
    </td>
    <td align="center">
      <a href="screenshots/ceefax-terminal/page-103.png">
        <img src="screenshots/ceefax-terminal/page-103.png" width="260" alt="UK Weather Map (Page 103)" />
      </a>
      <br/><sub><b>UK</b> (Weather map, Page 103)</sub>
    </td>
    <td></td>
  </tr>
</table>

### Web Tracker

The public web tracker is hosted at [ceefaxstation.com](https://ceefaxstation.com). Users should upload their logs to this central tracker rather than running their own servers.

## Configuration

### Radio Configuration
Edit `ceefax/radio_config.json`:
- `callsign`: Your amateur radio callsign
- `frequency`: Operating frequency
- `grid`: Maidenhead grid square

### Page Content
Pages are defined in `ceefax/pages/*.json`. Each page includes:
- Page number
- Title
- Content (array of lines)
- Timestamp
- Subpage number

## Development

### Versioning
The project uses semantic versioning with alpha/beta/release stages:
- **Alpha**: `0.x.x-alpha` (current stage)
- **Beta**: `0.x.x-beta` (future)
- **Release**: `x.x.x` (future, no suffix)

Version is stored in `VERSION` file and changelog in `CHANGELOG.json`.

## License

MIT License - see [LICENSE](LICENSE) for details.

Created by M7TJF

## Links

- **Live Tracker**: [ceefaxstation.com](https://ceefaxstation.com)
- **Repository**: [github.com/thaum-labs/ceefax_station](https://github.com/thaum-labs/ceefax_station)

---

**Ceefax Station** - Bringing teletext to the modern era with packet radio
