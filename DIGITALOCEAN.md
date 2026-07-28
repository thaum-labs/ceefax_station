# DigitalOcean droplet setup (ceefaxstation.com)

The live site runs on a **DigitalOcean droplet** (not App Platform).

Config lives in:

```text
/root/ceefax_station_website/.env
```

(Older docs said `/root/ceefax_station` — this droplet uses `_website`.)

That file is loaded by systemd for both:

- `ceefaxweb` (the website)
- `ceefax-hub-pages.timer` (refreshes + publishes the shared page pack every 30 minutes)

## Environment variables to set

Edit on the server:

```bash
ssh root@YOUR_DROPLET_IP
nano /root/ceefax_station_website/.env
```

Then:

```bash
systemctl restart ceefaxweb
systemctl restart ceefax-hub-pages.timer
# Optional: publish once immediately
cd /root/ceefax_station_website && source venv/bin/activate
python -m ceefaxweb.refresh_hub_pages
```

### Required / recommended values

| Variable | Required? | Example / notes |
|---|---|---|
| `CEEFAXWEB_HOST` | Yes | `127.0.0.1` |
| `CEEFAXWEB_PORT` | Yes | `8088` |
| `CEEFAXWEB_DB` | Yes | `/root/ceefax_station_website/ceefaxweb/ceefaxweb.sqlite3` |
| `CEEFAXWEB_PAGE_PACK_DIR` | Yes (for hub packs) | `/root/ceefax_station_website/ceefaxweb/data/page_pack` |
| `CEEFAX_PAGES_SOURCE` | Yes on server | **`local`** (server must build pages itself, not download from itself) |
| `CEEFAX_HUB_CALLSIGN` | Optional | `CEEFAX` (used when refreshing hub pages) |
| `GUARDIAN_API_KEY` | Recommended | Free Guardian Open Platform key |
| `FOOTBALL_DATA_API_KEY` | Recommended | Free football-data.org token |
| `LOTTERY_RESULTS_API_KEY` | Recommended | Lottery Results Feed token |
| `TMDB_API_KEY` | Recommended | TMDB v3 API key |
| `CEEFAXWEB_UPLOAD_TOKEN` | Optional | Not enforced; public uploads work without it |

### Example `.env`

```bash
CEEFAXWEB_HOST=127.0.0.1
CEEFAXWEB_PORT=8088
CEEFAXWEB_DB=/root/ceefax_station_website/ceefaxweb/ceefaxweb.sqlite3
CEEFAXWEB_PAGE_PACK_DIR=/root/ceefax_station_website/ceefaxweb/data/page_pack
CEEFAX_PAGES_SOURCE=local
CEEFAX_HUB_CALLSIGN=CEEFAX

GUARDIAN_API_KEY=paste-here
FOOTBALL_DATA_API_KEY=paste-here
LOTTERY_RESULTS_API_KEY=paste-here
TMDB_API_KEY=paste-here
```

## Check it worked

```bash
curl -s https://ceefaxstation.com/api/pages/manifest | head
systemctl status ceefax-hub-pages.timer --no-pager
journalctl -u ceefax-hub-pages.service -n 50 --no-pager
```

You want `page_count` > 0 and a recent `generated_at`.

## What stations do

Nothing special beyond updating to latest `main`. Default `CEEFAX_PAGES_SOURCE=auto` pulls this pack and keeps pages 102/700 local.
