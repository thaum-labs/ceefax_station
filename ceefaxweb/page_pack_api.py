"""Hub-side page pack storage and simple per-IP rate limiting."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock

from ceefax.src.page_pack import load_manifest, validate_pack_dir


def default_pack_dir(repo_root: Path) -> Path:
    configured = (os.environ.get("CEEFAXWEB_PAGE_PACK_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (repo_root / "ceefaxweb" / "data" / "page_pack").resolve()


class RateLimiter:
    """Fixed-window counter: allow `limit` events per `window_seconds` per key."""

    def __init__(self, *, limit: int = 30, window_seconds: float = 60.0) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


def client_ip(headers: dict[str, str], fallback: str = "unknown") -> str:
    forwarded = (headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or fallback
    real_ip = (headers.get("x-real-ip") or headers.get("X-Real-IP") or "").strip()
    return real_ip or fallback


def get_pack_manifest(pack_dir: Path) -> dict:
    return validate_pack_dir(pack_dir)


def pack_zip_path(pack_dir: Path) -> Path:
    path = pack_dir / "pages.zip"
    if not path.exists():
        raise FileNotFoundError(f"No pages.zip in {pack_dir} — publish a pack first")
    # Ensure manifest still validates.
    load_manifest(pack_dir)
    return path
