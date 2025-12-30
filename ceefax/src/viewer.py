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

    # Controls bar one line above bottom (replaces Fastext)
    controls_y = max_y - 2
    if controls_y > offset_y + PAGE_HEIGHT:
        # Center the control labels instead of left-aligning.
        if curses.has_colors():
            labels = [
                (" r: RX ", curses.color_pair(3) | curses.A_BOLD),      # RED
                (" t: TX ", curses.color_pair(4) | curses.A_BOLD),      # GREEN
                (" F5: Reload ", curses.color_pair(5) | curses.A_BOLD), # YELLOW
                (" ESC: Exit ", curses.color_pair(6) | curses.A_BOLD),  # BLUE
            ]
            total_len = sum(len(text) for text, _ in labels)
            x = max((max_x - 1 - total_len) // 2, 0)
            for text, attr in labels:
                if x >= max_x - 1:
                    break
                stdscr.addstr(controls_y, x, text[: max_x - 1 - x], attr)
                x += len(text)
        else:
            line = "r: RX  t: TX  F5: Reload  ESC: Exit"
            x = max((max_x - 1 - len(line)) // 2, 0)
            stdscr.addstr(controls_y, x, line[: max_x - 1 - x])

    # Status line at bottom, centred horizontally to match header
    status = f"Page {page.page_id}  ({index + 1}/{total})  n/p: next/prev  q: quit"
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


def _draw_tx_screen(stdscr: "curses._CursesWindow", status: str, progress: float = 0.0, progress_label: str = "", countdown: str = "", message: str = "", show_logo: bool = False) -> None:
    """
    Draw TX mode screen styled like a Ceefax page (centered, with header bar).
    
    Args:
        show_logo: If True, display TX logo when transmitting
    """
    stdscr.clear()
    max_y, max_x = stdscr.getmaxyx()
    
    # Require at least PAGE_WIDTH x PAGE_HEIGHT area
    if max_y < PAGE_HEIGHT or max_x < PAGE_WIDTH:
        msg = f"Terminal too small. Need at least {PAGE_WIDTH}x{PAGE_HEIGHT}."
        stdscr.addstr(0, 0, msg[: max_x - 1])
        stdscr.refresh()
        return
    
    # Center the frame (same as regular pages)
    offset_y = max((max_y - PAGE_HEIGHT) // 2, 0)
    offset_x = max((max_x - PAGE_WIDTH) // 2, 0)
    
    # Build Ceefax-style header line
    now = datetime.now()
    clock = now.strftime("%H:%M %d %b").upper()
    page_num = "TX "
    title = "TRANSMIT MODE"
    base_header = f"CEEFAX {page_num} {title}"
    header_text = base_header[:PAGE_WIDTH].ljust(PAGE_WIDTH)
    
    # Colors (same as regular pages)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_YELLOW, curses.COLOR_BLUE)   # header
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # body
        header_attr = curses.color_pair(1) | curses.A_BOLD
        body_attr = curses.color_pair(2)
    else:
        header_attr = curses.A_BOLD
        body_attr = curses.A_NORMAL
    
    # Header (row 0) - yellow on blue
    stdscr.addstr(offset_y, offset_x, header_text[:PAGE_WIDTH], header_attr)
    
    # Clock at top-right
    clock_x = offset_x + max(PAGE_WIDTH - len(clock) - 1, 0)
    stdscr.addstr(offset_y, clock_x, clock, header_attr)
    
    # Get callsign for header if available
    callsign = ""
    try:
        from pathlib import Path
        import json
        root = Path(__file__).resolve().parent.parent
        config_file = root / "radio_config.json"
        if config_file.exists():
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
            callsign = config_data.get("callsign", "").strip()
    except Exception:  # noqa: BLE001
        pass
    
    if callsign:
        callsign_x = clock_x - len(callsign) - 2
        if callsign_x >= offset_x:
            stdscr.addstr(offset_y, callsign_x, callsign, header_attr)
            stdscr.addstr(offset_y, callsign_x + len(callsign), "  ", header_attr)
    
    # Content area (inside a border like page 000)
    border_top = offset_y + 1
    border_bottom = offset_y + PAGE_HEIGHT - 1
    inner_x = offset_x + 1
    inner_width = max(PAGE_WIDTH - 2, 1)
    
    # Draw border
    border_attr = body_attr | curses.A_BOLD
    top_line = ("+" + ("-" * (PAGE_WIDTH - 2)) + "+")[:PAGE_WIDTH]
    stdscr.addstr(border_top, offset_x, top_line, border_attr)
    stdscr.addstr(border_bottom, offset_x, top_line, border_attr)
    for row in range(border_top + 1, border_bottom):
        stdscr.addstr(row, offset_x, "|", border_attr)
        stdscr.addstr(row, offset_x + PAGE_WIDTH - 1, "|", border_attr)
    
    # Content lines (centered like page 000)
    current_row = border_top + 1
    row = current_row
    
    # Add TX logo if transmitting
    if show_logo:
        tx_logo = [
            "░▀█▀░█░█",
            "░░█░░▄▀▄",
            "░░▀░░▀░▀",
        ]
        row += 2
        for logo_line in tx_logo:
            if row >= border_bottom - 8:
                break
            logo_centered = logo_line.center(inner_width)
            stdscr.addstr(row, inner_x, logo_centered[:inner_width], body_attr | curses.A_BOLD)
            row += 1
        row += 2
    
    # Add status
    if status:
        row += 1
        status_text = status.upper().center(inner_width)
        stdscr.addstr(row, inner_x, status_text[:inner_width], body_attr | curses.A_BOLD)
        row += 2
    
    # Add progress bar (centered, ensure it fits within inner_width)
    if progress_label:
        row += 1
        # Calculate the full progress bar text to determine actual width
        # Progress bar format: "Label [====>     ] XX%"
        label_len = len(progress_label)
        # Try different bar widths to find one that fits
        bar_width = min(40, inner_width - label_len - 10)  # Reserve space for label + brackets + % + spacing
        bar_width = max(10, bar_width)  # Minimum bar width
        
        # Build a sample to get exact length
        sample_bar = "[" + "=" * bar_width + "]"
        sample_text = f"{progress_label} {sample_bar} 100%"
        
        # If it's too long, reduce bar width
        while len(sample_text) > inner_width and bar_width > 10:
            bar_width -= 1
            sample_bar = "[" + "=" * bar_width + "]"
            sample_text = f"{progress_label} {sample_bar} 100%"
        
        # Center the entire progress bar text within inner_width
        full_text_len = len(sample_text)
        bar_x = inner_x + (inner_width - full_text_len) // 2
        # Ensure bar_x doesn't go outside inner area
        bar_x = max(inner_x, min(bar_x, inner_x + inner_width - full_text_len))
        _draw_ascii_progress_bar(stdscr, row, bar_x, bar_width, progress, progress_label)
        row += 2
    
    # Add countdown if present
    if countdown:
        countdown_text = f"NEXT TRANSMISSION IN: {countdown}"
        countdown_centered = countdown_text.center(inner_width)
        stdscr.addstr(row, inner_x, countdown_centered[:inner_width], body_attr | curses.A_BOLD)
        row += 2
    
    # Add message if present (word-wrapped and centered)
    if message:
        row += 1
        # Word wrap message to fit inner width
        words = message.split()
        msg_lines = []
        current_line = ""
        for word in words:
            if not current_line:
                current_line = word
            elif len(current_line) + 1 + len(word) <= inner_width:
                current_line += " " + word
            else:
                msg_lines.append(current_line)
                current_line = word
        if current_line:
            msg_lines.append(current_line)
        
        for msg_line in msg_lines:
            if row >= border_bottom - 3:
                break
            msg_centered = msg_line.center(inner_width)
            stdscr.addstr(row, inner_x, msg_centered[:inner_width], body_attr | curses.A_BOLD)
            row += 1
        row += 1
    
    # Add ESC instruction at bottom
    if row < border_bottom - 1:
        esc_text = "PRESS ESC TO RETURN TO VIEWER"
        esc_centered = esc_text.center(inner_width)
        stdscr.addstr(border_bottom - 2, inner_x, esc_centered[:inner_width], body_attr | curses.A_BOLD)
    
    # Controls bar (same as regular pages)
    controls_y = max_y - 2
    if controls_y > offset_y + PAGE_HEIGHT:
        if curses.has_colors():
            labels = [
                (" r: RX ", curses.color_pair(3) | curses.A_BOLD),      # RED
                (" t: TX ", curses.color_pair(4) | curses.A_BOLD),      # GREEN
                (" F5: Reload ", curses.color_pair(5) | curses.A_BOLD), # YELLOW
                (" ESC: Exit ", curses.color_pair(6) | curses.A_BOLD),  # BLUE
            ]
            total_len = sum(len(text) for text, _ in labels)
            x = max((max_x - 1 - total_len) // 2, 0)
            for text, attr in labels:
                if x >= max_x - 1:
                    break
                stdscr.addstr(controls_y, x, text[: max_x - 1 - x], attr)
                x += len(text)
        else:
            line = "r: RX  t: TX  F5: Reload  ESC: Exit"
            x = max((max_x - 1 - len(line)) // 2, 0)
            stdscr.addstr(controls_y, x, line[: max_x - 1 - x])
    
    # Status line at bottom (same as regular pages)
    status_line_text = "TRANSMIT MODE  Press ESC to return"
    status_line = status_line_text[: max_x - 1]
    pad_width = max_x - 1
    start_x = max((pad_width - len(status_line)) // 2, 0)
    
    stdscr.attron(curses.A_REVERSE)
    stdscr.addstr(max_y - 1, 0, " " * pad_width)
    stdscr.addstr(max_y - 1, start_x, status_line)
    stdscr.attroff(curses.A_REVERSE)
    
    stdscr.refresh()


def _draw_rx_screen(stdscr: "curses._CursesWindow", status: str = "", message: str = "") -> None:
    """
    Draw RX mode screen styled like a Ceefax page (centered, with header bar and RX logo).
    """
    stdscr.clear()
    max_y, max_x = stdscr.getmaxyx()
    
    # Require at least PAGE_WIDTH x PAGE_HEIGHT area
    if max_y < PAGE_HEIGHT or max_x < PAGE_WIDTH:
        msg = f"Terminal too small. Need at least {PAGE_WIDTH}x{PAGE_HEIGHT}."
        stdscr.addstr(0, 0, msg[: max_x - 1])
        stdscr.refresh()
        return
    
    # Center the frame (same as regular pages)
    offset_y = max((max_y - PAGE_HEIGHT) // 2, 0)
    offset_x = max((max_x - PAGE_WIDTH) // 2, 0)
    
    # Build Ceefax-style header line
    now = datetime.now()
    clock = now.strftime("%H:%M %d %b").upper()
    page_num = "RX "
    title = "RECEIVE MODE"
    base_header = f"CEEFAX {page_num} {title}"
    header_text = base_header[:PAGE_WIDTH].ljust(PAGE_WIDTH)
    
    # Colors (same as regular pages)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_YELLOW, curses.COLOR_BLUE)   # header
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # body
        header_attr = curses.color_pair(1) | curses.A_BOLD
        body_attr = curses.color_pair(2)
    else:
        header_attr = curses.A_BOLD
        body_attr = curses.A_NORMAL
    
    # Header (row 0) - yellow on blue
    stdscr.addstr(offset_y, offset_x, header_text[:PAGE_WIDTH], header_attr)
    
    # Clock at top-right
    clock_x = offset_x + max(PAGE_WIDTH - len(clock) - 1, 0)
    stdscr.addstr(offset_y, clock_x, clock, header_attr)
    
    # Get callsign for header if available
    callsign = ""
    try:
        from pathlib import Path
        import json
        root = Path(__file__).resolve().parent.parent
        config_file = root / "radio_config.json"
        if config_file.exists():
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
            callsign = config_data.get("callsign", "").strip()
    except Exception:  # noqa: BLE001
        pass
    
    if callsign:
        callsign_x = clock_x - len(callsign) - 2
        if callsign_x >= offset_x:
            stdscr.addstr(offset_y, callsign_x, callsign, header_attr)
            stdscr.addstr(offset_y, callsign_x + len(callsign), "  ", header_attr)
    
    # Content area (inside a border like page 000)
    border_top = offset_y + 1
    border_bottom = offset_y + PAGE_HEIGHT - 1
    inner_x = offset_x + 1
    inner_width = max(PAGE_WIDTH - 2, 1)
    
    # Draw border
    border_attr = body_attr | curses.A_BOLD
    top_line = ("+" + ("-" * (PAGE_WIDTH - 2)) + "+")[:PAGE_WIDTH]
    stdscr.addstr(border_top, offset_x, top_line, border_attr)
    stdscr.addstr(border_bottom, offset_x, top_line, border_attr)
    for row in range(border_top + 1, border_bottom):
        stdscr.addstr(row, offset_x, "|", border_attr)
        stdscr.addstr(row, offset_x + PAGE_WIDTH - 1, "|", border_attr)
    
    # Content lines (centered like page 000)
    row = border_top + 1
    
    # Add RX logo
    rx_logo = [
        "░█▀▄░█░█",
        "░█▀▄░▄▀▄",
        "░▀░▀░▀░▀",
    ]
    row += 2
    for logo_line in rx_logo:
        if row >= border_bottom - 8:
            break
        logo_centered = logo_line.center(inner_width)
        stdscr.addstr(row, inner_x, logo_centered[:inner_width], body_attr | curses.A_BOLD)
        row += 1
    row += 2
    
    # Add status if present
    if status:
        status_text = status.upper().center(inner_width)
        stdscr.addstr(row, inner_x, status_text[:inner_width], body_attr | curses.A_BOLD)
        row += 2
    
    # Add message if present (word-wrapped and centered)
    if message:
        words = message.split()
        msg_lines = []
        current_line = ""
        for word in words:
            if not current_line:
                current_line = word
            elif len(current_line) + 1 + len(word) <= inner_width:
                current_line += " " + word
            else:
                msg_lines.append(current_line)
                current_line = word
        if current_line:
            msg_lines.append(current_line)
        
        for msg_line in msg_lines:
            if row >= border_bottom - 3:
                break
            msg_centered = msg_line.center(inner_width)
            stdscr.addstr(row, inner_x, msg_centered[:inner_width], body_attr | curses.A_BOLD)
            row += 1
        row += 1
    
    # Add ESC instruction at bottom
    if row < border_bottom - 1:
        esc_text = "PRESS ESC TO RETURN TO VIEWER"
        esc_centered = esc_text.center(inner_width)
        stdscr.addstr(border_bottom - 2, inner_x, esc_centered[:inner_width], body_attr | curses.A_BOLD)
    
    # Controls bar (same as regular pages)
    controls_y = max_y - 2
    if controls_y > offset_y + PAGE_HEIGHT:
        if curses.has_colors():
            labels = [
                (" r: RX ", curses.color_pair(3) | curses.A_BOLD),      # RED
                (" t: TX ", curses.color_pair(4) | curses.A_BOLD),      # GREEN
                (" F5: Reload ", curses.color_pair(5) | curses.A_BOLD), # YELLOW
                (" ESC: Exit ", curses.color_pair(6) | curses.A_BOLD),  # BLUE
            ]
            total_len = sum(len(text) for text, _ in labels)
            x = max((max_x - 1 - total_len) // 2, 0)
            for text, attr in labels:
                if x >= max_x - 1:
                    break
                stdscr.addstr(controls_y, x, text[: max_x - 1 - x], attr)
                x += len(text)
        else:
            line = "r: RX  t: TX  F5: Reload  ESC: Exit"
            x = max((max_x - 1 - len(line)) // 2, 0)
            stdscr.addstr(controls_y, x, line[: max_x - 1 - x])
    
    # Status line at bottom (same as regular pages)
    status_line_text = "RECEIVE MODE  Press ESC to return"
    status_line = status_line_text[: max_x - 1]
    pad_width = max_x - 1
    start_x = max((pad_width - len(status_line)) // 2, 0)
    
    stdscr.attron(curses.A_REVERSE)
    stdscr.addstr(max_y - 1, 0, " " * pad_width)
    stdscr.addstr(max_y - 1, start_x, status_line)
    stdscr.attroff(curses.A_REVERSE)
    
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
    # Note: We generate WAV with loops=1, then play it 3 times in the transmission loop
    # This avoids double-looping (WAV already containing 3 loops, then playing 3 times = 9 loops)
    loops_in_wav = 1  # Generate single loop, we'll play it multiple times
    
    # Step 1: Refresh pages first (run in background so ESC is responsive)
    _draw_tx_screen(stdscr, "Refreshing pages...", 0.0, "Refreshing")
    stdscr.refresh()

    try:
        from ceefax.src.update_all import prime_user_settings, update_all

        # Prevent update_all() from prompting for input while curses owns the terminal.
        prime_user_settings(callsign=src, frequency="", auto_location=True)

        refresh_done = threading.Event()
        refresh_err: dict = {"err": None}

        def _refresh_worker() -> None:
            try:
                update_all()
            except Exception as e:  # noqa: BLE001
                refresh_err["err"] = e
            finally:
                refresh_done.set()

        t_refresh = threading.Thread(target=_refresh_worker, daemon=True)
        t_refresh.start()

        # Indeterminate progress animation while refresh runs
        tick = 0
        while not refresh_done.is_set():
            ch = stdscr.getch()
            if ch == 27:  # ESC
                _draw_tx_screen(
                    stdscr,
                    "Refresh cancelled (finishing current tasks in background)...",
                    0.0,
                    "Refreshing",
                    "",
                    "Returning to viewer. You can retry TX after refresh completes.",
                )
                time.sleep(1.0)
                return

            # animate bar 0..100% repeating
            progress = (tick % 100) / 100.0
            _draw_tx_screen(stdscr, "Refreshing pages...", progress, "Refreshing")
            stdscr.refresh()
            tick += 3
            time.sleep(0.1)

        if refresh_err["err"] is not None:
            raise refresh_err["err"]
        
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
            ch = stdscr.getch()
            if ch == 27:  # ESC
                _draw_tx_screen(
                    stdscr,
                    "Generation cancelled",
                    0.0,
                    "Generating",
                    "",
                    "Returning to viewer.",
                )
                stdscr.refresh()
                time.sleep(1.0)
                return  # Exit TX mode immediately
            
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
        
        # Step 1.5: Pre-transmission confirmation with VOX and frequency info
        # Get frequency from config
        frequency_info = ""
        data_frequency = ""
        if config_file.exists():
            try:
                config_data = json.loads(config_file.read_text(encoding="utf-8"))
                freq_str = config_data.get("frequency", "")
                if freq_str:
                    frequency_info = freq_str
                    # Extract band and suggest typical data frequency.
                    # Supported formats include:
                    # - "144.800 MHz (2m)" (preferred)
                    # - "2m (...)" (legacy)
                    # - "144.800 MHz"
                    import re
                    # Try to extract band name (2m, 70cm, etc.)
                    band_match = re.search(r'(\d+[mc]m?|6m|10m|12m|15m|17m|20m|30m|40m|80m)', freq_str, re.I)
                    if band_match:
                        band = band_match.group(1).lower()
                        # Map bands to typical packet/data frequencies (UK amateur radio)
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
                        # Try to extract MHz value for custom frequencies
                        mhz_match = re.search(r'(\d+\.?\d*)\s*MHz', freq_str, re.I)
                        if mhz_match:
                            data_frequency = f"{mhz_match.group(1)} MHz"
            except Exception:  # noqa: BLE001
                pass
        
        # Show pre-transmission confirmation screen
        stdscr.nodelay(False)  # Blocking for Enter key
        confirmation_shown = False
        while not confirmation_shown:
            stdscr.clear()
            max_y, max_x = stdscr.getmaxyx()
            
            # Center the frame
            offset_y = max((max_y - PAGE_HEIGHT) // 2, 0)
            offset_x = max((max_x - PAGE_WIDTH) // 2, 0)
            
            # Header
            now = datetime.now()
            clock = now.strftime("%H:%M %d %b").upper()
            header_text = f"CEEFAX TX  TRANSMIT MODE".ljust(PAGE_WIDTH)
            
            if curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_YELLOW, curses.COLOR_BLUE)
                curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
                header_attr = curses.color_pair(1) | curses.A_BOLD
                body_attr = curses.color_pair(2)
            else:
                header_attr = curses.A_BOLD
                body_attr = curses.A_NORMAL
            
            stdscr.addstr(offset_y, offset_x, header_text[:PAGE_WIDTH], header_attr)
            clock_x = offset_x + max(PAGE_WIDTH - len(clock) - 1, 0)
            stdscr.addstr(offset_y, clock_x, clock, header_attr)
            
            if callsign:
                callsign_x = clock_x - len(callsign) - 2
                if callsign_x >= offset_x:
                    stdscr.addstr(offset_y, callsign_x, callsign, header_attr)
            
            # Border
            border_top = offset_y + 1
            border_bottom = offset_y + PAGE_HEIGHT - 1
            inner_x = offset_x + 1
            inner_width = max(PAGE_WIDTH - 2, 1)
            border_attr = body_attr | curses.A_BOLD
            top_line = ("+" + ("-" * (PAGE_WIDTH - 2)) + "+")[:PAGE_WIDTH]
            stdscr.addstr(border_top, offset_x, top_line, border_attr)
            stdscr.addstr(border_bottom, offset_x, top_line, border_attr)
            for row in range(border_top + 1, border_bottom):
                stdscr.addstr(row, offset_x, "|", border_attr)
                stdscr.addstr(row, offset_x + PAGE_WIDTH - 1, "|", border_attr)
            
            # Content - VOX instructions and frequency info
            row = border_top + 1
            row += 1
            
            # TX logo
            tx_logo = [
                "░▀█▀░█░█",
                "░░█░░▄▀▄",
                "░░▀░░▀░▀",
            ]
            for logo_line in tx_logo:
                if row >= border_bottom - 10:
                    break
                logo_centered = logo_line.center(inner_width)
                stdscr.addstr(row, inner_x, logo_centered[:inner_width], body_attr | curses.A_BOLD)
                row += 1
            row += 2
            
            # VOX instructions
            vox_lines = [
                "RADIO CONFIGURATION REQUIRED",
                "",
                "Ensure your radio is configured:",
                "",
                "1. VOX (Voice Operated Transmit) enabled",
                "2. Set to frequency band:",
            ]
            for line in vox_lines:
                if row >= border_bottom - 5:
                    break
                line_centered = line.center(inner_width)
                stdscr.addstr(row, inner_x, line_centered[:inner_width], body_attr | curses.A_BOLD)
                row += 1
            
            # Show frequency band
            if frequency_info:
                freq_display = frequency_info.center(inner_width)
                stdscr.addstr(row, inner_x, freq_display[:inner_width], body_attr | curses.A_BOLD)
                row += 1
            else:
                no_freq = "Frequency not configured".center(inner_width)
                stdscr.addstr(row, inner_x, no_freq[:inner_width], body_attr | curses.A_BOLD)
                row += 1
            
            row += 1
            
            # Show recommended data frequency
            if data_frequency:
                data_freq_line = f"3. Recommended data frequency: {data_frequency}".center(inner_width)
                stdscr.addstr(row, inner_x, data_freq_line[:inner_width], body_attr | curses.A_BOLD)
                row += 1
            
            row += 1
            confirm_line = "Press ENTER to start transmission".center(inner_width)
            stdscr.addstr(border_bottom - 2, inner_x, confirm_line[:inner_width], body_attr | curses.A_BOLD)
            
            # Controls and status
            controls_y = max_y - 2
            if controls_y > offset_y + PAGE_HEIGHT:
                if curses.has_colors():
                    labels = [
                        (" r: RX ", curses.color_pair(3) | curses.A_BOLD),
                        (" t: TX ", curses.color_pair(4) | curses.A_BOLD),
                        (" F5: Reload ", curses.color_pair(5) | curses.A_BOLD),
                        (" ESC: Exit ", curses.color_pair(6) | curses.A_BOLD),
                    ]
                    total_len = sum(len(text) for text, _ in labels)
                    x = max((max_x - 1 - total_len) // 2, 0)
                    for text, attr in labels:
                        if x >= max_x - 1:
                            break
                        stdscr.addstr(controls_y, x, text[: max_x - 1 - x], attr)
                        x += len(text)
            
            status_line_text = "TRANSMIT MODE  Press ENTER to continue, ESC to cancel"
            status_line = status_line_text[: max_x - 1]
            pad_width = max_x - 1
            start_x = max((pad_width - len(status_line)) // 2, 0)
            stdscr.attron(curses.A_REVERSE)
            stdscr.addstr(max_y - 1, 0, " " * pad_width)
            stdscr.addstr(max_y - 1, start_x, status_line)
            stdscr.attroff(curses.A_REVERSE)
            
            stdscr.refresh()
            
            # Wait for Enter or ESC
            ch = stdscr.getch()
            if ch == 10 or ch == 13:  # Enter key
                confirmation_shown = True
            elif ch == 27:  # ESC
                return  # Exit TX mode
        
        stdscr.nodelay(True)  # Back to non-blocking for transmission
        
        # Step 2: Transmit 3 times
        for tx_num in range(1, 4):
            status = f"Transmitting (loop {tx_num}/3)..."
            progress = (tx_num - 1) / 3.0
            _draw_tx_screen(stdscr, status, progress, f"Transmission {tx_num}/3", show_logo=True)
            stdscr.refresh()
            
            # Run playback in background thread so we can check for ESC
            playback_done = threading.Event()
            playback_stop = threading.Event()
            playback_err: dict = {"err": None}
            playback_proc = {"proc": None}  # Store subprocess for termination
            
            def _playback_worker() -> None:
                try:
                    import subprocess
                    import sys
                    if sys.platform.startswith("win"):
                        # On Windows, use PowerShell subprocess so we can terminate it
                        try:
                            # Escape the path for PowerShell
                            wav_escaped = wav.replace("'", "''")
                            proc = subprocess.Popen(
                                ["powershell", "-Command", f"(New-Object Media.SoundPlayer '{wav_escaped}').PlaySync()"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                            )
                            playback_proc["proc"] = proc
                            proc.wait()
                        except Exception as e:  # noqa: BLE001
                            # Fallback to winsound if PowerShell fails
                            import winsound
                            # Use async mode and poll for stop
                            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
                            # Poll until stop is requested or sound finishes (rough estimate)
                            import time
                            import os
                            # Estimate duration from file size (rough: 1 second per ~96KB for 16-bit 48kHz mono)
                            try:
                                file_size = os.path.getsize(wav)
                                estimated_duration = file_size / (48000 * 2)  # 48kHz, 16-bit (2 bytes)
                            except Exception:
                                estimated_duration = 30  # Default fallback
                            
                            elapsed = 0.0
                            while elapsed < estimated_duration and not playback_stop.is_set():
                                time.sleep(0.1)
                                elapsed += 0.1
                    else:
                        # For non-Windows, use the original play_wav_file
                        play_wav_file(wav, loops=1)
                except Exception as e:  # noqa: BLE001
                    playback_err["err"] = e
                finally:
                    playback_done.set()
            
            t_playback = threading.Thread(target=_playback_worker, daemon=True)
            t_playback.start()
            
            # Poll for ESC while playback runs
            while not playback_done.is_set():
                ch = stdscr.getch()
                if ch == 27:  # ESC
                    # Stop playback
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
                        progress,
                        f"Transmission {tx_num}/3",
                        "",
                        "Returning to viewer.",
                    )
                    stdscr.refresh()
                    time.sleep(1.0)
                    return  # Exit TX mode immediately
                time.sleep(0.1)  # Small delay to avoid busy-waiting
            
            # Check if playback had an error
            if playback_err["err"] is not None:
                progress = tx_num / 3.0
                _draw_tx_screen(stdscr, f"Transmission {tx_num}/3 failed: {str(playback_err['err'])[:40]}", progress, f"Transmission {tx_num}/3")
                stdscr.refresh()
                time.sleep(2)
            else:
                # Show completion
                progress = tx_num / 3.0
                _draw_tx_screen(stdscr, f"Transmission {tx_num}/3 complete", progress, f"Transmission {tx_num}/3", show_logo=True)
                stdscr.refresh()
                time.sleep(0.3)
        
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
    
    # Show initializing message with RX logo
    _draw_rx_screen(stdscr, "Initializing receive mode...", "Auto-detecting soundcard...")
    
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
                _draw_page(
                    stdscr,
                    pages[idx],
                    matrices[idx],
                    idx,
                    len(pages),
                    callsign_override=listener_callsign,
                )
            else:
                # Show RX screen with waiting message
                msg = rx_err["msg"] or f"Waiting for AX.25 pages from WAV: {Path(wav_path).name}"
                _draw_rx_screen(stdscr, "Waiting for pages...", msg)

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
    grid = (rcfg.get("grid") or "").strip().upper() if isinstance(rcfg, dict) else ""

    # Create a stable log path for the session.
    live_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ceefax_root = Path(__file__).resolve().parent.parent
    log_path = (ceefax_root / "logs_rx" / f"ceefax_ax25_live_{live_ts}.json")

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
                _draw_page(
                    stdscr,
                    pages[idx],
                    matrices[idx],
                    idx,
                    len(pages),
                    callsign_override=listener_callsign,
                )
            else:
                # Show RX screen with waiting message
                msg = rx_err["msg"] or "Waiting for AX.25 pages from live audio..."
                _draw_rx_screen(stdscr, "Waiting for pages...", msg)

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


