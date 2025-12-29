from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _state_path() -> Path:
    d = _repo_root() / "ceefax" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / "uploader_state.json"


def _load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {"schema": 1, "files": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"schema": 1, "files": {}}


def _save_state(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read_radio_config() -> tuple[str | None, str | None]:
    """
    Returns (callsign, grid) from ceefax/radio_config.json if present.
    """
    cfg = _repo_root() / "ceefax" / "radio_config.json"
    if not cfg.exists():
        return (None, None)
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        cs = (data.get("callsign") or "").strip().upper() or None
        grid = (data.get("grid") or "").strip().upper() or None
        return (cs, grid)
    except Exception:  # noqa: BLE001
        return (None, None)


def _normalize_server_url(server_url: str) -> str:
    s = (server_url or "").strip()
    if not s:
        return "https://ceefaxstation.com"
    if "://" not in s:
        s = "https://" + s
    return s.rstrip("/")


def _wait_file_stable(path: Path, *, stable_for_s: float = 0.5, timeout_s: float = 10.0) -> None:
    """
    Wait until a file appears stable (size + mtime unchanged for stable_for_s).
    This approximates "finalized" for typical write patterns.
    """
    start = time.time()
    last = None
    stable_start = None
    while True:
        try:
            st = path.stat()
            cur = (st.st_size, st.st_mtime_ns)
        except FileNotFoundError:
            cur = None

        now = time.time()
        if cur is not None and cur == last:
            if stable_start is None:
                stable_start = now
            if (now - stable_start) >= stable_for_s:
                return
        else:
            stable_start = None
            last = cur

        if (now - start) >= timeout_s:
            return
        time.sleep(0.1)


def upload_logs(
    *,
    server_url: str,
    token: str | None,
    uploader_callsign: str | None,
    uploader_grid: str | None,
    poll_seconds: float = 2.0,
    once: bool = False,
) -> None:
    """
    Near real-time uploader:
    - watches ceefax/logs_tx and ceefax/logs_rx
    - POSTs new/changed JSON logs to server
    """
    root = _repo_root()
    tx_dir = root / "ceefax" / "logs_tx"
    rx_dir = root / "ceefax" / "logs_rx"

    state = _load_state()
    files_state: dict[str, Any] = state.get("files") if isinstance(state.get("files"), dict) else {}

    if uploader_callsign is None or uploader_grid is None:
        cs2, grid2 = _read_radio_config()
        uploader_callsign = uploader_callsign or cs2
        uploader_grid = uploader_grid or grid2

    server_url = _normalize_server_url(server_url)
    ingest_url = server_url + "/api/ingest/log"

    def scan_one(path: Path) -> None:
        if not path.is_file() or path.suffix.lower() != ".json":
            return
        _wait_file_stable(path)
        rel = str(path.relative_to(root)).replace("\\", "/")
        b = path.read_bytes()
        sha = _sha256_bytes(b)
        prev = files_state.get(rel) or {}
        if isinstance(prev, dict) and prev.get("sha256") == sha:
            return

        try:
            log = json.loads(b.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return

        body = {
            "token": token or "",
            "uploader": {"callsign": uploader_callsign or "", "grid": uploader_grid or ""},
            "source_path": rel,
            "log": log,
        }
        r = requests.post(ingest_url, json=body, timeout=20)
        r.raise_for_status()

        files_state[rel] = {"sha256": sha, "uploaded_at": time.time()}
        state["files"] = files_state
        _save_state(state)

    print(f"Uploading logs to {ingest_url}")
    print(f"Uploader: callsign={uploader_callsign or '-'} grid={uploader_grid or '-'}")

    try:
        # First pass: upload any existing logs once.
        for d in (tx_dir, rx_dir):
            if d.exists():
                for p in sorted(d.glob("*.json")):
                    scan_one(p)

        if once:
            print("Done (once).")
            return

        # Then: watch for new/updated files (preferred) with polling fallback.
        try:
            from watchfiles import Change, watch  # type: ignore

            print("Watching (event-based): ceefax/logs_tx and ceefax/logs_rx (Ctrl+C to stop)")
            for changes in watch(str(tx_dir), str(rx_dir), debounce=int(max(50, poll_seconds * 1000))):
                for _chg, path_str in changes:
                    p = Path(path_str)
                    if p.suffix.lower() != ".json":
                        continue
                    # Only act on create/modify; ignore delete.
                    if _chg in (Change.added, Change.modified):
                        scan_one(p)
        except Exception:
            print("Watching (polling fallback): ceefax/logs_tx and ceefax/logs_rx (Ctrl+C to stop)")
            while True:
                for d in (tx_dir, rx_dir):
                    if not d.exists():
                        continue
                    for p in sorted(d.glob("*.json")):
                        scan_one(p)
                time.sleep(max(0.2, float(poll_seconds)))
    except KeyboardInterrupt:
        print("Uploader stopped.")


