from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import cleanup_old_data, connect, default_db_path, ingest_log, init_db, query_link_detail, query_map


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class Hub:
    def __init__(self) -> None:
        self.websockets: set[WebSocket] = set()

    async def broadcast(self, msg: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.websockets):
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.websockets.discard(ws)


async def periodic_cleanup(conn: sqlite3.Connection) -> None:
    """Run database cleanup every 24 hours."""
    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)  # 24 hours
            deleted = cleanup_old_data(conn)
            if any(deleted.values()):
                print(f"Periodic database cleanup: deleted {deleted}")
        except Exception as e:  # noqa: BLE001
            print(f"Warning: Periodic cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db_path = Path(os.environ.get("CEEFAXWEB_DB", "")).expanduser() if os.environ.get("CEEFAXWEB_DB") else default_db_path(_repo_root())
    conn = connect(db_path)
    init_db(conn)
    
    # Store connection and hub in app state
    app.state.db_conn = conn
    app.state.hub = Hub()
    
    # Run cleanup on startup (best effort - don't block if it fails)
    try:
        deleted = cleanup_old_data(conn)
        if any(deleted.values()):
            print(f"Startup database cleanup: deleted {deleted}")
    except Exception:  # noqa: BLE001
        pass  # Cleanup is best effort, don't fail startup
    
    # Start periodic cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup(conn))
    
    yield
    
    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    conn.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Ceefaxstation Tracker", lifespan=lifespan)

    static_dir = Path(__file__).resolve().parent / "static"

    _NO_CACHE_HEADERS = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        # Avoid browsers/proxies caching the UI HTML (helps users see updates immediately).
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(content=html, headers=_NO_CACHE_HEADERS)

    @app.get("/changelog", response_class=HTMLResponse)
    def changelog() -> HTMLResponse:
        changelog_path = static_dir / "changelog.html"
        if not changelog_path.exists():
            raise HTTPException(status_code=404, detail="Changelog page not found")
        html = changelog_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html, headers=_NO_CACHE_HEADERS)

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/api/map")
    def api_map(request: Request, range: str = "24h", band: str = "") -> JSONResponse:  # noqa: A002
        conn = request.app.state.db_conn
        return JSONResponse(query_map(conn, range_key=range, band_filter=band))

    @app.get("/api/link")
    def api_link(request: Request, tx: str, rx: str, range: str = "24h") -> JSONResponse:  # noqa: A002
        conn = request.app.state.db_conn
        return JSONResponse(query_link_detail(conn, tx=tx, rx=rx, range_key=range))

    @app.get("/api/changelog")
    def api_changelog() -> JSONResponse:
        """Return changelog data."""
        changelog_path = _repo_root() / "CHANGELOG.json"
        if changelog_path.exists():
            try:
                changelog_data = json.loads(changelog_path.read_text(encoding="utf-8"))
                return JSONResponse(changelog_data)
            except Exception:  # noqa: BLE001
                pass
        return JSONResponse({"current_version": "unknown", "stage": "alpha", "entries": []})

    @app.get("/api/version")
    def api_version() -> JSONResponse:
        """Return current version."""
        version_path = _repo_root() / "VERSION"
        if version_path.exists():
            try:
                version = version_path.read_text(encoding="utf-8").strip()
                return JSONResponse({"version": version})
            except Exception:  # noqa: BLE001
                pass
        return JSONResponse({"version": "unknown"})

    @app.post("/api/ingest/log")
    async def api_ingest(request: Request, body: dict[str, Any]) -> JSONResponse:
        """
        Ingest a single TX/RX log blob.

        Body format:
          {
            "token": "...",                 // optional (required if server configured)
            "uploader": {"callsign": "...", "grid": "IO91..."},  // optional but recommended
            "source_path": "ceefax/logs_tx/....json",           // optional
            "log": {...}                    // required: the log JSON
          }
        """
        conn = request.app.state.db_conn
        hub = request.app.state.hub
        
        # Token is optional - allow public uploads for seamless user experience
        # If a token is set in environment, it's still accepted but not required
        required_token = os.environ.get("CEEFAXWEB_UPLOAD_TOKEN") or ""
        token = str(body.get("token") or "")
        # Only enforce token if one is configured AND provided token doesn't match
        # This allows public uploads while still supporting token-based auth if needed
        if required_token and token and token != required_token:
            raise HTTPException(status_code=401, detail="invalid token")

        uploader = body.get("uploader") or {}
        up_callsign = str(uploader.get("callsign") or "").strip().upper() or None
        up_grid = str(uploader.get("grid") or "").strip().upper() or None
        src = str(body.get("source_path") or "") or None
        log = body.get("log")
        if not isinstance(log, dict):
            raise HTTPException(status_code=400, detail="missing log")

        inserted, reason = ingest_log(conn, payload=log, uploader_callsign=up_callsign, uploader_grid=up_grid, source_path=src)
        if inserted:
            await hub.broadcast({"type": "ingested", "reason": reason})
        return JSONResponse({"ok": True, "inserted": inserted, "reason": reason})

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        # Access app state through the WebSocket's application
        hub = app.state.hub
        hub.websockets.add(ws)
        try:
            await ws.send_text(json.dumps({"type": "hello"}))
            while True:
                # keepalive / ignore client messages
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.websockets.discard(ws)

    return app


app = create_app()


