import argparse
import curses
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from uuid import UUID

from .config import load_config
from .compiler import (
    Page,
    load_all_pages,
    compile_page_to_matrix,
    PAGE_WIDTH,
    PAGE_HEIGHT,
)

_HEX_TOKEN_RE = re.compile(r"<0x([0-9A-Fa-f]{2})>")


def _decode_direwolf_info_text(info_text: str) -> bytes:
    """
    Convert Dire Wolf monitor info field text into bytes.

    Example input (from your logs):
      "CFX110001<0x00><0x06>...<0x0a>..."
    """
    out = bytearray()
    i = 0
    for m in _HEX_TOKEN_RE.finditer(info_text):
        # Plain text between tokens.
        if m.start() > i:
            out += info_text[i : m.start()].encode("latin-1", errors="replace")
        out.append(int(m.group(1), 16))
        i = m.end()

    if i < len(info_text):
        out += info_text[i:].encode("latin-1", errors="replace")

    return bytes(out)


class _Ax25FragmentReassembler:
    """
    Reassembles CFX fragments into full compiled page bytes.

    Header formats:
      v1: b'CFX1' + page(3 ascii) + subpage(2 ascii) + idx(1) + total(1) + chunk...
      v2: b'CFX2' + tx_id(16 bytes) + page(3 ascii) + subpage(2 ascii) + idx(1) + total(1) + chunk...
    """

    def __init__(self) -> None:
        self._buf = {}  # (tx_id:str, page:str, subpage:int) -> {"total": int, "chunks": {idx:int->bytes}}

    def add(self, info_bytes: bytes):
        parsed = _parse_cfx_info(info_bytes)
        if not parsed:
            return None
        tx_id = parsed["tx_id"]
        page = parsed["page"]
        subpage = parsed["subpage"]
        idx = parsed["idx"]
        total = parsed["total"]
        chunk = parsed["chunk"]

        key = (tx_id, page, subpage)
        st = self._buf.get(key)
        if st is None:
            st = {"total": int(total), "chunks": {}}
            self._buf[key] = st
        else:
            # Total fragments should be stable; if we see it change, keep the max so
            # we can still complete the page without discarding already-received data.
            st["total"] = max(int(st.get("total", 0)), int(total))

        # Never overwrite an already-received fragment index. This ensures that
        # repeated carousel passes can only improve completeness and cannot
        # replace a previously good fragment with a worse one.
        chunks = st["chunks"]
        i_idx = int(idx)
        if i_idx not in chunks:
            chunks[i_idx] = chunk

        want = int(st["total"])
        if want <= 0 or want > 255:
            return None

        if len(chunks) < want:
            return None
        if any(i not in chunks for i in range(want)):
            return None

        data = b"".join(chunks[i] for i in range(want))
        del self._buf[key]
        return (tx_id, page, subpage, data)


def _parse_cfx_info(info_bytes: bytes) -> dict | None:
    """
    Parse info payload bytes for CFX v1/v2.

    Returns:
      {
        "version": 1|2,
        "tx_id": "<uuid>" or "",
        "page": "000",
        "subpage": 1,
        "idx": int,
        "total": int,
        "chunk": bytes,
      }
    """
    if not info_bytes.startswith(b"CFX"):
        return None
    if len(info_bytes) < 4:
        return None

    magic = info_bytes[:4]
    if magic == b"CFX1":
        if len(info_bytes) < 11:
            return None
        try:
            page = info_bytes[4:7].decode("ascii", errors="ignore")
            subpage = int(info_bytes[7:9].decode("ascii", errors="ignore") or "1")
        except Exception:  # noqa: BLE001
            return None
        return {
            "version": 1,
            "tx_id": "",
            "page": page,
            "subpage": subpage,
            "idx": int(info_bytes[9]),
            "total": int(info_bytes[10]),
            "chunk": info_bytes[11:],
        }

    if magic == b"CFX2":
        # magic(4) + tx_id(16) + page(3) + subpage(2) + idx(1) + total(1) = 27 bytes min
        if len(info_bytes) < 27:
            return None
        tx_bytes = info_bytes[4:20]
        try:
            tx_id = str(UUID(bytes=tx_bytes))
            page = info_bytes[20:23].decode("ascii", errors="ignore")
            subpage = int(info_bytes[23:25].decode("ascii", errors="ignore") or "1")
        except Exception:  # noqa: BLE001
            return None
        return {
            "version": 2,
            "tx_id": tx_id,
            "page": page,
            "subpage": subpage,
            "idx": int(info_bytes[25]),
            "total": int(info_bytes[26]),
            "chunk": info_bytes[27:],
        }

    return None


def _compiled_bytes_to_matrix_and_page(page: str, subpage: int, compiled: bytes):
    # Page 000 may be UTF-8 (Unicode logo). Everything else is ASCII.
    encoding = "utf-8" if page == "000" else "ascii"
    text = compiled.decode(encoding, errors="replace")
    lines = text.split("\n")
    # Normalize to 50x23.
    matrix = [ln[:PAGE_WIDTH].ljust(PAGE_WIDTH) for ln in lines[:PAGE_HEIGHT]]
    while len(matrix) < PAGE_HEIGHT:
        matrix.append(" " * PAGE_WIDTH)

    # Extract title/timestamp best-effort from the compiled matrix.
    page_id = f"{page}.{subpage}" if subpage and subpage != 1 else page
    header = matrix[0].strip()
    title = ""
    if header.startswith(page_id):
        title = header[len(page_id) :].strip()
    else:
        parts = header.split(" ", 1)
        title = parts[1].strip() if len(parts) == 2 else ""

    timestamp = matrix[1].rstrip()
    content = [ln.rstrip() for ln in matrix[2:]]

    return (
        Page(
            page=page,
            title=title,
            timestamp=timestamp,
            subpage=subpage or 1,
            content=content,
        ),
        matrix,
    )


def _direwolf_binary_names() -> list[str]:
    if sys.platform.startswith("win"):
        return ["direwolf.exe"]
    return ["direwolf", "direwolf.exe"]


def _find_direwolf_exe(explicit: str | None = None) -> str:
    """
    Find bundled Dire Wolf or fall back to PATH.

    Prefer the writable user data tree, then the install directory (Program Files
    for the Windows installer, /usr/lib/ceefax-station on Debian), then PATH.
    Linux packages typically use the system `direwolf` binary from apt.
    """
    if explicit:
        return explicit

    names = _direwolf_binary_names()
    candidates: list[Path] = []
    try:
        from .paths import ceefax_root, install_root

        for name in names:
            candidates.append(ceefax_root() / "tools" / "direwolf" / name)
            candidates.append(install_root() / "ceefax" / "tools" / "direwolf" / name)
    except Exception:  # noqa: BLE001
        for name in names:
            candidates.append(Path(__file__).resolve().parent.parent / "tools" / "direwolf" / name)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except Exception:  # noqa: BLE001
            continue

    import shutil

    for name in names:
        found = shutil.which(name)
        if found:
            return found

    return names[0]


def _find_latest_wav_in_output_dir(output_dir: str) -> str | None:
    try:
        p = Path(output_dir)
        if not p.exists():
            return None
        wavs = list(p.glob("*.wav"))
        if not wavs:
            return None
        wavs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return str(wavs[0])
    except Exception:  # noqa: BLE001
        return None


def _prompt_callsign() -> str:
    """
    Prompt for listener callsign (receiver) before starting curses.
    """
    while True:
        try:
            cs = input("Enter your call sign (listener/receiver): ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            raise
        if cs:
            return cs
        print("Call sign cannot be empty. Try again.")


def _log_dir() -> Path:
    # Store RX logs under ceefax/logs_rx/
    from .paths import ceefax_root

    return ceefax_root() / "logs_rx"


def _log_path_for_wav(wav_path: str) -> Path:
    p = Path(wav_path)
    return _log_dir() / f"{p.stem}.json"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    # Auto-upload RX tracker logs after each write (best-effort, background).
    try:
        if path.parent.name == "logs_rx" and path.suffix.lower() == ".json":
            from ceefaxstation.uploader import auto_upload_log

            auto_upload_log(path, wait_stable=False)
    except Exception:  # noqa: BLE001
        pass


def _load_radio_config() -> dict:
    """
    Best-effort read of ceefax/radio_config.json so RX logs can include frequency/grid
    metadata for the web tracker.
    """
    try:
        from .paths import ceefax_root

        p = ceefax_root() / "radio_config.json"
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


_AUDIO_LEVEL_RE = re.compile(r"audio level[^0-9\-]*(-?\d+(?:\.\d+)?)", re.I)
_UI_COLORS_READY = False


def _init_ui_colors() -> tuple[int, int]:
    """Initialize the shared Ceefax palette once per curses session."""
    global _UI_COLORS_READY
    if curses.has_colors():
        if not _UI_COLORS_READY:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_YELLOW, curses.COLOR_BLUE)
            curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
            curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
            curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)
            curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLACK)
            curses.init_pair(6, curses.COLOR_BLUE, curses.COLOR_BLACK)
            curses.init_pair(7, curses.COLOR_CYAN, curses.COLOR_BLACK)
            _UI_COLORS_READY = True
        return (curses.color_pair(1) | curses.A_BOLD, curses.color_pair(2))
    return (curses.A_BOLD, curses.A_NORMAL)


def _ui_layout(stdscr: "curses._CursesWindow") -> tuple[int, int, int, int] | None:
    """
    Return (frame_y, frame_x, frame_height, frame_width).

    Two bottom rows are always reserved for controls and status. The frame uses
    all remaining height on 80x24 and remains centered in larger terminals.
    """
    max_y, max_x = stdscr.getmaxyx()
    if max_y < 14 or max_x < PAGE_WIDTH:
        return None
    available_height = max_y - 2
    frame_height = min(PAGE_HEIGHT, available_height)
    frame_y = max((available_height - frame_height) // 2, 0)
    frame_x = max((max_x - PAGE_WIDTH) // 2, 0)
    return (frame_y, frame_x, frame_height, PAGE_WIDTH)


def _safe_addstr(stdscr: "curses._CursesWindow", row: int, col: int, text: str, attr: int = 0) -> None:
    """Draw without allowing a terminal resize race to crash the viewer."""
    max_y, max_x = stdscr.getmaxyx()
    if row < 0 or row >= max_y or col < 0 or col >= max_x:
        return
    try:
        stdscr.addstr(row, col, text[: max(0, max_x - col - 1)], attr)
    except curses.error:
        pass


def _draw_too_small(stdscr: "curses._CursesWindow") -> None:
    stdscr.clear()
    max_y, max_x = stdscr.getmaxyx()
    lines = [
        "CEEFAX STATION",
        f"Terminal too small: {max_x}x{max_y}",
        f"Resize to at least {PAGE_WIDTH}x14 (80x24 recommended).",
    ]
    start = max((max_y - len(lines)) // 2, 0)
    for i, line in enumerate(lines):
        _safe_addstr(stdscr, start + i, max((max_x - len(line)) // 2, 0), line, curses.A_BOLD)
    stdscr.refresh()


def _draw_footer(
    stdscr: "curses._CursesWindow",
    *,
    status: str,
    mode: str = "viewer",
    page_entry: str = "",
    notice: str = "",
) -> None:
    """Draw a persistent responsive controls row and reversed status row."""
    max_y, max_x = stdscr.getmaxyx()
    if max_y < 2:
        return
    _init_ui_colors()

    if mode == "viewer":
        controls = (
            "000 INDEX  3 DIGITS: PAGE  LEFT/RIGHT: BROWSE  "
            "R: RX  T: TX  S: SETUP  U: UPDATE  F5: REFRESH  ESC: EXIT"
        )
    elif mode == "rx":
        controls = "LEFT/RIGHT: RECEIVED PAGES  3 DIGITS: PAGE  ESC: RETURN"
    else:
        controls = "ESC: CANCEL / RETURN"
    if max_x < len(controls) + 2 and mode in ("viewer", "rx"):
        controls = (
            "3 DIGITS: PAGE  R:RX T:TX S:SETUP U:UPD F5 ESC"
            if mode == "viewer"
            else "LEFT/RIGHT: PAGES  3 DIGITS: PAGE  ESC: RETURN"
        )

    controls_attr = curses.color_pair(7) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    _safe_addstr(stdscr, max_y - 2, 0, " " * max(max_x - 1, 0))
    _safe_addstr(stdscr, max_y - 2, max((max_x - 1 - len(controls)) // 2, 0), controls, controls_attr)

    detail = notice
    if page_entry:
        detail = f"PAGE {page_entry.ljust(3, '_')}  Type three digits"
    status_text = detail or status
    status_text = status_text[: max(max_x - 1, 0)]
    _safe_addstr(stdscr, max_y - 1, 0, " " * max(max_x - 1, 0), curses.A_REVERSE)
    _safe_addstr(
        stdscr,
        max_y - 1,
        max((max_x - 1 - len(status_text)) // 2, 0),
        status_text,
        curses.A_REVERSE,
    )


def _find_page_index(pages: List[Page], number: str) -> int | None:
    """Return the first subpage matching a three-digit page number."""
    normalized = (number or "").strip().zfill(3)
    for index, page in enumerate(pages):
        if page.page == normalized:
            return index
    return None


def _page_entry_result(pages: List[Page], digits: str) -> tuple[int | None, str]:
    """Resolve a three-digit page entry into an index and user-facing notice."""
    if len(digits) != 3 or not digits.isdigit():
        return (None, "Enter a three-digit page number")
    index = _find_page_index(pages, digits)
    if index is None:
        return (None, f"PAGE {digits} NOT FOUND")
    return (index, f"PAGE {digits}")


def _handle_page_key(
    ch: int,
    pages: List[Page],
    current_index: int,
    digits: str,
) -> tuple[int, str, str, bool]:
    """
    Handle one numeric page-entry key.

    Returns (index, digits, notice, handled). Entry resolves immediately after
    three digits, matching classic teletext behavior.
    """
    if ord("0") <= ch <= ord("9"):
        if len(digits) >= 3:
            digits = ""
        digits += chr(ch)
        if len(digits) == 3:
            result, notice = _page_entry_result(pages, digits)
            return (result if result is not None else current_index, "", notice, True)
        return (current_index, digits, "", True)
    if ch in (curses.KEY_BACKSPACE, 8, 127) and digits:
        return (current_index, digits[:-1], "", True)
    return (current_index, digits, "", False)


def _format_progress_bar(width: int, percent: float) -> str:
    """
    Build a fixed-width progress bar body like [===>    ] (brackets included).
    Total length is always width + 2.
    """
    percent = max(0.0, min(1.0, percent))
    filled = int(width * percent)
    if filled <= 0:
        return "[" + " " * width + "]"
    if filled >= width:
        return "[" + "=" * width + "]"
    return "[" + "=" * (filled - 1) + ">" + " " * (width - filled) + "]"


def _maybe_update_audio_db(stats: dict, *, line: str) -> None:
    """
    Dire Wolf sometimes prints signal lines like "audio level ...".
    We treat the numeric value as a best-effort dB-ish indicator.
    """
    m = _AUDIO_LEVEL_RE.search(line or "")
    if not m:
        return
    try:
        stats["rx_db"] = float(m.group(1))
    except Exception:  # noqa: BLE001
        return


def _update_rx_log_summary(stats: dict) -> None:
    """
    Populate derived summary fields in-place so the log is easy to consume.
    """
    pages_decoded = stats.get("pages_decoded", {}) or {}
    page_progress = stats.get("page_progress", {}) or {}

    decoded_count = len(pages_decoded)
    pages_seen = len(page_progress)

    partial = 0
    complete_by_progress = 0
    for _k, v in page_progress.items():
        try:
            total = int(v.get("total", 0))
            got = v.get("got", []) or []
            got_n = len(set(int(x) for x in got))
            if total > 0 and got_n >= total:
                complete_by_progress += 1
            elif total > 0 and got_n > 0:
                partial += 1
        except Exception:  # noqa: BLE001
            continue

    stats["decoded_page_count"] = decoded_count
    stats["pages_seen_count"] = pages_seen
    stats["partial_page_count"] = partial
    stats["complete_by_progress_count"] = complete_by_progress


def _rx_pages_from_wav_with_direwolf(
    *,
    wav_path: str,
    direwolf_exe: str,
    dest_filter: str,
    out_q: "queue.Queue[tuple[Page, List[str]]]",
    stop_event: threading.Event,
    stats: dict,
    stats_lock: threading.Lock,
    log_path: Path | None = None,
    log_every_s: float = 1.0,
) -> None:
    """
    Spawn Dire Wolf, feed it a WAV via stdin, stream decoded CFX pages into out_q.
    """
    reassembler = _Ax25FragmentReassembler()

    # Dire Wolf reads WAV from stdin when argument is "-".
    # On Windows builds, it may require a config file; prefer a sibling direwolf.conf.
    exe_dir = str(Path(direwolf_exe).resolve().parent)
    cfg_path = str(Path(exe_dir) / "direwolf.conf")
    cmd = [direwolf_exe]
    if Path(cfg_path).exists():
        cmd += ["-c", cfg_path]
    cmd += ["-r", "48000", "-B", "1200", "-q", "d", "-D", "1", "-"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=exe_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
        )
    except FileNotFoundError:
        # Surface a clear message to the UI by enqueueing nothing and returning.
        raise

    def feeder():
        try:
            if proc.stdin is None:
                return
            with open(wav_path, "rb") as f:
                while not stop_event.is_set():
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            with stats_lock:
                stats["wav_read_error"] = str(exc)
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

    t = threading.Thread(target=feeder, daemon=True)
    t.start()

    try:
        if proc.stdout is None:
            return

        decoded_any = False
        # Keep a small snippet of early output to help diagnose failures.
        early_lines: List[str] = []
        last_log_t = time.monotonic()

        while True:
            if stop_event.is_set():
                break
            raw = proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("latin-1", errors="replace")

            # Skip signal level lines etc.
            if "audio level" in line:
                with stats_lock:
                    _maybe_update_audio_db(stats, line=line)
                continue
            if ">" not in line or ":" not in line:
                if len(early_lines) < 8 and line.strip():
                    early_lines.append(line.strip())
                # Capture Dire Wolf banner/version/config lines for logging.
                if line.strip():
                    with stats_lock:
                        if len(stats.get("direwolf_output_head", [])) < 12:
                            stats.setdefault("direwolf_output_head", []).append(line.strip())
                continue

            # Only keep frames addressed to dest_filter (default CEEFAX).
            # Example: "[0.2] N0CALL-1>CEEFAX:CFX1...."
            if f">{dest_filter}:" not in line:
                continue

            # Parse sender callsign and rx timestamp (Dire Wolf prints "[0.2] " prefix).
            ts_s: float | None = None
            src = None
            try:
                if line.startswith("["):
                    ts_part = line.split("]", 1)[0][1:]
                    ts_s = float(ts_part)
                after = line.split("]", 1)[1] if "]" in line else line
                # after: " N0CALL-1>CEEFAX:..."
                token = after.strip().split(":", 1)[0]
                # token: "N0CALL-1>CEEFAX"
                src = token.split(">", 1)[0].strip()
            except Exception:  # noqa: BLE001
                pass

            try:
                info_text = line.split(":", 1)[1].rstrip("\r\n")
            except Exception:  # noqa: BLE001
                continue

            if not info_text.startswith("CFX"):
                continue

            info_bytes = _decode_direwolf_info_text(info_text)
            parsed = _parse_cfx_info(info_bytes)
            if not parsed:
                continue

            # Update stats for fragment receipt (only fill missing, never overwrite).
            try:
                page = parsed["page"]
                subpage = int(parsed["subpage"])
                idx = int(parsed["idx"])
                total = int(parsed["total"])
                tx_id = str(parsed.get("tx_id") or "")
                key = f"{page}.{subpage}" if subpage != 1 else page
                with stats_lock:
                    stats["cfx_frames"] = int(stats.get("cfx_frames", 0)) + 1
                    if src:
                        stats.setdefault("stations_heard", {})[src] = (
                            int(stats.get("stations_heard", {}).get(src, 0)) + 1
                        )
                        # Keep a primary station callsign for convenience.
                        # NOTE: don't use setdefault here because the key exists with None initially.
                        if not stats.get("station_callsign"):
                            stats["station_callsign"] = src
                    if tx_id:
                        stats.setdefault("tx_ids_seen", [])
                        if tx_id not in stats["tx_ids_seen"]:
                            stats["tx_ids_seen"].append(tx_id)
                        # Convenience: if there's exactly one tx_id, store it at top-level.
                        if not stats.get("tx_id"):
                            stats["tx_id"] = tx_id
                    # per-page progress
                    pg = stats.setdefault("page_progress", {}).setdefault(
                        key,
                        {"page": page, "subpage": subpage, "total": total, "got": []},
                    )
                    pg["total"] = max(int(pg.get("total", 0)), total)
                    got = set(int(x) for x in pg.get("got", []))
                    if idx not in got:
                        got.add(idx)
                        pg["got"] = sorted(got)
                    if ts_s is not None:
                        pg.setdefault("last_rx_s", ts_s)
            except Exception:  # noqa: BLE001
                with stats_lock:
                    stats["cfx_frames"] = int(stats.get("cfx_frames", 0)) + 1

            assembled = reassembler.add(info_bytes)
            if not assembled:
                # Periodic log flush so users can inspect progress while decoding.
                if log_path and (time.monotonic() - last_log_t) >= float(log_every_s):
                    with stats_lock:
                        stats["updated_at"] = datetime.now().isoformat()
                        _update_rx_log_summary(stats)
                        _write_json(log_path, stats)
                    last_log_t = time.monotonic()
                continue

            tx_id, page, subpage, compiled = assembled
            page_obj, matrix = _compiled_bytes_to_matrix_and_page(page, subpage, compiled)
            out_q.put((page_obj, matrix))
            decoded_any = True
            with stats_lock:
                stats.setdefault("pages_decoded", {})
                pid = page_obj.page_id
                entry_key = f"{tx_id}:{pid}" if tx_id else pid
                if entry_key not in stats["pages_decoded"]:
                    stats["pages_decoded"][entry_key] = {
                        "tx_id": tx_id or None,
                        "page": page_obj.page,
                        "subpage": page_obj.subpage,
                        "title": page_obj.title,
                        "first_complete_rx_s": ts_s,
                        "rx_db": stats.get("rx_db"),
                        "frequency": stats.get("frequency"),
                    }
                # Immediate log flush on page completion so logs always contain decoded pages.
                if log_path:
                    stats["updated_at"] = datetime.now().isoformat()
                    _update_rx_log_summary(stats)
                    _write_json(log_path, stats)
                    last_log_t = time.monotonic()

        # If Dire Wolf exited and we never decoded a page, surface a helpful error.
        if not decoded_any and not stop_event.is_set():
            msg = "Dire Wolf exited without decoding any CFX1 pages."
            if early_lines:
                msg += " Output:\n" + "\n".join(early_lines)
            raise RuntimeError(msg)

    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:  # noqa: BLE001
            pass


def _write_temp_direwolf_config_with_device(*, base_cfg: str, device: str) -> str:
    """
    Create a temporary Dire Wolf config that forces the RX audio device.

    We do this to avoid asking users to edit bundled config files by hand.
    """
    base_path = Path(base_cfg)
    txt = base_path.read_text(encoding="utf-8", errors="replace")

    # Remove any existing (uncommented) ADEVICE lines.
    lines = []
    for ln in txt.splitlines():
        if ln.strip().startswith("ADEVICE "):
            continue
        lines.append(ln)

    # Prepend our ADEVICE directive so it wins.
    out_txt = f"ADEVICE {device}\n" + "\n".join(lines) + "\n"

    out_path = base_path.parent / "_ceefaxstation_live_direwolf.conf"
    out_path.write_text(out_txt, encoding="utf-8")
    return str(out_path)


def _rx_pages_from_live_with_direwolf(
    *,
    direwolf_exe: str,
    dest_filter: str,
    out_q: "queue.Queue[tuple[Page, List[str]]]",
    stop_event: threading.Event,
    stats: dict,
    stats_lock: threading.Lock,
    log_path: Path | None = None,
    log_every_s: float = 1.0,
    config_path: str | None = None,
    device: str | None = None,
    sample_rate: int = 48000,
    baud: int = 1200,
) -> None:
    """
    Spawn Dire Wolf and stream decoded CFX pages from a live sound device.
    """
    reassembler = _Ax25FragmentReassembler()

    exe_dir = str(Path(direwolf_exe).resolve().parent)

    cfg_path = config_path
    if not cfg_path:
        cfg_path = str(Path(exe_dir) / "direwolf.conf")

    if device:
        cfg_path = _write_temp_direwolf_config_with_device(base_cfg=cfg_path, device=device)

    cmd = [direwolf_exe]
    if cfg_path and Path(cfg_path).exists():
        cmd += ["-c", cfg_path]
    cmd += ["-r", str(int(sample_rate)), "-B", str(int(baud)), "-q", "d", "-D", "1"]

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=exe_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
        )
    except FileNotFoundError:
        raise

    try:
        if proc.stdout is None:
            return

        decoded_any = False
        early_lines: List[str] = []
        last_log_t = time.monotonic()

        while True:
            if stop_event.is_set():
                break
            raw = proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("latin-1", errors="replace")

            if "audio level" in line:
                with stats_lock:
                    _maybe_update_audio_db(stats, line=line)
                continue
            if ">" not in line or ":" not in line:
                if len(early_lines) < 8 and line.strip():
                    early_lines.append(line.strip())
                if line.strip():
                    with stats_lock:
                        if len(stats.get("direwolf_output_head", [])) < 12:
                            stats.setdefault("direwolf_output_head", []).append(line.strip())
                continue

            if f">{dest_filter}:" not in line:
                continue

            ts_s: float | None = None
            src = None
            try:
                if line.startswith("["):
                    ts_part = line.split("]", 1)[0][1:]
                    ts_s = float(ts_part)
                after = line.split("]", 1)[1] if "]" in line else line
                token = after.strip().split(":", 1)[0]
                src = token.split(">", 1)[0].strip()
            except Exception:  # noqa: BLE001
                pass

            try:
                info_text = line.split(":", 1)[1].rstrip("\r\n")
            except Exception:  # noqa: BLE001
                continue

            if not info_text.startswith("CFX"):
                continue

            info_bytes = _decode_direwolf_info_text(info_text)
            parsed = _parse_cfx_info(info_bytes)
            if not parsed:
                continue

            try:
                page = parsed["page"]
                subpage = int(parsed["subpage"])
                idx = int(parsed["idx"])
                total = int(parsed["total"])
                tx_id = str(parsed.get("tx_id") or "")
                key = f"{page}.{subpage}" if subpage != 1 else page
                with stats_lock:
                    stats["cfx_frames"] = int(stats.get("cfx_frames", 0)) + 1
                    if src:
                        stats.setdefault("stations_heard", {})[src] = (
                            int(stats.get("stations_heard", {}).get(src, 0)) + 1
                        )
                        if not stats.get("station_callsign"):
                            stats["station_callsign"] = src
                    if tx_id:
                        stats.setdefault("tx_ids_seen", [])
                        if tx_id not in stats["tx_ids_seen"]:
                            stats["tx_ids_seen"].append(tx_id)
                        if not stats.get("tx_id"):
                            stats["tx_id"] = tx_id
                    pg = stats.setdefault("page_progress", {}).setdefault(
                        key,
                        {"page": page, "subpage": subpage, "total": total, "got": []},
                    )
                    pg["total"] = max(int(pg.get("total", 0)), total)
                    got = set(int(x) for x in pg.get("got", []))
                    if idx not in got:
                        got.add(idx)
                        pg["got"] = sorted(got)
                    if ts_s is not None:
                        pg.setdefault("last_rx_s", ts_s)
            except Exception:  # noqa: BLE001
                with stats_lock:
                    stats["cfx_frames"] = int(stats.get("cfx_frames", 0)) + 1

            assembled = reassembler.add(info_bytes)
            if not assembled:
                if log_path and (time.monotonic() - last_log_t) >= float(log_every_s):
                    with stats_lock:
                        stats["updated_at"] = datetime.now().isoformat()
                        _update_rx_log_summary(stats)
                        _write_json(log_path, stats)
                    last_log_t = time.monotonic()
                continue

            tx_id, page, subpage, compiled = assembled
            page_obj, matrix = _compiled_bytes_to_matrix_and_page(page, subpage, compiled)
            out_q.put((page_obj, matrix))
            decoded_any = True
            with stats_lock:
                stats.setdefault("pages_decoded", {})
                pid = page_obj.page_id
                entry_key = f"{tx_id}:{pid}" if tx_id else pid
                if entry_key not in stats["pages_decoded"]:
                    stats["pages_decoded"][entry_key] = {
                        "tx_id": tx_id or None,
                        "page": page_obj.page,
                        "subpage": page_obj.subpage,
                        "title": page_obj.title,
                        "first_complete_rx_s": ts_s,
                        "rx_db": stats.get("rx_db"),
                        "frequency": stats.get("frequency"),
                    }
                if log_path:
                    stats["updated_at"] = datetime.now().isoformat()
                    _update_rx_log_summary(stats)
                    _write_json(log_path, stats)
                    last_log_t = time.monotonic()

        if not decoded_any and not stop_event.is_set():
            msg = "Dire Wolf exited without decoding any CFX pages."
            if early_lines:
                msg += " Output:\n" + "\n".join(early_lines)
            raise RuntimeError(msg)

    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:  # noqa: BLE001
            pass


def _upsert_sorted_page(
    pages: List[Page],
    matrices: List[List[str]],
    page_obj: Page,
    matrix: List[str],
) -> None:
    """
    Insert/update page+matrix while keeping list sorted by (page, subpage).
    """
    key = (int(page_obj.page), int(page_obj.subpage))

    for i, p in enumerate(pages):
        if p.page == page_obj.page and p.subpage == page_obj.subpage:
            pages[i] = page_obj
            matrices[i] = matrix
            return

    insert_at = len(pages)
    for i, p in enumerate(pages):
        if (int(p.page), int(p.subpage)) > key:
            insert_at = i
            break

    pages.insert(insert_at, page_obj)
    matrices.insert(insert_at, matrix)


def _draw_page(
    stdscr: "curses._CursesWindow",
    page: Page,
    matrix: List[str],
    index: int,
    total: int,
    callsign_override: str | None = None,
    *,
    page_entry: str = "",
    notice: str = "",
    footer_mode: str = "viewer",
) -> None:
    """Render a responsive Ceefax page with persistent navigation chrome."""
    stdscr.clear()
    layout = _ui_layout(stdscr)
    if layout is None:
        _draw_too_small(stdscr)
        return

    offset_y, offset_x, frame_height, frame_width = layout
    frame_bottom = offset_y + frame_height - 1
    header_attr, body_attr = _init_ui_colors()
    now = datetime.now()
    clock = now.strftime("%H:%M %d %b").upper()
    callsign = (callsign_override or "").strip()
    if not callsign:
        callsign = str(_load_radio_config().get("callsign") or "").strip().upper()

    title = (page.title or "").upper()[:18]
    header_left = f"CEEFAX {page.page.rjust(3)} {title}"
    header_right = f"{callsign}  {clock}" if callsign else clock
    header = header_left[:frame_width].ljust(frame_width)
    if len(header_right) < frame_width:
        start = frame_width - len(header_right)
        header = header[:start] + header_right
    _safe_addstr(stdscr, offset_y, offset_x, header[:frame_width], header_attr)

    is_start_page = page.page == "000"
    content_lines = matrix[2:PAGE_HEIGHT]
    start_row = offset_y + 1

    if is_start_page:
        border_attr = body_attr | curses.A_BOLD
        top_line = "+" + ("-" * (frame_width - 2)) + "+"
        _safe_addstr(stdscr, start_row, offset_x, top_line, border_attr)
        _safe_addstr(stdscr, frame_bottom, offset_x, top_line, border_attr)
        for row in range(start_row + 1, frame_bottom):
            _safe_addstr(stdscr, row, offset_x, "|", border_attr)
            _safe_addstr(stdscr, row, offset_x + frame_width - 1, "|", border_attr)

        inner_width = frame_width - 2
        row = start_row + 1
        for line in content_lines:
            if row >= frame_bottom:
                break
            raw = line or ""
            if "{{users callsign}}" in raw:
                raw = f"{callsign} TELETEX SERVICE".strip() if callsign else "TELETEX SERVICE"
            text = raw.strip()
            rendered = text[:inner_width].center(inner_width) if text else " " * inner_width
            _safe_addstr(stdscr, row, offset_x + 1, rendered, body_attr | curses.A_BOLD)
            row += 1
    else:
        row = start_row
        _safe_addstr(
            stdscr,
            row,
            offset_x,
            "CEEFAX STATION".center(frame_width),
            header_attr,
        )
        row += 1
        if content_lines:
            heading = (content_lines[0] or "")[:frame_width]
            _safe_addstr(stdscr, row, offset_x, heading, body_attr | curses.A_BOLD)
            row += 1

            def _is_sep(line: str) -> bool:
                stripped = line.strip()
                return bool(stripped) and all(ch == "-" for ch in stripped)

            if not any(_is_sep(line) for line in content_lines[:3]) and row <= frame_bottom:
                _safe_addstr(stdscr, row, offset_x, "-" * frame_width, body_attr)
                row += 1
            for line in content_lines[1:]:
                if row > frame_bottom:
                    break
                _safe_addstr(stdscr, row, offset_x, (line or "")[:frame_width], body_attr)
                row += 1

    status = f"PAGE {page.page_id}  {index + 1}/{total}"
    if footer_mode == "rx":
        status = f"RECEIVE MODE  PAGE {page.page_id}  {index + 1}/{total}"
    _draw_footer(
        stdscr,
        status=status,
        mode=footer_mode,
        page_entry=page_entry,
        notice=notice,
    )
    stdscr.refresh()


def _draw_ascii_progress_bar(stdscr: "curses._CursesWindow", row: int, col: int, width: int, percent: float, label: str = "") -> None:
    """
    Draw an ASCII progress bar in DOS/Ceefax style.
    
    Args:
        stdscr: Curses window
        row: Row position
        col: Column position
        width: Width of progress bar (excluding brackets)
        percent: Progress percentage (0.0 to 1.0)
        label: Optional label text to display
    """
    height, screen_width = stdscr.getmaxyx()
    if row < 0 or row >= height:
        return
    
    # Clamp percent
    percent = max(0.0, min(1.0, percent))
    bar = _format_progress_bar(width, percent)
    percent_str = f" {int(percent * 100)}%"
    
    # Combine label, bar, and percent
    if label:
        full_text = f"{label} {bar}{percent_str}"
    else:
        full_text = f"{bar}{percent_str}"
    
    # Truncate to fit screen and ensure it doesn't exceed available space
    max_width = screen_width - col - 1
    if len(full_text) > max_width:
        # If too long, truncate the label first, then the bar
        if label and len(label) > 5:
            label_short = label[:max_width - len(bar) - len(percent_str) - 1]
            full_text = f"{label_short} {bar}{percent_str}"
        else:
            full_text = full_text[:max_width]
    
    try:
        stdscr.addstr(row, col, full_text[:max_width])
    except curses.error:
        pass  # Ignore if out of bounds


def _draw_mode_screen(
    stdscr: "curses._CursesWindow",
    *,
    mode: str,
    title: str,
    status: str,
    fields: list[tuple[str, str]] | None = None,
    progress: float | None = None,
    progress_label: str = "",
    countdown: str = "",
    message: str = "",
    footer_status: str = "",
    footer_mode: str | None = None,
) -> None:
    """Shared responsive status panel for TX and RX workflows."""
    stdscr.clear()
    layout = _ui_layout(stdscr)
    if layout is None:
        _draw_too_small(stdscr)
        return
    offset_y, offset_x, frame_height, frame_width = layout
    frame_bottom = offset_y + frame_height - 1
    header_attr, body_attr = _init_ui_colors()
    clock = datetime.now().strftime("%H:%M %d %b").upper()
    callsign = str(_load_radio_config().get("callsign") or "").strip().upper()
    header_left = f"CEEFAX {mode}  {title.upper()}"
    header_right = f"{callsign}  {clock}" if callsign else clock
    header = header_left[:frame_width].ljust(frame_width)
    if len(header_right) < frame_width:
        start = frame_width - len(header_right)
        header = header[:start] + header_right
    _safe_addstr(stdscr, offset_y, offset_x, header[:frame_width], header_attr)

    border_top = offset_y + 1
    top_line = "+" + "-" * (frame_width - 2) + "+"
    border_attr = body_attr | curses.A_BOLD
    _safe_addstr(stdscr, border_top, offset_x, top_line, border_attr)
    _safe_addstr(stdscr, frame_bottom, offset_x, top_line, border_attr)
    for row in range(border_top + 1, frame_bottom):
        _safe_addstr(stdscr, row, offset_x, "|", border_attr)
        _safe_addstr(stdscr, row, offset_x + frame_width - 1, "|", border_attr)

    inner_x = offset_x + 2
    inner_width = frame_width - 4
    row = border_top + 2
    # ASCII-only logo renders reliably in Windows PowerShell and Terminal.
    logo = f"[ {mode} ]"
    _safe_addstr(stdscr, row, inner_x, logo.center(inner_width), body_attr | curses.A_BOLD)
    row += 2
    _safe_addstr(stdscr, row, inner_x, status.upper().center(inner_width), body_attr | curses.A_BOLD)
    row += 2

    for label, value in fields or []:
        if row >= frame_bottom - 3:
            break
        field = f"{label[:14].ljust(14)} {value}"
        _safe_addstr(stdscr, row, inner_x, field[:inner_width], body_attr)
        row += 1

    if progress is not None and row < frame_bottom - 3:
        row += 1
        width = max(10, min(28, inner_width - len(progress_label) - 7))
        text = f"{progress_label} {_format_progress_bar(width, progress)} {int(max(0, min(1, progress)) * 100)}%"
        _safe_addstr(stdscr, row, inner_x, text[:inner_width], body_attr | curses.A_BOLD)
        row += 1

    if countdown and row < frame_bottom - 2:
        _safe_addstr(stdscr, row, inner_x, f"Next transmission  {countdown}"[:inner_width], body_attr)
        row += 1
    if message and row < frame_bottom - 1:
        words = message.split()
        line = ""
        for word in words:
            candidate = word if not line else f"{line} {word}"
            if len(candidate) <= inner_width:
                line = candidate
            else:
                _safe_addstr(stdscr, row, inner_x, line.center(inner_width), body_attr)
                row += 1
                if row >= frame_bottom:
                    break
                line = word
        if line and row < frame_bottom:
            _safe_addstr(stdscr, row, inner_x, line.center(inner_width), body_attr)

    _draw_footer(
        stdscr,
        status=footer_status or f"{title.upper()}  ESC: RETURN",
        mode=footer_mode or ("rx" if mode == "RX" else "tx"),
    )
    stdscr.refresh()


def _draw_tx_screen(
    stdscr: "curses._CursesWindow",
    status: str,
    progress: float = 0.0,
    progress_label: str = "",
    countdown: str = "",
    message: str = "",
    show_logo: bool = False,
    *,
    fields: list[tuple[str, str]] | None = None,
    footer_status: str = "TRANSMIT MODE  ENTER: START  ESC: RETURN",
) -> None:
    if fields is None:
        radio = _load_radio_config()
        fields = [
            ("Callsign", str(radio.get("callsign") or "Not configured")),
            ("Frequency", str(radio.get("frequency") or "Not configured")),
        ]
    _draw_mode_screen(
        stdscr,
        mode="TX",
        title="Transmit mode",
        status=status,
        fields=fields,
        progress=progress if progress_label else None,
        progress_label=progress_label,
        countdown=countdown,
        message=message,
        footer_status=footer_status,
    )


def _rx_status_fields(stats: dict | None, *, source: str = "", device: str = "") -> list[tuple[str, str]]:
    """Summarize live decoder state for the RX dashboard."""
    stats = stats or {}
    pages = stats.get("pages_decoded") or {}
    progress = stats.get("page_progress") or {}
    partial = 0
    for value in progress.values() if isinstance(progress, dict) else []:
        try:
            total = int(value.get("total") or 0)
            got = len(set(value.get("got") or []))
            if total > got > 0:
                partial += 1
        except Exception:  # noqa: BLE001
            continue
    signal = stats.get("rx_db")
    signal_text = f"{float(signal):.1f} dB" if signal is not None else "Waiting"
    station = str(stats.get("station_callsign") or "-")
    return [
        ("Source", source or "Live audio"),
        ("Audio", device or "Default device"),
        ("Signal", signal_text),
        ("Frames", str(stats.get("cfx_frames") or 0)),
        ("Pages", f"{len(pages)} complete / {partial} partial"),
        ("Last station", station),
    ]


def _rx_footer_status(stats: dict | None) -> str:
    """Compact decoder telemetry for the footer shown under received pages."""
    stats = stats or {}
    signal = stats.get("rx_db")
    signal_text = f"{float(signal):.1f} dB" if signal is not None else "-- dB"
    pages = len(stats.get("pages_decoded") or {})
    frames = int(stats.get("cfx_frames") or 0)
    station = str(stats.get("station_callsign") or "-")
    return f"RX {signal_text}  {frames} FRAMES  {pages} PAGES  LAST {station}"


def _draw_rx_screen(
    stdscr: "curses._CursesWindow",
    status: str = "",
    message: str = "",
    *,
    stats: dict | None = None,
    source: str = "Live audio",
    device: str = "",
) -> None:
    _draw_mode_screen(
        stdscr,
        mode="RX",
        title="Receive mode",
        status=status or "Listening",
        fields=_rx_status_fields(stats, source=source, device=device),
        message=message,
        footer_status="RECEIVE MODE  ESC: RETURN",
    )


def _edit_text_value(
    value: str,
    ch: int,
    *,
    max_length: int = 12,
    allow: str = "alnum",
) -> tuple[str, bool, bool]:
    """Apply one curses key to a short text value; returns value, submit, cancel."""
    if ch == 27:
        return (value, False, True)
    if ch in (10, 13, curses.KEY_ENTER):
        return (value, True, False)
    if ch in (curses.KEY_BACKSPACE, 8, 127):
        return (value[:-1], False, False)
    if 0 <= ch <= 255:
        char = chr(ch)
        if allow == "upper":
            char = char.upper()
            ok = (char.isalnum() or char in "-/") and len(value) < max_length
        elif allow == "freq":
            ok = (char.isalnum() or char in " .-()/+") and len(value) < max_length
        else:
            char = char.upper()
            ok = (char.isalnum() or char in "-/") and len(value) < max_length
        if ok:
            return (value + char, False, False)
    return (value, False, False)


def _prompt_callsign_in_tui(stdscr: "curses._CursesWindow") -> str | None:
    """Prompt for a callsign without tearing down curses / flashing PowerShell."""
    value = ""
    stdscr.nodelay(False)
    while True:
        _draw_mode_screen(
            stdscr,
            mode="TX",
            title="Station setup",
            status="Callsign required",
            fields=[("Callsign", (value + "_") or "_")],
            message="Enter your amateur radio callsign.",
            footer_status="TYPE CALLSIGN  ENTER: SAVE  ESC: CANCEL",
        )
        ch = stdscr.getch()
        value, submit, cancel = _edit_text_value(value, ch, allow="upper")
        if cancel:
            return None
        if submit and value:
            from .update_all import persist_radio_config

            persist_radio_config(value)
            return value


def _station_setup_incomplete(radio: dict | None = None) -> bool:
    """True when callsign/frequency/grid still need configuring."""
    from .hub_pages import _needs_station_setup

    data = radio if isinstance(radio, dict) else _load_radio_config()
    callsign = str(data.get("callsign") or "").strip()
    frequency = str(data.get("frequency") or "").strip()
    grid = str(data.get("grid") or "").strip()
    return _needs_station_setup(callsign) or (not frequency) or (not grid)


def _frequency_choices() -> list[str]:
    """Preset packet/data frequencies from the station band list."""
    from .update_all import AMATEUR_BANDS, AMATEUR_BAND_RECOMMENDED_FREQ

    choices: list[str] = []
    for group in ("HF", "VHF", "UHF"):
        for band in AMATEUR_BANDS.get(group, []):
            label = AMATEUR_BAND_RECOMMENDED_FREQ.get(band)
            if label:
                choices.append(str(label))
    return choices


def _station_setup_in_tui(stdscr: "curses._CursesWindow", *, force: bool = False) -> bool:
    """
    Station setup in the curses UI (callsign, selectable frequency, grid).

    Frequency is chosen from the recommended band list (LEFT/RIGHT), not typed.
    Shows automatically when incomplete, or when force=True (viewer S key).
    Returns True if settings were saved.
    """
    from .hub_pages import _needs_station_setup
    from .update_all import persist_radio_config

    radio = _load_radio_config()
    if not force and not _station_setup_incomplete(radio):
        return True

    callsign = str(radio.get("callsign") or "").strip().upper()
    if _needs_station_setup(callsign):
        callsign = ""
    frequency = str(radio.get("frequency") or "").strip()
    grid = str(radio.get("grid") or "").strip().upper()

    freq_choices = _frequency_choices()
    if not freq_choices:
        freq_choices = ["144.800 MHz (2m)"]
    try:
        freq_idx = freq_choices.index(frequency)
    except ValueError:
        # Prefer 2m if current value isn't in the list.
        freq_idx = next(
            (i for i, v in enumerate(freq_choices) if "(2m)" in v),
            0,
        )
        if frequency and frequency not in freq_choices:
            # Keep unknown saved value visible until user changes selection.
            freq_choices = [frequency, *freq_choices]
            freq_idx = 0
    frequency = freq_choices[freq_idx]

    field = 0  # 0=callsign, 1=frequency, 2=grid
    stdscr.nodelay(False)
    stdscr.keypad(True)

    while True:
        freq_disp = frequency
        if field == 1:
            freq_disp = f"< {frequency} >  ({freq_idx + 1}/{len(freq_choices)})"
        fields = [
            ("Callsign", (callsign + "_") if field == 0 else (callsign or "(required)")),
            ("Frequency", freq_disp if field == 1 else (frequency or "(required)")),
            ("Grid", (grid + "_") if field == 2 else (grid or "(optional)")),
        ]
        if field == 1:
            msg = "LEFT/RIGHT selects a recommended band frequency."
            footer = "LEFT/RIGHT: BAND  TAB: NEXT  ENTER: SAVE  ESC: CANCEL"
        elif field == 0:
            msg = "Type your callsign. TAB moves to frequency list."
            footer = "TYPE  TAB: NEXT  ENTER: SAVE  ESC: CANCEL"
        else:
            msg = "Maidenhead grid e.g. IO91WM (optional but needed for the map)."
            footer = "TYPE  TAB: NEXT  ENTER: SAVE  ESC: CANCEL"

        _draw_mode_screen(
            stdscr,
            mode="TX",
            title="Station setup",
            status="Configure callsign, frequency, and grid",
            fields=fields,
            message=msg,
            footer_status=footer,
        )
        ch = stdscr.getch()
        if ch == 27:
            return False
        if ch in (9,):  # TAB
            field = (field + 1) % 3
            continue
        if ch == curses.KEY_BTAB:
            field = (field - 1) % 3
            continue
        if ch in (10, 13, curses.KEY_ENTER):
            if callsign.strip() and frequency.strip():
                persist_radio_config(
                    callsign.strip().upper(),
                    frequency=frequency.strip(),
                    grid=(grid.strip().upper() or None),
                )
                return True
            if not callsign.strip():
                field = 0
            elif not frequency.strip():
                field = 1
            continue

        if field == 1:
            if ch in (curses.KEY_LEFT, curses.KEY_UP, ord("-")):
                freq_idx = (freq_idx - 1) % len(freq_choices)
                frequency = freq_choices[freq_idx]
            elif ch in (curses.KEY_RIGHT, curses.KEY_DOWN, ord("+"), ord("=")):
                freq_idx = (freq_idx + 1) % len(freq_choices)
                frequency = freq_choices[freq_idx]
            continue

        if field == 0:
            if ch in (curses.KEY_DOWN,):
                field = 1
                continue
            callsign, _submit, cancel = _edit_text_value(
                callsign, ch, max_length=12, allow="upper"
            )
            if cancel:
                return False
        else:
            if ch in (curses.KEY_UP,):
                field = 1
                continue
            if ch in (curses.KEY_DOWN,):
                continue
            grid, _submit, cancel = _edit_text_value(grid, ch, max_length=8, allow="upper")
            if cancel:
                return False


def _confirm_tx(
    stdscr: "curses._CursesWindow",
    *,
    callsign: str,
    frequency: str,
    data_frequency: str,
    page_count: int,
    repetitions: int,
) -> bool:
    """Show the final TX safety summary; return True on Enter."""
    stdscr.nodelay(False)
    fields = [
        ("Callsign", callsign),
        ("Frequency", frequency or "Not configured"),
        ("Data freq", data_frequency or "Use configured frequency"),
        ("Pages", str(page_count)),
        ("Repetitions", str(repetitions)),
        ("Schedule", "Retransmits automatically each hour"),
        ("Radio", "Enable VOX before starting"),
    ]
    while True:
        _draw_mode_screen(
            stdscr,
            mode="TX",
            title="Transmission ready",
            status="Check radio configuration",
            fields=fields,
            message="ENTER starts now; stays armed for hourly TX. ESC cancels.",
            footer_status="TRANSMISSION READY  ENTER: START  ESC: CANCEL",
        )
        ch = stdscr.getch()
        if ch in (10, 13, curses.KEY_ENTER):
            return True
        if ch == 27:
            return False


def _next_hour_local(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _format_countdown(remaining: timedelta) -> str:
    total_seconds = max(0, int(remaining.total_seconds()))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _tx_frequency_labels(config_file: Path) -> tuple[str, str]:
    """Return (configured frequency label, suggested data frequency)."""
    frequency_info = ""
    data_frequency = ""
    if not config_file.exists():
        return frequency_info, data_frequency
    try:
        config_data = json.loads(config_file.read_text(encoding="utf-8"))
        freq_str = str(config_data.get("frequency") or "")
        if not freq_str:
            return frequency_info, data_frequency
        frequency_info = freq_str
        band_match = re.search(r"(\d+[mc]m?|6m|10m|12m|15m|17m|20m|30m|40m|80m)", freq_str, re.I)
        if band_match:
            band = band_match.group(1).lower()
            data_freq_map = {
                "80m": "3.580 MHz",
                "40m": "7.040 MHz",
                "30m": "10.147 MHz",
                "20m": "14.105 MHz",
                "17m": "18.105 MHz",
                "15m": "21.105 MHz",
                "12m": "24.930 MHz",
                "10m": "28.120 MHz",
                "6m": "50.200 MHz",
                "2m": "144.800 MHz",
                "70cm": "433.500 MHz",
            }
            data_frequency = data_freq_map.get(band, "")
        else:
            mhz_match = re.search(r"(\d+\.?\d*)\s*MHz", freq_str, re.I)
            if mhz_match:
                data_frequency = f"{mhz_match.group(1)} MHz"
    except Exception:  # noqa: BLE001
        pass
    return frequency_info, data_frequency


def _tx_wait_until(
    stdscr: "curses._CursesWindow",
    until: datetime,
    *,
    countdown_to: datetime,
    status: str,
    message: str,
    fields: list[tuple[str, str]] | None = None,
) -> bool:
    """
    Wait until `until`, redrawing a countdown to `countdown_to`.
    Returns False if the user presses ESC.
    """
    stdscr.nodelay(True)
    footer = "HOURLY TX ARMED  ESC: STOP SCHEDULE"
    while True:
        now = datetime.now()
        if now >= until:
            return True
        ch = stdscr.getch()
        if ch == 27:
            return False
        _draw_tx_screen(
            stdscr,
            status,
            1.0,
            "Next TX",
            _format_countdown(countdown_to - now),
            message,
            fields=fields,
            footer_status=footer,
        )
        stdscr.refresh()
        time.sleep(0.25)


def _app_update_flow(stdscr: "curses._CursesWindow") -> bool:
    """
    Check GitHub Releases for a newer Windows installer and apply it.

    Returns True if the installer was launched (caller should exit the app).
    """
    from ceefaxstation.self_update import apply_update, check_for_update

    stdscr.nodelay(False)
    _draw_mode_screen(
        stdscr,
        mode="--",
        title="Application update",
        status="Checking GitHub Releases",
        fields=[("Source", "github.com/thaum-labs/ceefax_station")],
        message="Comparing installed version to the latest release...",
        footer_status="UPDATE CHECK  ESC: CANCEL",
    )
    stdscr.refresh()

    check_done = threading.Event()
    check_err: dict = {"err": None}
    check_result: dict = {"local": None, "latest": None, "available": False}

    def _check_worker() -> None:
        try:
            local, latest, available = check_for_update()
            check_result["local"] = local
            check_result["latest"] = latest
            check_result["available"] = available
        except Exception as exc:  # noqa: BLE001
            check_err["err"] = exc
        finally:
            check_done.set()

    threading.Thread(target=_check_worker, daemon=True).start()
    stdscr.nodelay(True)
    while not check_done.is_set():
        if stdscr.getch() == 27:
            return False
        _draw_mode_screen(
            stdscr,
            mode="--",
            title="Application update",
            status="Checking GitHub Releases",
            fields=[("Source", "github.com/thaum-labs/ceefax_station")],
            message="Comparing installed version to the latest release...",
            footer_status="UPDATE CHECK  ESC: CANCEL",
        )
        stdscr.refresh()
        time.sleep(0.1)
    stdscr.nodelay(False)

    if check_err["err"] is not None:
        _draw_mode_screen(
            stdscr,
            mode="--",
            title="Application update",
            status="Update check failed",
            message=str(check_err["err"])[:120],
            footer_status="ESC: RETURN",
        )
        while stdscr.getch() != 27:
            pass
        return False

    local = str(check_result["local"] or "")
    latest = check_result["latest"]
    available = bool(check_result["available"])
    remote_tag = getattr(latest, "tag", None) or "?"

    if not available:
        _draw_mode_screen(
            stdscr,
            mode="--",
            title="Application update",
            status="Already up to date",
            fields=[("Installed", local), ("Latest", remote_tag)],
            message="No newer GitHub release is available.",
            footer_status="ESC: RETURN",
        )
        while stdscr.getch() != 27:
            pass
        return False

    while True:
        _draw_mode_screen(
            stdscr,
            mode="--",
            title="Application update",
            status="Update available",
            fields=[
                ("Installed", local),
                ("Latest", remote_tag),
                ("Installs via", "Windows Setup (UAC may prompt)"),
            ],
            message="ENTER downloads the installer and upgrades in place. ESC cancels.",
            footer_status="UPDATE READY  ENTER: INSTALL  ESC: CANCEL",
        )
        ch = stdscr.getch()
        if ch in (10, 13, curses.KEY_ENTER):
            break
        if ch == 27:
            return False

    progress_msg = {"text": "Starting download..."}
    apply_done = threading.Event()
    apply_err: dict = {"err": None}
    apply_result: dict = {"result": None}

    def _apply_worker() -> None:
        try:
            apply_result["result"] = apply_update(
                force=False,
                silent=True,
                progress=lambda msg: progress_msg.__setitem__("text", msg),
            )
        except Exception as exc:  # noqa: BLE001
            apply_err["err"] = exc
        finally:
            apply_done.set()

    threading.Thread(target=_apply_worker, daemon=True).start()
    stdscr.nodelay(True)
    while not apply_done.is_set():
        _draw_mode_screen(
            stdscr,
            mode="--",
            title="Application update",
            status="Downloading / launching installer",
            fields=[("Installed", local), ("Latest", remote_tag)],
            message=str(progress_msg["text"])[:120],
            footer_status="PLEASE WAIT",
        )
        stdscr.refresh()
        time.sleep(0.15)
    stdscr.nodelay(False)

    if apply_err["err"] is not None:
        _draw_mode_screen(
            stdscr,
            mode="--",
            title="Application update",
            status="Update failed",
            message=str(apply_err["err"])[:120],
            footer_status="ESC: RETURN",
        )
        while stdscr.getch() != 27:
            pass
        return False

    result = apply_result["result"] or {}
    status = result.get("status")
    if status == "launched":
        _draw_mode_screen(
            stdscr,
            mode="--",
            title="Application update",
            status="Installer started",
            fields=[("From", local), ("To", remote_tag)],
            message="Approve UAC if prompted. The app will exit so files can be replaced.",
            footer_status="EXITING...",
        )
        stdscr.refresh()
        time.sleep(1.5)
        return True

    err = result.get("error") or status or "unknown error"
    _draw_mode_screen(
        stdscr,
        mode="--",
        title="Application update",
        status="Update failed",
        message=str(err)[:120],
        footer_status="ESC: RETURN",
    )
    while stdscr.getch() != 27:
        pass
    return False


def _tx_refresh_pages(
    stdscr: "curses._CursesWindow",
    pages: List[Page],
    *,
    src: str,
    page_dir: str,
    stage_label: str = "1 of 3",
) -> bool:
    """
    Check hub for a newer pack (apply + rebuild when newer), refresh local pages.
    Returns False if cancelled with ESC.
    """
    from ceefax.src.hub_pages import refresh_station_pages

    _draw_tx_screen(
        stdscr,
        "Checking hub pack / refreshing pages",
        fields=[("Stage", stage_label), ("Callsign", src), ("Pages loaded", str(len(pages)))],
        message="Downloads only when the website pack is newer.",
        footer_status="REFRESH  ESC: CANCEL",
    )
    stdscr.refresh()

    refresh_done = threading.Event()
    refresh_err: dict = {"err": None}
    refresh_result: dict = {"result": None}

    def _refresh_worker() -> None:
        try:
            refresh_result["result"] = refresh_station_pages(
                callsign=src,
                frequency="",
                auto_location=True,
            )
        except Exception as e:  # noqa: BLE001
            refresh_err["err"] = e
        finally:
            refresh_done.set()

    threading.Thread(target=_refresh_worker, daemon=True).start()
    stdscr.nodelay(True)
    while not refresh_done.is_set():
        ch = stdscr.getch()
        if ch == 27:
            _draw_tx_screen(
                stdscr,
                "Refresh cancelled (finishing in background)...",
                message="Returning to viewer.",
                footer_status="REFRESH  ESC: CANCEL",
            )
            time.sleep(1.0)
            return False
        _draw_tx_screen(
            stdscr,
            "Checking hub pack / refreshing pages",
            fields=[("Stage", stage_label), ("Callsign", src), ("Pages loaded", str(len(pages)))],
            message="Downloads only when the website pack is newer.",
            footer_status="REFRESH  ESC: CANCEL",
        )
        stdscr.refresh()
        time.sleep(0.1)

    if refresh_err["err"] is not None:
        raise refresh_err["err"]

    new_pages = load_all_pages(page_dir)
    if new_pages:
        pages[:] = new_pages
    return True


def _tx_generate_wav(
    stdscr: "curses._CursesWindow",
    pages: List[Page],
    *,
    cfg,
    src: str,
) -> tuple[str, List[str]]:
    """Build a single-loop AX.25 WAV (played 3× by the TX loop). Returns (wav, page_ids)."""
    from ceefax.src.ax25_audio import build_ax25_audio_plan, write_ax25_audio_wav_and_or_stdout

    _draw_tx_screen(
        stdscr,
        "Generating transmission file",
        fields=[("Stage", "2 of 3"), ("Callsign", src), ("Pages", str(len(pages)))],
        footer_status="TRANSMIT MODE  ESC: CANCEL",
    )
    stdscr.refresh()

    plan = build_ax25_audio_plan(
        pages=pages,
        loops=1,
        dest_callsign=cfg.ax25.dest_callsign,
        src_callsign=src,
        max_info_bytes=cfg.ax25.max_info_bytes,
    )
    wav = write_ax25_audio_wav_and_or_stdout(
        plan=plan,
        sample_rate=cfg.audio.sample_rate,
        symbol_rate=cfg.audio.symbol_rate,
        frequency_mark=cfg.audio.frequency_mark,
        frequency_space=cfg.audio.frequency_space,
        amplitude=cfg.audio.amplitude,
        preamble_flags=cfg.ax25.preamble_flags,
        inter_frame_flags=cfg.ax25.inter_frame_flags,
        postamble_flags=cfg.ax25.postamble_flags,
        output_dir=cfg.general.output_dir,
        output_mode=cfg.audio.output,
    )
    _draw_tx_screen(
        stdscr,
        "Transmission file ready",
        fields=[
            ("Stage", "2 of 3"),
            ("Callsign", src),
            ("Pages", str(len(pages))),
            ("Fragments", str(plan.fragments)),
        ],
        footer_status="TRANSMIT MODE  ESC: CANCEL",
    )
    stdscr.refresh()
    time.sleep(0.3)
    return wav, list(plan.page_ids)


def _wav_duration_seconds(path: str) -> float:
    """Best-effort WAV duration in seconds (PCM)."""
    try:
        import wave

        with wave.open(path, "rb") as wf:
            rate = int(wf.getframerate() or 0)
            frames = int(wf.getnframes() or 0)
            if rate > 0 and frames > 0:
                return frames / float(rate)
    except Exception:  # noqa: BLE001
        pass
    try:
        # Fallback: assume 48 kHz 16-bit mono PCM payload roughly file_size/rate/2
        return max(1.0, os.path.getsize(path) / (48000.0 * 2.0))
    except Exception:  # noqa: BLE001
        return 30.0


def _estimate_tx_page(
    page_ids: List[str],
    *,
    loop_elapsed: float,
    loop_duration: float,
) -> tuple[str, int, int]:
    """
    Estimate which page is on-air within one carousel loop.

    Returns (page_id, page_index_1based, page_count).
    """
    ids = [str(p) for p in (page_ids or []) if str(p).strip()]
    n = len(ids) or 1
    if not ids:
        ids = ["?"]
    if loop_duration <= 0:
        return ids[0], 1, n
    frac = max(0.0, min(0.999999, float(loop_elapsed) / float(loop_duration)))
    idx = min(n - 1, int(frac * n))
    return ids[idx], idx + 1, n


def _tx_play_three_loops(
    stdscr: "curses._CursesWindow",
    wav: str,
    *,
    page_ids: List[str] | None = None,
) -> bool:
    """Play the WAV three times with estimated per-page progress. ESC cancels."""
    from ceefax.src.playback import play_wav_file

    pages_in_loop = [str(p) for p in (page_ids or []) if str(p).strip()]
    loop_duration = _wav_duration_seconds(wav)
    stdscr.nodelay(True)

    for tx_num in range(1, 4):
        playback_done = threading.Event()
        playback_stop = threading.Event()
        playback_err: dict = {"err": None}
        playback_proc: dict = {"proc": None}
        loop_started = time.monotonic()

        def _playback_worker() -> None:
            try:
                if sys.platform.startswith("win"):
                    try:
                        wav_escaped = wav.replace("'", "''")
                        proc = subprocess.Popen(
                            [
                                "powershell",
                                "-Command",
                                f"(New-Object Media.SoundPlayer '{wav_escaped}').PlaySync()",
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=(
                                subprocess.CREATE_NO_WINDOW
                                if hasattr(subprocess, "CREATE_NO_WINDOW")
                                else 0
                            ),
                        )
                        playback_proc["proc"] = proc
                        proc.wait()
                    except Exception:  # noqa: BLE001
                        import winsound

                        winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
                        elapsed = 0.0
                        while elapsed < loop_duration and not playback_stop.is_set():
                            time.sleep(0.1)
                            elapsed += 0.1
                else:
                    play_wav_file(wav, loops=1)
            except Exception as e:  # noqa: BLE001
                playback_err["err"] = e
            finally:
                playback_done.set()

        threading.Thread(target=_playback_worker, daemon=True).start()

        while not playback_done.is_set():
            ch = stdscr.getch()
            if ch == 27:
                playback_stop.set()
                if playback_proc["proc"]:
                    try:
                        playback_proc["proc"].terminate()
                        playback_proc["proc"].wait(timeout=0.5)
                    except Exception:  # noqa: BLE001
                        try:
                            playback_proc["proc"].kill()
                        except Exception:  # noqa: BLE001
                            pass
                _draw_tx_screen(
                    stdscr,
                    "Transmission cancelled",
                    (tx_num - 1) / 3.0,
                    f"Transmission {tx_num}/3",
                    message="Returning to viewer.",
                    footer_status="TRANSMITTING  ESC: STOP",
                )
                stdscr.refresh()
                time.sleep(1.0)
                return False

            loop_elapsed = max(0.0, time.monotonic() - loop_started)
            page_id, page_i, page_n = _estimate_tx_page(
                pages_in_loop,
                loop_elapsed=loop_elapsed,
                loop_duration=loop_duration,
            )
            loop_frac = (
                max(0.0, min(1.0, loop_elapsed / loop_duration)) if loop_duration > 0 else 0.0
            )
            overall = ((tx_num - 1) + loop_frac) / 3.0
            remain = max(0.0, (3.0 - ((tx_num - 1) + loop_frac)) * loop_duration)
            remain_m = int(remain // 60)
            remain_s = int(remain % 60)
            _draw_tx_screen(
                stdscr,
                f"Transmitting page {page_id} (est.)",
                overall,
                f"Loop {tx_num}/3",
                show_logo=True,
                fields=[
                    ("Loop", f"{tx_num}/3"),
                    ("Page", f"{page_id} ({page_i}/{page_n})"),
                    ("Pages left", str(max(0, page_n - page_i))),
                    ("Est. left", f"{remain_m:02d}:{remain_s:02d}"),
                ],
                footer_status="TRANSMITTING  ESC: STOP  (page progress estimated)",
            )
            stdscr.refresh()
            time.sleep(0.15)

        progress = tx_num / 3.0
        if playback_err["err"] is not None:
            _draw_tx_screen(
                stdscr,
                f"Transmission {tx_num}/3 failed: {str(playback_err['err'])[:40]}",
                progress,
                f"Transmission {tx_num}/3",
                footer_status="TRANSMITTING  ESC: STOP",
            )
            stdscr.refresh()
            time.sleep(2)
        else:
            _draw_tx_screen(
                stdscr,
                f"Transmission {tx_num}/3 complete",
                progress,
                f"Transmission {tx_num}/3",
                show_logo=True,
                footer_status="TRANSMITTING  ESC: STOP",
            )
            stdscr.refresh()
            time.sleep(0.3)
    try:
        from ceefax.src.ax25_audio import finalize_tx_report

        finalize_tx_report(wav)
    except Exception:  # noqa: BLE001
        pass
    return True


def _tx_mode_loop(stdscr: "curses._CursesWindow", pages: List[Page]) -> None:
    """
    TX mode: transmit now (3 loops), then stay armed and retransmit each hour.

    First cycle asks for confirmation. Later hourly cycles refresh/build near the
    hour and transmit without re-confirming. ESC leaves TX mode at any wait/play.
    """
    from ceefax.src.config import load_config

    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    cfg = load_config()
    from .paths import ceefax_root

    config_file = ceefax_root() / "radio_config.json"
    callsign = None
    if config_file.exists():
        try:
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
            callsign = str(config_data.get("callsign") or "").strip().upper()
        except Exception:  # noqa: BLE001
            pass

    if not callsign:
        callsign = _prompt_callsign_in_tui(stdscr)
        if not callsign:
            return

    src = callsign or cfg.ax25.callsign or "N0CALL"
    lead = max(0, int(getattr(cfg.ax25, "refresh_lead_seconds", 180) or 180))
    map_message = (
        "Visit https://ceefaxstation.com to see your station on the map. "
        "Hourly TX armed — ESC stops the schedule."
    )

    try:
        # --- First (on-demand) cycle: refresh → build → confirm → TX ---
        if not _tx_refresh_pages(stdscr, pages, src=src, page_dir=cfg.general.page_dir):
            return

        wav, tx_page_ids = _tx_generate_wav(stdscr, pages, cfg=cfg, src=src)
        frequency_info, data_frequency = _tx_frequency_labels(config_file)
        if not _confirm_tx(
            stdscr,
            callsign=src,
            frequency=frequency_info,
            data_frequency=data_frequency,
            page_count=len(pages),
            repetitions=3,
        ):
            return

        if not _tx_play_three_loops(stdscr, wav, page_ids=tx_page_ids):
            return

        # --- Hourly cycles until ESC ---
        while True:
            now = datetime.now()
            hour = _next_hour_local(now)
            refresh_at = hour - timedelta(seconds=lead)
            hour_label = hour.strftime("%H:00")
            wait_fields = [
                ("Callsign", src),
                ("Next TX", hour_label),
                ("Prepare at", refresh_at.strftime("%H:%M:%S")),
                ("Status", "Waiting"),
            ]

            if now < refresh_at:
                if not _tx_wait_until(
                    stdscr,
                    refresh_at,
                    countdown_to=hour,
                    status=f"Next transmission at {hour_label}",
                    message=map_message,
                    fields=wait_fields,
                ):
                    return

            prep_fields = [
                ("Callsign", src),
                ("Next TX", hour_label),
                ("Status", "Preparing"),
            ]
            _draw_tx_screen(
                stdscr,
                f"Preparing hourly TX for {hour_label}",
                fields=prep_fields,
                footer_status="HOURLY TX ARMED  ESC: STOP SCHEDULE",
            )
            stdscr.refresh()

            if not _tx_refresh_pages(
                stdscr,
                pages,
                src=src,
                page_dir=cfg.general.page_dir,
                stage_label="hourly",
            ):
                return

            wav, tx_page_ids = _tx_generate_wav(stdscr, pages, cfg=cfg, src=src)

            now2 = datetime.now()
            if now2 < hour:
                if not _tx_wait_until(
                    stdscr,
                    hour,
                    countdown_to=hour,
                    status=f"Ready — starting at {hour_label}",
                    message=map_message,
                    fields=[
                        ("Callsign", src),
                        ("Next TX", hour_label),
                        ("Pages", str(len(pages))),
                        ("Status", "Armed"),
                    ],
                ):
                    return
            else:
                _draw_tx_screen(
                    stdscr,
                    f"Hour boundary passed — transmitting now ({hour_label})",
                    fields=[
                        ("Callsign", src),
                        ("Target", hour_label),
                        ("Pages", str(len(pages))),
                        ("Status", "Starting"),
                    ],
                    footer_status="HOURLY TX ARMED  ESC: STOP SCHEDULE",
                )
                stdscr.refresh()
                time.sleep(0.5)

            if not _tx_play_three_loops(stdscr, wav, page_ids=tx_page_ids):
                return

    except Exception as e:  # noqa: BLE001
        _draw_tx_screen(stdscr, f"Error: {str(e)[:50]}", 0.0, "Error")
        stdscr.refresh()
        time.sleep(3)


def _rx_mode_loop(stdscr: "curses._CursesWindow", pages: List[Page]) -> None:
    """
    RX mode: Auto-detect soundcard and start live reception.
    """
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)
    
    # Show initializing message with RX logo
    _draw_rx_screen(stdscr, "Initializing receive mode...", "Auto-detecting soundcard...")
    
    # Find direwolf
    dw = _find_direwolf_exe(None)
    
    # Auto-detect device (None = auto-detect)
    device = None
    
    # Get listener callsign from config or use default
    from .paths import ceefax_root

    config_file = ceefax_root() / "radio_config.json"
    listener = None
    
    if config_file.exists():
        try:
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
            listener = config_data.get("callsign", "").strip().upper()
        except Exception:  # noqa: BLE001
            pass
    
    # Start live RX mode (this will handle its own loop and ESC key)
    _rx_viewer_loop_live(
        stdscr,
        dw,
        dest_filter="CEEFAX",
        listener_callsign=listener,
        device=device,
        config_path=None,
        sample_rate=48000,
        baud=1200,
    )


def _viewer_loop(stdscr: "curses._CursesWindow", pages: List[Page]) -> None:
    curses.curs_set(0)  # hide cursor
    stdscr.nodelay(False)
    stdscr.keypad(True)

    idx = 0

    def compile_all() -> List[List[str]]:
        return [compile_page_to_matrix(p) for p in pages]

    matrices = compile_all()
    page_entry = ""
    notice = ""

    while True:
        if not pages:
            _draw_mode_screen(
                stdscr,
                mode="--",
                title="Page viewer",
                status="No pages loaded",
                fields=[("Action", "Press F5 to refresh")],
                message="Generate or receive pages, then refresh the viewer.",
                footer_status="NO PAGES  F5: REFRESH  ESC: EXIT",
                footer_mode="viewer",
            )
        else:
            page = pages[idx]
            matrix = matrices[idx]
            _draw_page(
                stdscr,
                page,
                matrix,
                idx,
                len(pages),
                page_entry=page_entry,
                notice=notice,
            )

        ch = stdscr.getch()
        idx, page_entry, key_notice, handled = _handle_page_key(ch, pages, idx, page_entry)
        if handled:
            notice = key_notice
            continue
        page_entry = ""
        notice = ""
        if ch in (ord("q"), ord("Q")) or ch == 27:
            break
        if ch in (ord("n"), curses.KEY_RIGHT, curses.KEY_NPAGE):
            if pages:
                idx = (idx + 1) % len(pages)
        elif ch in (ord("p"), curses.KEY_LEFT, curses.KEY_PPAGE):
            if pages:
                idx = (idx - 1) % len(pages)
        elif ch == curses.KEY_F5:
            # Check hub for a newer pack, rebuild pages, then reload viewer.
            cfg = load_config()
            rcfg = _load_radio_config()
            src = ""
            if isinstance(rcfg, dict):
                src = str(rcfg.get("callsign") or "").strip().upper()
            try:
                ok = _tx_refresh_pages(
                    stdscr,
                    pages,
                    src=src or "N0CALL",
                    page_dir=cfg.general.page_dir,
                    stage_label="F5 refresh",
                )
            except Exception as exc:  # noqa: BLE001
                notice = f"REFRESH FAILED: {exc}"
                continue
            if not ok:
                notice = "REFRESH CANCELLED"
                continue
            new_pages = load_all_pages(cfg.general.page_dir)
            if new_pages:
                pages[:] = new_pages
                matrices[:] = compile_all()
                idx = min(idx, len(pages) - 1)
                notice = f"REFRESHED {len(pages)} PAGES"
            else:
                notice = "REFRESHED (NO PAGES FOUND)"
        elif ch in (ord("r"), ord("R")):
            # Enter RX mode
            _rx_mode_loop(stdscr, pages)
            # After RX mode, reload pages in case new ones were received
            cfg = load_config()
            new_pages = load_all_pages(cfg.general.page_dir)
            if new_pages:
                pages[:] = new_pages
                matrices[:] = compile_all()
        elif ch in (ord("t"), ord("T")):
            # Enter TX mode
            _tx_mode_loop(stdscr, pages)
            # After TX mode, reload pages in case they were refreshed
            cfg = load_config()
            new_pages = load_all_pages(cfg.general.page_dir)
            if new_pages:
                pages[:] = new_pages
                matrices[:] = compile_all()
        elif ch in (ord("s"), ord("S")):
            saved = _station_setup_in_tui(stdscr, force=True)
            notice = "STATION SETTINGS SAVED" if saved else "STATION SETUP CANCELLED"
        elif ch in (ord("u"), ord("U")):
            if _app_update_flow(stdscr):
                break
            notice = ""


def _rx_viewer_loop_from_wav(
    stdscr: "curses._CursesWindow",
    wav_path: str,
    direwolf_exe: str,
    dest_filter: str = "CEEFAX",
    listener_callsign: str | None = None,
) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(100)  # allow periodic redraw/updates

    pages: List[Page] = []
    matrices: List[List[str]] = []
    idx = 0
    page_entry = ""
    notice = ""

    q: "queue.Queue[tuple[Page, List[str]]]" = queue.Queue()
    stop_event = threading.Event()
    stats_lock = threading.Lock()
    rcfg = _load_radio_config()
    freq = (rcfg.get("frequency") or "").strip() if isinstance(rcfg, dict) else ""
    grid = (rcfg.get("grid") or "").strip().upper() if isinstance(rcfg, dict) else ""
    stats: dict = {
        "schema": 1,
        "listener_callsign": (listener_callsign or "").strip(),
        "listener_grid": grid or None,
        "dest_filter": dest_filter,
        "wav_path": str(wav_path),
        "wav_name": Path(wav_path).name,
        "started_at": datetime.now().isoformat(),
        "frequency": freq or None,
        "rx_db": None,
        "station_callsign": None,
        "tx_id": None,
        "tx_ids_seen": [],
        "cfx_frames": 0,
        "stations_heard": {},
        "pages_decoded": {},
        "page_progress": {},
    }
    log_path = _log_path_for_wav(wav_path)
    _update_rx_log_summary(stats)
    _write_json(log_path, stats)

    # Start Dire Wolf RX thread.
    rx_err = {"msg": None}

    def rx_thread():
        try:
            _rx_pages_from_wav_with_direwolf(
                wav_path=wav_path,
                direwolf_exe=direwolf_exe,
                dest_filter=dest_filter,
                out_q=q,
                stop_event=stop_event,
                stats=stats,
                stats_lock=stats_lock,
                log_path=log_path,
            )
        except FileNotFoundError:
            rx_err["msg"] = f"Dire Wolf not found: {direwolf_exe}"
        except Exception as exc:  # noqa: BLE001
            rx_err["msg"] = f"RX error: {exc}"
        finally:
            if rx_err["msg"]:
                with stats_lock:
                    stats["rx_error"] = rx_err["msg"]

    t = threading.Thread(target=rx_thread, daemon=True)
    t.start()

    try:
        while True:
            # Drain any newly completed pages.
            updated = False
            while True:
                try:
                    page_obj, matrix = q.get_nowait()
                except queue.Empty:
                    break
                _upsert_sorted_page(pages, matrices, page_obj, matrix)
                updated = True

            if pages:
                idx = max(0, min(idx, len(pages) - 1))
                with stats_lock:
                    snapshot = dict(stats)
                _draw_page(
                    stdscr,
                    pages[idx],
                    matrices[idx],
                    idx,
                    len(pages),
                    callsign_override=listener_callsign,
                    page_entry=page_entry,
                    notice=notice or _rx_footer_status(snapshot),
                    footer_mode="rx",
                )
            else:
                # Show RX screen with waiting message
                msg = rx_err["msg"] or f"Waiting for AX.25 pages from WAV: {Path(wav_path).name}"
                with stats_lock:
                    snapshot = dict(stats)
                _draw_rx_screen(
                    stdscr,
                    "Listening",
                    msg,
                    stats=snapshot,
                    source=Path(wav_path).name,
                )

            ch = stdscr.getch()
            idx, page_entry, key_notice, handled = _handle_page_key(ch, pages, idx, page_entry)
            if handled:
                notice = key_notice
                continue
            page_entry = ""
            notice = ""
            if ch in (ord("q"), ord("Q")) or ch == 27:  # q or ESC
                break
            if ch in (ord("n"), curses.KEY_RIGHT, curses.KEY_NPAGE):
                if pages:
                    idx = (idx + 1) % len(pages)
            elif ch in (ord("p"), curses.KEY_LEFT, curses.KEY_PPAGE):
                if pages:
                    idx = (idx - 1) % len(pages)
            elif ch in (ord("r"), ord("R")):
                # In RX mode, treat reload as a no-op (WAV is immutable).
                pass

            # Avoid busy-loop if nothing is happening.
            if not updated:
                time.sleep(0.02)
    finally:
        stop_event.set()
        with stats_lock:
            stats["ended_at"] = datetime.now().isoformat()
            # Flatten a useful page list for later upload.
            decoded = list(stats.get("pages_decoded", {}).values())
            stats["decoded_pages"] = sorted(decoded, key=lambda x: (int(x["page"]), int(x["subpage"])))
            _update_rx_log_summary(stats)
        _write_json(log_path, stats)


def _rx_viewer_loop_live(
    stdscr: "curses._CursesWindow",
    direwolf_exe: str,
    *,
    dest_filter: str = "CEEFAX",
    listener_callsign: str | None = None,
    device: str | None = None,
    config_path: str | None = None,
    sample_rate: int = 48000,
    baud: int = 1200,
) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(100)

    pages: List[Page] = []
    matrices: List[List[str]] = []
    idx = 0
    page_entry = ""
    notice = ""

    q: "queue.Queue[tuple[Page, List[str]]]" = queue.Queue()
    stop_event = threading.Event()
    stats_lock = threading.Lock()
    rcfg = _load_radio_config()
    freq = (rcfg.get("frequency") or "").strip() if isinstance(rcfg, dict) else ""
    grid = (rcfg.get("grid") or "").strip().upper() if isinstance(rcfg, dict) else ""

    # Create a stable log path for the session.
    live_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    from .paths import ceefax_root

    log_path = (ceefax_root() / "logs_rx" / f"ceefax_ax25_live_{live_ts}.json")

    stats: dict = {
        "schema": 1,
        "listener_callsign": (listener_callsign or "").strip(),
        "listener_grid": grid or None,
        "dest_filter": dest_filter,
        "rx_mode": "live",
        "started_at": datetime.now().isoformat(),
        "frequency": freq or None,
        "rx_db": None,
        "station_callsign": None,
        "tx_id": None,
        "tx_ids_seen": [],
        "cfx_frames": 0,
        "stations_heard": {},
        "pages_decoded": {},
        "page_progress": {},
    }
    _update_rx_log_summary(stats)
    _write_json(log_path, stats)

    rx_err = {"msg": None}

    def rx_thread():
        try:
            _rx_pages_from_live_with_direwolf(
                direwolf_exe=direwolf_exe,
                dest_filter=dest_filter,
                out_q=q,
                stop_event=stop_event,
                stats=stats,
                stats_lock=stats_lock,
                log_path=log_path,
                config_path=config_path,
                device=device,
                sample_rate=sample_rate,
                baud=baud,
            )
        except FileNotFoundError:
            rx_err["msg"] = f"Dire Wolf not found: {direwolf_exe}"
        except Exception as exc:  # noqa: BLE001
            rx_err["msg"] = f"RX error: {exc}"
        finally:
            if rx_err["msg"]:
                with stats_lock:
                    stats["rx_error"] = rx_err["msg"]

    t = threading.Thread(target=rx_thread, daemon=True)
    t.start()

    try:
        while True:
            updated = False
            while True:
                try:
                    page_obj, matrix = q.get_nowait()
                except queue.Empty:
                    break
                _upsert_sorted_page(pages, matrices, page_obj, matrix)
                updated = True

            if pages:
                idx = max(0, min(idx, len(pages) - 1))
                with stats_lock:
                    snapshot = dict(stats)
                _draw_page(
                    stdscr,
                    pages[idx],
                    matrices[idx],
                    idx,
                    len(pages),
                    callsign_override=listener_callsign,
                    page_entry=page_entry,
                    notice=notice or _rx_footer_status(snapshot),
                    footer_mode="rx",
                )
            else:
                # Show RX screen with waiting message
                msg = rx_err["msg"] or "Waiting for AX.25 pages from live audio..."
                with stats_lock:
                    snapshot = dict(stats)
                _draw_rx_screen(
                    stdscr,
                    "Listening",
                    msg,
                    stats=snapshot,
                    source="Live audio",
                    device=device or "Default device",
                )

            ch = stdscr.getch()
            idx, page_entry, key_notice, handled = _handle_page_key(ch, pages, idx, page_entry)
            if handled:
                notice = key_notice
                continue
            page_entry = ""
            notice = ""
            if ch in (ord("q"), ord("Q")) or ch == 27:  # q or ESC
                break
            if ch in (ord("n"), curses.KEY_RIGHT, curses.KEY_NPAGE):
                if pages:
                    idx = (idx + 1) % len(pages)
            elif ch in (ord("p"), curses.KEY_LEFT, curses.KEY_PPAGE):
                if pages:
                    idx = (idx - 1) % len(pages)

            if not updated:
                time.sleep(0.02)
    finally:
        stop_event.set()
        with stats_lock:
            stats["ended_at"] = datetime.now().isoformat()
            decoded = list(stats.get("pages_decoded", {}).values())
            stats["decoded_pages"] = sorted(decoded, key=lambda x: (int(x["page"]), int(x["subpage"])))
            _update_rx_log_summary(stats)
        _write_json(log_path, stats)


def main() -> None:
    """
    Launch a simple Ceefax-style viewer in the terminal using curses.
    """
    parser = argparse.ArgumentParser(prog="ceefax-viewer")
    parser.add_argument(
        "--rx-wav",
        dest="rx_wav",
        default=None,
        help="Decode a 48kHz AFSK1200 WAV via Dire Wolf and display pages live.",
    )
    parser.add_argument(
        "--rx-latest",
        dest="rx_latest",
        action="store_true",
        help="Decode the most recently generated WAV in the configured output_dir.",
    )
    parser.add_argument(
        "--rx-live",
        dest="rx_live",
        action="store_true",
        help="Decode live AFSK1200 audio via Dire Wolf from a sound device.",
    )
    parser.add_argument(
        "--listener",
        dest="listener",
        default=None,
        help="Listener/receiver call sign (if omitted, you will be prompted).",
    )
    parser.add_argument(
        "--direwolf",
        dest="direwolf",
        default=None,
        help="Path to the Dire Wolf executable (bundled tools/direwolf on Windows, or PATH on Linux).",
    )
    parser.add_argument(
        "--dest",
        dest="dest",
        default="CEEFAX",
        help="AX.25 destination callsign filter (default: CEEFAX).",
    )
    parser.add_argument(
        "--device",
        dest="device",
        default=None,
        help="Dire Wolf ADEVICE string/substring for live RX (e.g. 'USB' or 'Realtek High').",
    )
    parser.add_argument(
        "--direwolf-config",
        dest="direwolf_config",
        default=None,
        help="Path to direwolf.conf to use for live RX (defaults to direwolf.conf next to the direwolf executable).",
    )
    parser.add_argument(
        "--sample-rate",
        dest="sample_rate",
        type=int,
        default=48000,
        help="Audio sample rate for live RX (default: 48000).",
    )
    parser.add_argument(
        "--baud",
        dest="baud",
        type=int,
        default=1200,
        help="AFSK baud rate for live RX (default: 1200).",
    )
    args = parser.parse_args()

    config = load_config()

    # Resolve RX mode inputs BEFORE curses starts. Prompts via `input()` don't behave
    # well once curses has taken control of the terminal.
    rx_wav = args.rx_wav
    if args.rx_latest or (isinstance(rx_wav, str) and rx_wav.lower() == "latest"):
        rx_wav = _find_latest_wav_in_output_dir(config.general.output_dir)

    listener = (args.listener or "").strip().upper()
    if rx_wav and not listener:
        listener = _prompt_callsign()

    # We pass pages by reference so reload can update in-place.
    def runner(stdscr: "curses._CursesWindow") -> None:
        if args.rx_live:
            dw = _find_direwolf_exe(args.direwolf)
            _rx_viewer_loop_live(
                stdscr,
                dw,
                dest_filter=args.dest,
                listener_callsign=listener,
                device=(args.device or None),
                config_path=(args.direwolf_config or None),
                sample_rate=int(args.sample_rate),
                baud=int(args.baud),
            )
        elif rx_wav:
            dw = _find_direwolf_exe(args.direwolf)
            _rx_viewer_loop_from_wav(
                stdscr,
                rx_wav,
                dw,
                dest_filter=args.dest,
                listener_callsign=listener,
            )
        else:
            _station_setup_in_tui(stdscr)
            pages = load_all_pages(config.general.page_dir)
            _viewer_loop(stdscr, pages)

    curses.wrapper(runner)


if __name__ == "__main__":
    main()


