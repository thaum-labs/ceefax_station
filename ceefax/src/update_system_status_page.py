"""
Update page 901 (System Status) with live-ish status based on the last update run.

- Data Sources: derived from update_all successes/failures (per feed group)
- System Metrics: OS uptime, pages loaded, last update time
- Summary line: "All systems operational" only when all feeds are OK
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import atomic_write_json


def _pad(text: str) -> str:
    return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_os_uptime_seconds() -> Optional[int]:
    """Return OS uptime in seconds (best effort, no external deps)."""
    try:
        if os.name == "nt":
            import ctypes

            # milliseconds since boot
            GetTickCount64 = ctypes.windll.kernel32.GetTickCount64  # type: ignore[attr-defined]
            GetTickCount64.restype = ctypes.c_ulonglong
            ms = int(GetTickCount64())
            return ms // 1000

        # Linux: /proc/uptime
        p = Path("/proc/uptime")
        if p.exists():
            first = p.read_text(encoding="utf-8").split()[0]
            return int(float(first))
    except Exception:  # noqa: BLE001
        return None
    return None


def _fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "N/A"
    s = int(seconds)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _count_pages(pages_dir: Path) -> int:
    try:
        return len(list(pages_dir.glob("*.json")))
    except Exception:  # noqa: BLE001
        return 0


def build_system_status_page(
    feed_status: Dict[str, Tuple[bool, str]],
    last_update_hhmmss: str,
    pages_loaded: int,
    os_uptime_s: Optional[int],
) -> List[str]:
    failing = [k for k, (ok, _) in feed_status.items() if not ok]
    cached = [k for k, (ok, detail) in feed_status.items() if ok and detail == "STALE"]
    if failing:
        summary = f"Issues detected: {len(failing)} source(s)"
    elif cached:
        summary = f"Operating with cached data: {len(cached)}"
    else:
        summary = "All systems operational"

    lines: List[str] = [
        _pad("SYSTEM STATUS"),
        _pad(summary),
        _pad(""),
    ]

    lines.append(_pad("DATA SOURCES"))
    lines.append(_pad("-" * PAGE_WIDTH))

    # Render feed status rows.
    for label in [
        "Weather (Open-Meteo)",
        "News (Guardian/BBC)",
        "Sport (API/RSS)",
        "Exchange Rates",
        "Travel (TFL)",
        "TV (TVMaze)",
        "Film (TMDB)",
        "Lottery",
        "Entertainment APIs",
        "PSK Reporter",
    ]:
        ok, detail = feed_status.get(label, (False, "UNKNOWN"))
        if ok and detail == "STALE":
            status_txt = "CACHED"
        elif ok and detail == "SKIPPED":
            status_txt = "SKIPPED"
        else:
            status_txt = "CONNECTED" if ok else "ERROR"
        # Keep line readable in 50 cols
        right = status_txt
        left = f"{label}:"
        # Include a short hint if failing
        if not ok and detail:
            right = f"{status_txt}"
        line = f"{left:<18} {right:>12}"
        lines.append(_pad(line))

    lines.append(_pad(""))

    lines.append(_pad("SYSTEM METRICS"))
    lines.append(_pad("-" * PAGE_WIDTH))
    lines.append(_pad(f"OS Uptime:         {_fmt_duration(os_uptime_s)}"))
    lines.append(_pad(f"Pages Loaded:      {pages_loaded}"))
    lines.append(_pad(f"Last Update:       {last_update_hhmmss}"))
    return lines[:PAGE_HEIGHT]


def write_system_status_page(
    feed_status: Dict[str, Tuple[bool, str]],
    last_update_iso: str,
) -> None:
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "901.json"

    # HH:MM:SS in local-ish display (use ISO for parsing)
    hhmmss = last_update_iso[11:19] if "T" in last_update_iso else last_update_iso[-8:]

    pages_loaded = _count_pages(pages_dir)
    os_uptime_s = _get_os_uptime_seconds()

    content = build_system_status_page(
        feed_status=feed_status,
        last_update_hhmmss=hhmmss,
        pages_loaded=pages_loaded,
        os_uptime_s=os_uptime_s,
    )

    page = {
        "page": "901",
        "title": "System Status",
        "timestamp": _now_iso(),
        "subpage": 1,
        "content": content,
    }
    atomic_write_json(page_file, page)


def main() -> None:
    # Standalone: write UNKNOWN statuses
    feed_status = {
        "Weather (Open-Meteo)": (False, "UNKNOWN"),
        "News (Guardian/BBC)": (False, "UNKNOWN"),
        "Sport (API/RSS)": (False, "UNKNOWN"),
        "Exchange Rates": (False, "UNKNOWN"),
        "Travel (TFL)": (False, "UNKNOWN"),
        "TV (TVMaze)": (False, "UNKNOWN"),
        "Film (TMDB)": (False, "UNKNOWN"),
        "Lottery": (False, "UNKNOWN"),
        "Entertainment APIs": (False, "UNKNOWN"),
        "PSK Reporter": (False, "UNKNOWN"),
    }
    write_system_status_page(feed_status=feed_status, last_update_iso=_now_iso())


if __name__ == "__main__":
    main()


