"""
Update page 902 (System Logs) with recent activity and performance metrics.

This page is fed by a persistent changelog written during update runs.
"""

from __future__ import annotations

import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .compiler import PAGE_WIDTH, PAGE_HEIGHT
from .providers import atomic_write_json


def _pad(text: str) -> str:
    return text[:PAGE_WIDTH].ljust(PAGE_WIDTH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_process_memory_bytes() -> Optional[int]:
    """
    Approximate RAM used by the current process (RSS / Working Set).
    No external dependencies.
    """
    try:
        # Windows: use GetProcessMemoryInfo
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            psapi = ctypes.WinDLL("psapi.dll")
            kernel32 = ctypes.WinDLL("kernel32.dll")

            GetCurrentProcess = kernel32.GetCurrentProcess
            GetCurrentProcess.restype = wintypes.HANDLE

            GetProcessMemoryInfo = psapi.GetProcessMemoryInfo
            GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
            GetProcessMemoryInfo.restype = wintypes.BOOL

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            ok = GetProcessMemoryInfo(GetCurrentProcess(), ctypes.byref(counters), counters.cb)
            if ok:
                return int(counters.WorkingSetSize)
            return None

        # Linux: /proc
        proc_statm = Path("/proc/self/statm")
        if proc_statm.exists():
            parts = proc_statm.read_text(encoding="utf-8").split()
            if len(parts) >= 2:
                rss_pages = int(parts[1])
                page_size = os.sysconf("SC_PAGE_SIZE")
                return rss_pages * page_size
    except Exception:  # noqa: BLE001
        return None
    return None


def get_process_memory_bytes() -> Optional[int]:
    """Public wrapper used by update_all."""
    return _get_process_memory_bytes()


def _load_log(log_file: Path) -> List[Dict[str, Any]]:
    if not log_file.exists():
        return []
    try:
        data = json.loads(log_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception:  # noqa: BLE001
        return []
    return []


def _save_log(log_file: Path, entries: List[Dict[str, Any]]) -> None:
    atomic_write_json(log_file, entries)


def append_run_entries(run_entries: List[Dict[str, Any]], max_entries: int = 200) -> None:
    """
    Append new changelog entries and persist them for future runs.
    """
    root = Path(__file__).resolve().parent.parent
    log_file = root / "activity_log.json"
    existing = _load_log(log_file)
    combined = (existing + run_entries)[-max_entries:]
    _save_log(log_file, combined)


def build_system_logs_page(
    recent_entries: List[Dict[str, Any]],
    avg_update_seconds: Optional[float],
    process_memory_bytes: Optional[int],
) -> List[str]:
    lines: List[str] = []
    lines.append(_pad("SYSTEM LOGS"))
    lines.append(_pad(""))

    lines.append(_pad("RECENT ACTIVITY"))
    lines.append(_pad("-" * PAGE_WIDTH))

    if not recent_entries:
        lines.append(_pad("No updates recorded yet."))
    else:
        for e in recent_entries[:10]:
            ts = str(e.get("ts", ""))[:19]
            msg = str(e.get("msg", ""))
            # Prefer HH:MM:SS if we have ISO
            hhmmss = ts[11:19] if "T" in ts else ts[-8:]
            line = f"{hhmmss} - {msg}"
            lines.append(_pad(line))

    lines.append(_pad(""))
    lines.append(_pad("PERFORMANCE"))
    lines.append(_pad("-" * PAGE_WIDTH))

    if avg_update_seconds is not None:
        lines.append(_pad(f"Avg update time:   {avg_update_seconds:.2f}s"))
    else:
        lines.append(_pad("Avg update time:   N/A"))

    if process_memory_bytes is not None:
        mem_mb = process_memory_bytes / (1024 * 1024)
        lines.append(_pad(f"Memory usage:      ~{mem_mb:.0f} MB"))
    else:
        lines.append(_pad("Memory usage:      N/A"))

    lines.append(_pad(""))
    lines.append(_pad(f"Platform: {platform.system()}"))

    return lines[:PAGE_HEIGHT]


def write_system_logs_page(
    run_entries: Optional[List[Dict[str, Any]]] = None,
    avg_update_seconds: Optional[float] = None,
    process_memory_bytes: Optional[int] = None,
) -> None:
    """
    Write pages/902.json.
    If run_entries is provided, it is appended to the persistent log first.
    """
    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "pages"
    page_file = pages_dir / "902.json"

    if run_entries:
        append_run_entries(run_entries)

    log_file = root / "activity_log.json"
    all_entries = _load_log(log_file)
    recent = list(reversed(all_entries))[:10]

    content = build_system_logs_page(
        recent_entries=recent,
        avg_update_seconds=avg_update_seconds,
        process_memory_bytes=process_memory_bytes,
    )

    page = {
        "page": "902",
        "title": "System Logs",
        "timestamp": _now_iso(),
        "subpage": 1,
        "content": content,
    }
    atomic_write_json(page_file, page)


def main() -> None:
    # Standalone mode: just render from existing log file with current memory usage.
    mem = _get_process_memory_bytes()
    write_system_logs_page(run_entries=None, avg_update_seconds=None, process_memory_bytes=mem)


if __name__ == "__main__":
    main()


