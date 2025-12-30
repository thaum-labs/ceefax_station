import argparse
import curses
import json
import queue
import re
import subprocess
import threading
import time
from datetime import datetime
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


def _find_direwolf_exe(explicit: str | None = None) -> str:
    """
    Find bundled direwolf.exe or fall back to PATH.
    """
    if explicit:
        return explicit

    # Prefer bundled path: ceefax/tools/direwolf/direwolf.exe
    ceefax_root = Path(__file__).resolve().parent.parent
    candidate = ceefax_root / "tools" / "direwolf" / "direwolf.exe"
    if candidate.exists():
        return str(candidate)

    return "direwolf.exe"


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
    ceefax_root = Path(__file__).resolve().parent.parent
    return ceefax_root / "logs_rx"


def _log_path_for_wav(wav_path: str) -> Path:
    p = Path(wav_path)
    return _log_dir() / f"{p.stem}.json"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_radio_config() -> dict:
    """
    Best-effort read of ceefax/radio_config.json so RX logs can include frequency/grid
    metadata for the web tracker.
    """
    try:
        ceefax_root = Path(__file__).resolve().parent.parent
        p = ceefax_root / "radio_config.json"
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


_AUDIO_LEVEL_RE = re.compile(r"audio level[^0-9\\-]*(-?\\d+(?:\\.\\d+)?)", re.I)


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
) -> None:
    stdscr.clear()
    max_y, max_x = stdscr.getmaxyx()

    # Require at least PAGE_WIDTH x PAGE_HEIGHT area
    if max_y < PAGE_HEIGHT or max_x < PAGE_WIDTH:
        msg = f"Terminal too small. Need at least {PAGE_WIDTH}x{PAGE_HEIGHT}."
        stdscr.addstr(0, 0, msg[: max_x - 1])
        stdscr.refresh()
        return

    # Center the frame
    offset_y = max((max_y - PAGE_HEIGHT) // 2, 0)
    offset_x = max((max_x - PAGE_WIDTH) // 2, 0)

    # Build Ceefax-style header line (ignore matrix[0], construct our own)
    # Example: "CEEFAX 100 NEWS HEADLINES     12:34 06 DEC"
    now = datetime.now()
    clock = now.strftime("%H:%M %d %b").upper()  # e.g. "12:34 06 DEC"
    title = (page.title or "").upper()[:20]
    page_num = (page.page or "").rjust(3)

    # Base header text without the clock; we'll overlay the time at the
    # far right so it stays aligned to the edge of the blue bar.
    base_header = f"CEEFAX {page_num} {title}"
    header_text = base_header[:PAGE_WIDTH].ljust(PAGE_WIDTH)

    # Colours
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_YELLOW, curses.COLOR_BLUE)   # header
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # body (classic Ceefax yellow text)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)     # RED
        curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)   # GREEN
        curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # YELLOW
        curses.init_pair(6, curses.COLOR_BLUE, curses.COLOR_BLACK)    # BLUE

        header_attr = curses.color_pair(1) | curses.A_BOLD
        body_attr = curses.color_pair(2)
    else:
        header_attr = curses.A_BOLD
        body_attr = curses.A_NORMAL

    # Header (row 0)
    stdscr.addstr(offset_y, offset_x, header_text[:PAGE_WIDTH], header_attr)

    # "P<page>" indicator at absolute top-left (outside centred frame),
    # similar to classic Ceefax layout.
    p_code = f"P{page.page}".ljust(4)
    stdscr.addstr(offset_y, 0, p_code, header_attr)

    # Get call sign first to calculate positions
    callsign = (callsign_override or "").strip()
    if not callsign:
        try:
            from pathlib import Path
            import json

            root = Path(__file__).resolve().parent.parent
            config_file = root / "radio_config.json"
            if config_file.exists():
                config_data = json.loads(config_file.read_text(encoding="utf-8"))
                callsign = config_data.get("callsign", "")
        except Exception:  # noqa: BLE001
            pass
    
    # Calculate positions: call sign (if present) then clock, both right-aligned
    clock_x = offset_x + max(PAGE_WIDTH - len(clock) - 1, 0)
    
    if callsign:
        # Place call sign to the left of the clock on the same header row
        # Format: "CALLSIGN  12:34 06 DEC"
        callsign_x = clock_x - len(callsign) - 2  # 2 spaces between callsign and clock
        if callsign_x >= offset_x:
            stdscr.addstr(offset_y, callsign_x, callsign, header_attr)
            stdscr.addstr(offset_y, callsign_x + len(callsign), "  ", header_attr)  # Add spacing
        else:
            # If callsign is too long, place it before clock with minimal spacing
            callsign_x = max(offset_x, clock_x - len(callsign) - 1)
            stdscr.addstr(offset_y, callsign_x, callsign[:clock_x - callsign_x - 1], header_attr)
    
    # Overlay clock at top-right corner of the blue header bar
    stdscr.addstr(offset_y, clock_x, clock, header_attr)

    is_start_page = (page.page == "000")

    # ASCII-art "CEEFAX STATION" logo area below header.
    if curses.has_colors():
        art_attr = header_attr  # yellow on blue, bold
    else:
        art_attr = curses.A_BOLD

    # Keep the header area compact to maximize content space.
    # For the start page, skip the extra logo so the splash sits in the middle.
    ceefax_art = [] if is_start_page else ["CEEFAX STATION".center(PAGE_WIDTH)]

    # ASCII art starts on row 1 (below header)
    art_row = offset_y + 1
    for i, line in enumerate(ceefax_art):
        row = art_row + i
        if row >= offset_y + PAGE_HEIGHT:
            break
        stdscr.addstr(
            row,
            offset_x,
            line[:PAGE_WIDTH].ljust(PAGE_WIDTH),
            art_attr,
        )

    # Remaining lines: show from matrix[1:] (timestamp + content),
    # formatted with a bold heading and a yellow rule beneath it.
    start_row = art_row + len(ceefax_art)

    # Treat matrix[2:] (compiled content rows) as on-screen content.
    # We deliberately skip the timestamp row (matrix[1]) so that the
    # first content line appears directly under the logo area.
    content_lines = matrix[2:PAGE_HEIGHT]

    current_row = start_row

    if content_lines:
        # Special-case start page: render content as-is (no injected rule/heading),
        # and substitute the callsign placeholder.
        if is_start_page:
            # Draw a border around the start page body (below the blue header).
            # We keep the header untouched and render the page content inside the box.
            border_attr = body_attr | curses.A_BOLD
            border_top = start_row
            border_bottom = offset_y + PAGE_HEIGHT - 1
            inner_x = offset_x + 1
            inner_width = max(PAGE_WIDTH - 2, 1)

            if border_bottom > border_top:
                top_line = ("+" + ("-" * (PAGE_WIDTH - 2)) + "+")[:PAGE_WIDTH]
                stdscr.addstr(border_top, offset_x, top_line, border_attr)
                stdscr.addstr(border_bottom, offset_x, top_line, border_attr)

                for row in range(border_top + 1, border_bottom):
                    stdscr.addstr(row, offset_x, "|", border_attr)
                    stdscr.addstr(row, offset_x + PAGE_WIDTH - 1, "|", border_attr)

            # Start rendering on the first row inside the border.
            current_row = border_top + 1

            for line in content_lines:
                if current_row >= offset_y + PAGE_HEIGHT:
                    break
                if current_row >= border_bottom:
                    break

                raw = (line or "")
                if "{{users callsign}}" in raw:
                    cs = (callsign or "").strip()
                    repl = f"{cs} TELETEX SERVICE".strip() if cs else "TELETEX SERVICE"
                    raw = repl

                # Center everything on the start page (including instructions).
                txt = raw.strip()
                rendered = ("" if not txt else txt[:inner_width].center(inner_width))

                stdscr.addstr(current_row, inner_x, rendered, body_attr | curses.A_BOLD)
                current_row += 1
            stdscr.refresh()
            return

        # If the page already draws its own separator near the top (e.g. ASCII art
        # panels), don't inject an extra rule line in the viewer.
        def _is_sep(line: str) -> bool:
            s = line.strip()
            return bool(s) and all(ch == "-" for ch in s)

        has_own_rule = any(_is_sep(l) for l in content_lines[:3])

        # First content line as a bold heading.
        heading = content_lines[0]
        stdscr.addstr(current_row, offset_x, heading[:PAGE_WIDTH], body_attr | curses.A_BOLD)
        current_row += 1

        # Optional injected rule (only if the page doesn't already have one).
        if not has_own_rule and current_row < offset_y + PAGE_HEIGHT:
            rule_text = "-" * PAGE_WIDTH
            if curses.has_colors():
                # Keep separators uniform: always yellow (same as body text).
                rule_attr = body_attr
            else:
                rule_attr = curses.A_UNDERLINE
            stdscr.addstr(current_row, offset_x, rule_text[:PAGE_WIDTH], rule_attr)
            current_row += 1

        # Remaining content
        for line in content_lines[1:]:
            if current_row >= offset_y + PAGE_HEIGHT:
                break
            stdscr.addstr(current_row, offset_x, line[:PAGE_WIDTH], body_attr)
            current_row += 1

    # "Fastext" bar one line above bottom
    fastext_y = max_y - 2
    if fastext_y > offset_y + PAGE_HEIGHT:
        # Center the fastext labels instead of left-aligning.
        if curses.has_colors():
            labels = [
                (" RED ", curses.color_pair(3) | curses.A_BOLD),
                (" GREEN ", curses.color_pair(4) | curses.A_BOLD),
                (" YELLOW ", curses.color_pair(5) | curses.A_BOLD),
                (" BLUE ", curses.color_pair(6) | curses.A_BOLD),
            ]
            total_len = sum(len(text) for text, _ in labels)
            x = max((max_x - 1 - total_len) // 2, 0)
            for text, attr in labels:
                if x >= max_x - 1:
                    break
                stdscr.addstr(fastext_y, x, text[: max_x - 1 - x], attr)
                x += len(text)
        else:
            line = "RED  GREEN  YELLOW  BLUE"
            x = max((max_x - 1 - len(line)) // 2, 0)
            stdscr.addstr(fastext_y, x, line[: max_x - 1 - x])

    # Status line at bottom, centred horizontally to match header
    status = f"Page {page.page_id}  ({index + 1}/{total})  n/p: next/prev  r: reload  q: quit"
    status_line = status[: max_x - 1]
    pad_width = max_x - 1
    start_x = max((pad_width - len(status_line)) // 2, 0)

    stdscr.attron(curses.A_REVERSE)
    # Clear the whole status row
    stdscr.addstr(max_y - 1, 0, " " * pad_width)
    # Draw centred status text
    stdscr.addstr(max_y - 1, start_x, status_line)
    stdscr.attroff(curses.A_REVERSE)

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
    
    # Calculate filled width
    filled = int(width * percent)
    empty = width - filled
    
    # Build progress bar: [====>     ] 45%
    bar = "[" + "=" * filled + ">" * (1 if filled < width and filled > 0 else 0) + " " * empty + "]"
    percent_str = f" {int(percent * 100)}%"
    
    # Combine label, bar, and percent
    if label:
        full_text = f"{label} {bar}{percent_str}"
    else:
        full_text = f"{bar}{percent_str}"
    
    # Truncate to fit screen
    max_width = screen_width - col - 1
    if len(full_text) > max_width:
        full_text = full_text[:max_width]
    
    try:
        stdscr.addstr(row, col, full_text[:max_width])
    except curses.error:
        pass  # Ignore if out of bounds


def _draw_tx_screen(stdscr: "curses._CursesWindow", status: str, progress: float = 0.0, progress_label: str = "", countdown: str = "", message: str = "") -> None:
    """
    Draw TX mode screen with progress bars and status.
    """
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    
    try:
        # Title
        title = "CEEFAX STATION - TRANSMIT MODE"
        title_col = max(0, (width - len(title)) // 2)
        stdscr.addstr(1, title_col, title[:width - title_col])
        
        # Status line
        status_text = f"Status: {status}"
        stdscr.addstr(3, 2, status_text[:width - 3])
        
        # Progress bar area
        if progress_label:
            _draw_ascii_progress_bar(stdscr, 5, 2, min(40, width - 15), progress, progress_label)
        
        # Countdown
        if countdown:
            countdown_text = f"Next transmission in: {countdown}"
            stdscr.addstr(7, 2, countdown_text[:width - 3])
        
        # Message
        if message:
            # Wrap message if needed
            msg_lines = []
            words = message.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 <= width - 4:
                    current_line += (" " if current_line else "") + word
                else:
                    if current_line:
                        msg_lines.append(current_line)
                    current_line = word
            if current_line:
                msg_lines.append(current_line)
            
            for i, line in enumerate(msg_lines[:5]):  # Max 5 lines
                if 9 + i < height - 3:
                    stdscr.addstr(9 + i, 2, line[:width - 4])
        
        # Instructions
        if height > 3:
            inst_text = "Press ESC to return to viewer"
            stdscr.addstr(height - 3, 2, inst_text[:width - 3])
    except curses.error:
        pass  # Ignore out of bounds errors
    
    stdscr.refresh()


def _tx_mode_loop(stdscr: "curses._CursesWindow", pages: List[Page]) -> None:
    """
    TX mode: Generate WAV, transmit 3 times, show countdown to next hour.
    """
    import sys
    from datetime import datetime, timedelta
    from ceefax.src.ax25_audio import build_ax25_audio_plan, write_ax25_audio_wav_and_or_stdout
    from ceefax.src.config import load_config
    from ceefax.src.playback import play_wav_file
    from pathlib import Path
    import json
    
    curses.curs_set(0)
    stdscr.nodelay(True)  # Non-blocking for countdown updates
    stdscr.keypad(True)
    
    cfg = load_config()
    
    # Get callsign from config or prompt
    repo_root = Path(__file__).resolve().parent.parent.parent
    config_file = repo_root / "ceefax" / "radio_config.json"
    callsign = None
    
    if config_file.exists():
        try:
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
            callsign = config_data.get("callsign", "").strip().upper()
        except Exception:  # noqa: BLE001
            pass
    
    if not callsign:
        # Prompt for callsign (need to temporarily exit curses)
        curses.endwin()
        try:
            while True:
                try:
                    cs = input("Enter your callsign: ").strip().upper()
                    if cs:
                        callsign = cs
                        break
                    print("Callsign cannot be empty. Try again.")
                except (EOFError, KeyboardInterrupt):
                    return
        finally:
            stdscr.refresh()
    
    src = callsign or cfg.ax25.callsign or "N0CALL"
    loops_in_wav = cfg.ax25.loops_per_hour or 3
    
    # Step 1: Refresh pages first
    _draw_tx_screen(stdscr, "Refreshing pages...", 0.0, "Refreshing")
    stdscr.refresh()
    
    try:
        # Refresh pages before generating
        from ceefax.src.update_all import update_all
        
        # Refresh all pages (this updates weather, news, etc.)
        update_all()
        
        # Reload pages after refresh
        new_pages = load_all_pages(cfg.general.page_dir)
        if new_pages:
            pages[:] = new_pages
        
        # Step 2: Generate WAV file
        _draw_tx_screen(stdscr, "Generating transmission file...", 0.0, "Generating")
        stdscr.refresh()
        
        plan = build_ax25_audio_plan(
            pages=pages,
            loops=max(1, loops_in_wav),
            dest_callsign=cfg.ax25.dest_callsign,
            src_callsign=src,
            max_info_bytes=cfg.ax25.max_info_bytes,
        )
        
        # Simulate progress during generation (actual generation is fast)
        for i in range(10):
            _draw_tx_screen(stdscr, "Generating transmission file...", i / 10.0, "Generating")
            stdscr.refresh()
            time.sleep(0.05)
        
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
        
        _draw_tx_screen(stdscr, "File generated successfully", 1.0, "Generating")
        stdscr.refresh()
        time.sleep(0.5)
        
        # Step 2: Transmit 3 times
        for tx_num in range(1, 4):
            status = f"Transmitting (loop {tx_num}/3)..."
            progress = (tx_num - 1) / 3.0
            _draw_tx_screen(stdscr, status, progress, f"Transmission {tx_num}/3")
            stdscr.refresh()
            
            try:
                # Play the WAV file (blocking call)
                play_wav_file(wav, loops=1)
                
                # Show completion
                progress = tx_num / 3.0
                _draw_tx_screen(stdscr, f"Transmission {tx_num}/3 complete", progress, f"Transmission {tx_num}/3")
                stdscr.refresh()
                time.sleep(0.3)
            except Exception as e:  # noqa: BLE001
                progress = tx_num / 3.0
                _draw_tx_screen(stdscr, f"Transmission {tx_num}/3 failed: {str(e)[:40]}", progress, f"Transmission {tx_num}/3")
                stdscr.refresh()
                time.sleep(2)
        
        # Step 4: Show countdown and website message
        message = "Visit https://ceefaxstation.com to see your station on the map and view reception data"
        
        while True:
            # Check for ESC key
            ch = stdscr.getch()
            if ch == 27:  # ESC key
                break
            
            # Calculate time until next hour
            now = datetime.now()
            next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            remaining = next_hour - now
            total_seconds = int(remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            countdown_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            _draw_tx_screen(
                stdscr,
                "All transmissions complete",
                1.0,
                "Status",
                countdown_str,
                message
            )
            stdscr.refresh()
            time.sleep(1)
            
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
    
    # Show initializing message
    stdscr.clear()
    stdscr.addstr(0, 0, "Initializing receive mode...")
    stdscr.addstr(1, 0, "Auto-detecting soundcard...")
    stdscr.refresh()
    
    # Find direwolf
    dw = _find_direwolf_exe(None)
    
    # Auto-detect device (None = auto-detect)
    device = None
    
    # Get listener callsign from config or use default
    repo_root = Path(__file__).resolve().parent.parent.parent
    config_file = repo_root / "ceefax" / "radio_config.json"
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

    while True:
        if not pages:
            stdscr.clear()
            stdscr.addstr(0, 0, "No pages loaded. Press q to quit.")
            stdscr.refresh()
        else:
            page = pages[idx]
            matrix = matrices[idx]
            _draw_page(stdscr, page, matrix, idx, len(pages))

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break
        if ch in (ord("n"), curses.KEY_RIGHT, curses.KEY_NPAGE):
            if pages:
                idx = (idx + 1) % len(pages)
        elif ch in (ord("p"), curses.KEY_LEFT, curses.KEY_PPAGE):
            if pages:
                idx = (idx - 1) % len(pages)
        elif ch == curses.KEY_F5:
            # Reload pages from disk (F5)
            cfg = load_config()
            new_pages = load_all_pages(cfg.general.page_dir)
            if new_pages:
                pages[:] = new_pages
                matrices[:] = compile_all()
                idx = 0
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

    q: "queue.Queue[tuple[Page, List[str]]]" = queue.Queue()
    stop_event = threading.Event()
    stats_lock = threading.Lock()
    rcfg = _load_radio_config()
    freq = (rcfg.get("frequency") or "").strip() if isinstance(rcfg, dict) else ""
    stats: dict = {
        "schema": 1,
        "listener_callsign": (listener_callsign or "").strip(),
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
                _draw_page(
                    stdscr,
                    pages[idx],
                    matrices[idx],
                    idx,
                    len(pages),
                    callsign_override=listener_callsign,
                )
            else:
                stdscr.clear()
                msg = rx_err["msg"] or f"Waiting for AX.25 pages from WAV: {wav_path}"
                stdscr.addstr(0, 0, msg[: max(stdscr.getmaxyx()[1] - 1, 1)])
                stdscr.addstr(1, 0, "Press q to quit."[: max(stdscr.getmaxyx()[1] - 1, 1)])
                stdscr.refresh()

            ch = stdscr.getch()
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

    q: "queue.Queue[tuple[Page, List[str]]]" = queue.Queue()
    stop_event = threading.Event()
    stats_lock = threading.Lock()
    rcfg = _load_radio_config()
    freq = (rcfg.get("frequency") or "").strip() if isinstance(rcfg, dict) else ""

    # Create a stable log path for the session.
    live_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ceefax_root = Path(__file__).resolve().parent.parent
    log_path = (ceefax_root / "logs_rx" / f"ceefax_ax25_live_{live_ts}.json")

    stats: dict = {
        "schema": 1,
        "listener_callsign": (listener_callsign or "").strip(),
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
                _draw_page(
                    stdscr,
                    pages[idx],
                    matrices[idx],
                    idx,
                    len(pages),
                    callsign_override=listener_callsign,
                )
            else:
                stdscr.clear()
                msg = rx_err["msg"] or "Waiting for AX.25 pages from live audio..."
                stdscr.addstr(0, 0, msg[: max(stdscr.getmaxyx()[1] - 1, 1)])
                stdscr.addstr(1, 0, "Press q to quit."[: max(stdscr.getmaxyx()[1] - 1, 1)])
                stdscr.refresh()

            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
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
        help="Path to direwolf.exe (defaults to bundled tools/direwolf/direwolf.exe or PATH).",
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
            pages = load_all_pages(config.general.page_dir)
            _viewer_loop(stdscr, pages)

    curses.wrapper(runner)


if __name__ == "__main__":
    main()


