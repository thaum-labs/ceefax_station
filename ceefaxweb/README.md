## Ceefaxstation Tracker (Web)

**Note:** This is the web tracker code for the central server at [ceefaxstation.com](https://ceefaxstation.com). 

**Users should NOT run their own tracker servers.** Instead, they should upload their logs to the public tracker using:

```bash
ceefaxstation upload
```

This will automatically upload to https://ceefaxstation.com with no configuration needed.

---

### For Server Administrators Only

The following information is for administrators of the central tracker server only.

Public, no-login website + API that visualizes **TX/RX stations** and **links** (lines) between them, driven by the JSON logs uploaded from user stations.

### Run the server locally (development/testing)

Install deps:

```bash
python -m pip install -r ceefax/requirements.txt
```

Start the server (default `http://127.0.0.1:8088`):

```bash
python -m ceefaxweb
```

Open:
- `http://127.0.0.1:8088/`

### Upload Configuration

Uploads are **public by default** — no token required. This allows seamless uploads from user stations via `ceefaxstation upload`.

`CEEFAXWEB_UPLOAD_TOKEN` (if set in the server environment) is **not enforced**; the ingest API accepts uploads with or without a token. Do not treat that env var as access control.

The uploader:
- Watches `ceefax/logs_tx` and `ceefax/logs_rx`
- Uploads new/changed JSON files
- Stores a local state file at `ceefax/cache/uploader_state.json` to avoid re-uploading

### Maidenhead grids

Stations appear on the map only if the server knows their **Maidenhead grid**.

You can provide it via:
- `ceefaxstation upload --grid <GRID>`
- or add it to `ceefax/radio_config.json` as `"grid": "IO91WM"` (the uploader will pick it up)

### API endpoints

- `GET /api/map?range=24h|7d|30d`
- `GET /api/link?tx=CALL&rx=CALL&range=24h|7d|30d`
- `GET /api/pages/manifest` — shared teletext page-pack metadata (public, rate-limited)
- `GET /api/pages/pack` — zip of shared pages (public, rate-limited; excludes local-only 102/700)
- `POST /api/ingest/log`
- `WS /ws` (pushes `{type:"ingested"}` on new log ingestion)

### Publishing a page pack (hub operator)

On the server that holds the API keys:

```bash
# 1) Refresh pages locally with keys configured in the environment
python -m ceefaxstation debug --refresh --no-view --pages-source local

# 2) Publish shared pages into the pack directory
python -m ceefaxweb.publish_pages
# or: ceefaxstation pages publish
```

Pack directory defaults to `ceefaxweb/data/page_pack/` (override with `CEEFAXWEB_PAGE_PACK_DIR`).

Stations then run:

```bash
ceefaxstation pages pull
# or rely on CEEFAX_PAGES_SOURCE=auto during debug/tx refresh
```


