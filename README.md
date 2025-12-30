# Ceefax Station

<div align="center">

```
  ░█▀▀░█▀▀░█▀▀░█▀▀░█▀█░█░█░░
  ░█░░░█▀▀░█▀▀░█▀▀░█▀█░▄▀▄░░
  ░▀▀▀░▀▀▀░▀▀▀░▀░░░▀░▀░▀░▀░░
░█▀▀░▀█▀░█▀█░▀█▀░▀█▀░█▀█░█▀█
░▀▀█░░█░░█▀█░░█░░░█░░█░█░█░█
░▀▀▀░░▀░░▀░▀░░▀░░▀▀▀░▀▀▀░▀░▀
```

</div>

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

### Updating Pages
Pages can be updated manually or via API update scripts in `ceefax/src/update_*.py`.

### Adding New Pages
1. Create a JSON file in `ceefax/pages/`
2. Add entry to the index page (100.json)
3. Update compiler if needed

## License

MIT License - see [LICENSE](LICENSE) for details.

Created by M7TJF

## Links

- **Live Tracker**: [ceefaxstation.com](https://ceefaxstation.com)
- **Repository**: [github.com/thaum-labs/ceefax_station](https://github.com/thaum-labs/ceefax_station)

---

**Ceefax Station** - Bringing teletext to the modern era with packet radio
