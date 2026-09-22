"""HF carousel transport over bundled modem73 (RDM-600S / RDM-300S).

modem73 v2.4 decodes every robust mode at once (CONTROL_PORT.md: "RX
auto-detects the mode"). Only the transmitter sets RDM-600S or RDM-300S.
TX queue drain is `get_status`: channel_state == "idle", ptt_on false, and
tx_frame_count caught up with the frames we submitted. There is no separate
queue-depth command.
"""

from __future__ import annotations

import json
import logging
import shutil
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List
from uuid import UUID, uuid4

from .ax25 import fragment_page_bytes
from .compiler import Page, compile_page_to_frame
from .config import AppConfig
from .kissframe import encode_kiss_frame, iter_kiss_frames, payload_from_kiss_frame

HF_PHY_MTU = 170
BEACON_MAGIC = b"CFXB"
FRAME_SECONDS = {"RDM-600S": 3.6, "RDM-300S": 7.1}
ROBUST_MODE = {"RDM-600S": 6, "RDM-300S": 7}
# modem73 drops a KISS frame once 256 are already queued, and tx_frame_count
# does not move while a frame is on the air. Pace off the published frame
# time instead, and keep only this many frames queued ahead of that clock.
TX_QUEUE_LIMIT = 256
TX_QUEUE_WINDOW = 16

HF_LISTENER_NOTE = (
    "HF uses modem73, which decodes every robust mode at once. "
    "This listener does not choose RDM-600S or RDM-300S. "
    "An FM station still uses Dire Wolf."
)


def uses_hf(config: AppConfig) -> bool:
    return config.radio.band == "hf"


def link_label(config: AppConfig) -> str:
    if uses_hf(config):
        return f"HF {config.hf.mode}"
    return "VHF FM"


def hf_set_config(mode: str) -> dict:
    """One set_config for the whole pass. modem73 has a single global TX mode."""
    if mode not in ROBUST_MODE:
        raise ValueError(f"hf.mode must be RDM-600S or RDM-300S, got {mode!r}")
    return {
        "cmd": "set_config",
        "modem_type": 2,
        "robust_mode": ROBUST_MODE[mode],
        "csma_band": 0,
        "csma_enabled": True,
        # modem73's own fragmentor would reassemble our CFX pieces. Leave them intact.
        "fragmentation_enabled": False,
    }


def estimate_pass_seconds(frame_count: int, mode: str) -> float:
    return max(0, int(frame_count)) * FRAME_SECONDS[mode]


def build_station_beacon(
    *,
    tx_id: str,
    callsign: str,
    frequency: str,
    grid: str,
) -> bytes:
    body = json.dumps(
        {
            "tx_id": tx_id,
            "callsign": (callsign or "").strip().upper(),
            "frequency": (frequency or "").strip(),
            "grid": (grid or "").strip().upper(),
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    frame = BEACON_MAGIC + body
    if len(frame) > HF_PHY_MTU:
        raise ValueError("HF station beacon exceeds 170 bytes")
    return frame


def parse_station_beacon(payload: bytes) -> dict | None:
    if not payload.startswith(BEACON_MAGIC):
        return None
    try:
        data = json.loads(payload[len(BEACON_MAGIC) :].decode("ascii"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("tx_id"):
        return None
    return data


@dataclass(frozen=True)
class HfPassPlan:
    tx_id: str
    mode: str
    src_callsign: str
    payloads: List[bytes]
    page_ids: List[str]
    fragments: int
    loops: int

    @property
    def estimated_seconds(self) -> float:
        return estimate_pass_seconds(len(self.payloads), self.mode)


def build_hf_pass_plan(
    *,
    pages: List[Page],
    loops: int,
    src_callsign: str,
    frequency: str,
    grid: str,
    max_frame_bytes: int,
    mode: str,
    tx_id: str | None = None,
) -> HfPassPlan:
    """
    KISS payloads for one HF pass: one station beacon, then CFX2 fragments.

    max_frame_bytes is the whole fragment including the 27-byte CFX2 header.
    fragment_page_bytes already subtracts that header from the limit.
    """
    if mode not in ROBUST_MODE:
        raise ValueError(f"hf.mode must be RDM-600S or RDM-300S, got {mode!r}")
    if not 1 <= int(max_frame_bytes) <= HF_PHY_MTU:
        raise ValueError(
            f"hf.max_frame_bytes must be 1..{HF_PHY_MTU} "
            "(short robust frames have a 170 byte MTU; do not use 172)"
        )

    tx_uuid = UUID(tx_id) if tx_id else uuid4()
    tx_id_str = str(tx_uuid)
    beacon = build_station_beacon(
        tx_id=tx_id_str,
        callsign=src_callsign,
        frequency=frequency,
        grid=grid,
    )
    payloads: List[bytes] = [beacon]
    page_ids: List[str] = []
    fragments = 0
    loops = max(1, int(loops))

    for _ in range(loops):
        for page in pages:
            page_bytes = compile_page_to_frame(page)
            frags = fragment_page_bytes(
                tx_id_bytes=tx_uuid.bytes,
                page=page.page,
                subpage=page.subpage,
                page_bytes=page_bytes,
                max_info_bytes=int(max_frame_bytes),
            )
            for frag in frags:
                # Measured after chunking, not from the whole page.
                if len(frag.payload) > int(max_frame_bytes):
                    raise AssertionError(
                        f"HF fragment is {len(frag.payload)} bytes; limit is {max_frame_bytes}"
                    )
                payloads.append(frag.payload)
            fragments += len(frags)
            page_ids.append(page.page_id)

    return HfPassPlan(
        tx_id=tx_id_str,
        mode=mode,
        src_callsign=src_callsign,
        payloads=payloads,
        page_ids=page_ids,
        fragments=fragments,
        loops=loops,
    )


def ingest_hf_payload(reassembler, payload: bytes, stats: dict, beacons: dict):
    """
    Feed one KISS payload into the FM reassembler.

    A CFXB beacon records the station for this tx_id and is not a page fragment.
    Returns the reassembler's result, or None for beacons and partials.
    """
    beacon = parse_station_beacon(payload)
    if beacon is not None:
        beacons[str(beacon["tx_id"])] = beacon
        callsign = str(beacon.get("callsign") or "").strip().upper()
        if callsign:
            heard = stats.setdefault("stations_heard", {})
            heard[callsign] = int(heard.get(callsign, 0)) + 1
            if not stats.get("station_callsign"):
                stats["station_callsign"] = callsign
        return None

    from .viewer import _parse_cfx_info

    parsed = _parse_cfx_info(payload)
    if parsed:
        callsign = ""
        tx_id = str(parsed.get("tx_id") or "")
        beacon_for_tx = beacons.get(tx_id) or {}
        callsign = str(beacon_for_tx.get("callsign") or "").strip().upper()
        _note_hf_fragment(stats, parsed, callsign)

    assembled = reassembler.add(payload)
    if assembled and not stats.get("station_callsign"):
        tx_id = str(assembled[0] or "")
        callsign = str((beacons.get(tx_id) or {}).get("callsign") or "").strip().upper()
        if callsign:
            stats["station_callsign"] = callsign
    return assembled


def _note_hf_fragment(stats: dict, parsed: dict, callsign: str) -> None:
    page = parsed["page"]
    subpage = int(parsed["subpage"])
    idx = int(parsed["idx"])
    total = int(parsed["total"])
    tx_id = str(parsed.get("tx_id") or "")
    key = f"{page}.{subpage}" if subpage != 1 else page
    stats["cfx_frames"] = int(stats.get("cfx_frames", 0)) + 1
    if callsign:
        heard = stats.setdefault("stations_heard", {})
        heard[callsign] = int(heard.get(callsign, 0)) + 1
        if not stats.get("station_callsign"):
            stats["station_callsign"] = callsign
    if tx_id:
        seen = stats.setdefault("tx_ids_seen", [])
        if tx_id not in seen:
            seen.append(tx_id)
        if not stats.get("tx_id"):
            stats["tx_id"] = tx_id
    progress = stats.setdefault("page_progress", {}).setdefault(
        key,
        {"page": page, "subpage": subpage, "total": total, "got": []},
    )
    progress["total"] = max(int(progress.get("total", 0)), total)
    got = set(int(item) for item in progress.get("got", []))
    if idx not in got:
        got.add(idx)
        progress["got"] = sorted(got)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("modem73 control connection closed")
        buf.extend(chunk)
    return bytes(buf)


class ControlClient:
    """Length-prefixed JSON control port (4-byte big-endian length + JSON)."""

    def __init__(self, host: str, port: int, timeout_s: float = 5.0) -> None:
        self._sock = socket.create_connection((host, port), timeout=timeout_s)
        self._sock.settimeout(timeout_s)
        self._timeout_s = timeout_s

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def request(self, command: dict, *, timeout_s: float | None = None) -> dict:
        body = json.dumps(command).encode("utf-8")
        self._sock.sendall(struct.pack(">I", len(body)) + body)
        deadline = time.monotonic() + float(timeout_s if timeout_s is not None else self._timeout_s)
        want_status = command.get("cmd") == "get_status"
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            self._sock.settimeout(remaining)
            try:
                message = self._read_message()
            except socket.timeout:
                continue
            if want_status and "channel_state" in message:
                return message
            if not want_status and "ok" in message:
                return message
            # Unsolicited rx_frame / config_changed events have neither.
        raise TimeoutError(f"no reply to {command.get('cmd')}")

    def _read_message(self) -> dict:
        raw_len = _recv_exact(self._sock, 4)
        size = struct.unpack(">I", raw_len)[0]
        if size > 1_000_000:
            raise ValueError(f"modem73 control message is {size} bytes")
        payload = _recv_exact(self._sock, size)
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("modem73 control message was not an object")
        return data

    def get_status(self) -> dict:
        return self.request({"cmd": "get_status"})

    def set_config(self, fields: dict) -> dict:
        return self.request(fields if "cmd" in fields else {"cmd": "set_config", **fields})


class KissClient:
    def __init__(self, host: str, port: int, timeout_s: float = 5.0) -> None:
        self._sock = socket.create_connection((host, port), timeout=timeout_s)
        self._sock.settimeout(timeout_s)
        self._buf = bytearray()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def send_payload(self, payload: bytes) -> None:
        self._sock.sendall(encode_kiss_frame(payload))

    def read_payload(self, timeout_s: float = 0.5) -> bytes | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for frame in iter_kiss_frames(self._buf):
                payload = payload_from_kiss_frame(frame)
                if payload is not None:
                    return payload
            self._sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("modem73 KISS connection closed")
            self._buf.extend(chunk)
        for frame in iter_kiss_frames(self._buf):
            payload = payload_from_kiss_frame(frame)
            if payload is not None:
                return payload
        return None


def tcp_port_open(host: str, port: int, timeout_s: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def modem73_command(exe: str, *, kiss_port: int, control_port: int) -> list[str]:
    return [
        exe,
        "--headless",
        "--port",
        str(int(kiss_port)),
        "--control-port",
        str(int(control_port)),
    ]


def _missing_modem73_message() -> str:
    if sys.platform.startswith("win"):
        return (
            "Bundled modem73.exe was not found under ceefax/tools/modem73. "
            "The Windows installer stages the official modem73-win build there. "
            "An FM station does not need it."
        )
    return (
        "modem73 was not found on PATH. The Ceefax Debian package does not embed it. "
        "Install the official modem73 build for this CPU (amd64, arm64, or armhf) from "
        "https://github.com/RFnexus/modem73/releases . An FM station does not need it."
    )


def find_modem73_exe(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    from .paths import ceefax_root, install_root

    names = ["modem73.exe"] if sys.platform.startswith("win") else ["modem73", "modem73.exe"]
    roots = (
        ceefax_root() / "tools" / "modem73",
        install_root() / "ceefax" / "tools" / "modem73",
        Path(__file__).resolve().parent.parent / "tools" / "modem73",
    )
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return str(candidate)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(_missing_modem73_message())


def wait_until_drained(
    client: ControlClient,
    *,
    min_tx_frames: int,
    timeout_s: float,
    poll_s: float = 0.25,
    idle_hold_s: float | None = None,
) -> dict:
    """
    Block until get_status shows the TX queue has drained.

    Idle plus PTT off, twice in a row, and tx_frame_count at least min_tx_frames.
    The second idle poll avoids closing while a just-queued frame is about to key.
    tx_frame_count stays put while a frame is on the air, so a pass can also
    finish after the channel has been idle for idle_hold_s.
    """
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    stable_count: int | None = None
    stable_hits = 0
    idle_since: float | None = None
    while time.monotonic() < deadline:
        last = client.get_status()
        idle = last.get("channel_state") == "idle" and not bool(last.get("ptt_on"))
        tx_count = int(last.get("tx_frame_count") or 0)
        if idle and tx_count >= int(min_tx_frames):
            idle_since = None
            if stable_count == tx_count:
                stable_hits += 1
                if stable_hits >= 2:
                    return last
            else:
                stable_count = tx_count
                stable_hits = 1
        elif idle and idle_hold_s is not None:
            stable_count = None
            stable_hits = 0
            if idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= idle_hold_s:
                return last
        else:
            stable_count = None
            stable_hits = 0
            idle_since = None
        time.sleep(poll_s)
    raise TimeoutError(f"modem73 TX queue did not drain (last get_status: {last})")


def _wait_for_frame_slot(
    *,
    sent: int,
    started: float,
    window: int,
    per_frame: float,
    poll_s: float,
    stop_check: Callable[[], bool] | None,
) -> bool:
    """
    Keep at most `window` frames ahead of the published frame duration.

    Returns False when stop_check asks to stop queueing. modem73's
    tx_frame_count does not advance during TX, so the clock is the pace.
    """
    if per_frame <= 0 or sent < window:
        return True
    while True:
        if stop_check and stop_check():
            return False
        elapsed = time.monotonic() - started
        if sent < window + int(elapsed / per_frame):
            return True
        time.sleep(poll_s)


class Modem73Session:
    """
    Talk to modem73 on the configured loopback ports.

    If both ports are already open, attach and leave that process alone.
    Otherwise launch the bundled (or PATH) binary headless. A VHF station must
    not construct this.
    """

    def __init__(self, config: AppConfig, *, exe: str | None = None) -> None:
        self.config = config
        self._exe = exe
        self._proc: subprocess.Popen | None = None
        self._log = None
        self._owned = False
        self.control: ControlClient | None = None
        self.kiss: KissClient | None = None

    def open(self) -> None:
        host = self.config.hf.kiss_host
        kiss_port = int(self.config.hf.kiss_port)
        control_port = int(self.config.hf.control_port)
        kiss_up = tcp_port_open(host, kiss_port)
        control_up = tcp_port_open(host, control_port)
        if kiss_up and control_up:
            logging.info("Attaching to modem73 already listening on %s:%s", host, kiss_port)
            self._owned = False
        elif kiss_up or control_up:
            raise RuntimeError(
                f"modem73 ports are half-open on {host} "
                f"(KISS {kiss_port}={kiss_up}, control {control_port}={control_up})"
            )
        else:
            exe = find_modem73_exe(self._exe)
            from .paths import ceefax_root

            log_path = ceefax_root() / "logs_tx" / "modem73.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = open(log_path, "ab")
            command = modem73_command(exe, kiss_port=kiss_port, control_port=control_port)
            logging.info("Starting modem73: %s", " ".join(command))
            self._proc = subprocess.Popen(command, stdout=self._log, stderr=subprocess.STDOUT)
            self._owned = True
            self._wait_until_listening(host, kiss_port, control_port)
        self.control = ControlClient(host, control_port)
        self.kiss = KissClient(host, kiss_port)

    def _wait_until_listening(self, host: str, kiss_port: int, control_port: int) -> None:
        assert self._proc is not None
        for _ in range(50):
            if self._proc.poll() is not None:
                raise RuntimeError(f"modem73 exited immediately with code {self._proc.returncode}")
            if tcp_port_open(host, kiss_port) and tcp_port_open(host, control_port):
                return
            time.sleep(0.1)
        raise TimeoutError("modem73 did not open the KISS and control ports")

    def close(self, *, drain: bool = True) -> None:
        # Drain before dropping a transmit session so the next set_config, or
        # process exit, cannot cut a frame that is still on the air. Receive
        # sessions pass drain=False; they never queued TX frames.
        if drain:
            try:
                if self.control is not None:
                    status = self.control.get_status()
                    wait_until_drained(
                        self.control,
                        min_tx_frames=int(status.get("tx_frame_count") or 0),
                        timeout_s=15,
                    )
            except Exception as exc:  # noqa: BLE001
                logging.warning("modem73 drain before close failed: %s", exc)
        if self.kiss is not None:
            self.kiss.close()
            self.kiss = None
        if self.control is not None:
            self.control.close()
            self.control = None
        if self._owned and self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self) -> "Modem73Session":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def configure_mode(self, mode: str) -> None:
        if self.control is None:
            raise RuntimeError("modem73 session is not open")
        status = self.control.get_status()
        wait_until_drained(
            self.control,
            min_tx_frames=int(status.get("tx_frame_count") or 0),
            timeout_s=30,
        )
        command = hf_set_config(mode)
        result = self.control.set_config(command)
        if result.get("ok") is False:
            raise RuntimeError(f"modem73 rejected set_config: {result}")

    def send_payloads(
        self,
        payloads: Iterable[bytes],
        *,
        mode: str,
        stop_check: Callable[[], bool] | None = None,
        on_frame: Callable[[int, int], None] | None = None,
        window: int = TX_QUEUE_WINDOW,
        poll_s: float = 0.25,
    ) -> int:
        if self.kiss is None or self.control is None:
            raise RuntimeError("modem73 session is not open")
        queued = list(payloads)
        self.configure_mode(mode)
        before = self.control.get_status()
        baseline = int(before.get("tx_frame_count") or 0)
        per_frame = FRAME_SECONDS.get(mode, 3.6)
        room = max(1, min(int(window), TX_QUEUE_LIMIT))
        started = time.monotonic()
        sent = 0
        for payload in queued:
            if stop_check and stop_check():
                break
            if not _wait_for_frame_slot(
                sent=sent,
                started=started,
                window=room,
                per_frame=per_frame,
                poll_s=poll_s,
                stop_check=stop_check,
            ):
                break
            self.kiss.send_payload(payload)
            sent += 1
            if on_frame:
                on_frame(sent, len(queued))
        timeout_s = estimate_pass_seconds(max(sent, 1), mode) * 2 + 30
        wait_until_drained(
            self.control,
            min_tx_frames=baseline + sent,
            timeout_s=max(15.0, timeout_s),
            poll_s=poll_s,
            idle_hold_s=max(6.0, per_frame),
        )
        return sent


def run_hf_pass(
    config: AppConfig,
    pages: List[Page],
    *,
    callsign: str,
    loops: int | None = None,
    stop_check: Callable[[], bool] | None = None,
    on_frame: Callable[[int, int], None] | None = None,
    session_factory: Callable[[], Modem73Session] | None = None,
) -> HfPassPlan:
    """Stream one HF carousel to modem73. Does not build or play a WAV."""
    from .ax25_audio import finalize_hf_tx_report, write_hf_tx_report

    radio = {}
    try:
        from .ax25_audio import _load_radio_config

        loaded = _load_radio_config()
        if isinstance(loaded, dict):
            radio = loaded
    except Exception:  # noqa: BLE001
        radio = {}
    frequency = str(radio.get("frequency") or "")
    grid = str(radio.get("grid") or "")
    loop_count = config.hf.loops_per_hour if loops is None else int(loops)
    plan = build_hf_pass_plan(
        pages=pages,
        loops=loop_count,
        src_callsign=callsign,
        frequency=frequency,
        grid=grid,
        max_frame_bytes=config.hf.max_frame_bytes,
        mode=config.hf.mode,
    )
    minutes = plan.estimated_seconds / 60.0
    logging.info(
        "HF %s pass: %d KISS frames (%d page fragments + beacon), about %.1f min",
        plan.mode,
        len(plan.payloads),
        plan.fragments,
        minutes,
    )
    write_hf_tx_report(plan=plan, frequency=frequency, grid=grid, dest_callsign=config.ax25.dest_callsign)
    factory = session_factory or (lambda: Modem73Session(config))
    session = factory()
    # The default factory owns the process. A test double is already connected
    # and is left alone so unit tests never launch modem73.
    manage_session = session_factory is None
    try:
        if manage_session:
            session.open()
        session.send_payloads(
            plan.payloads,
            mode=plan.mode,
            stop_check=stop_check,
            on_frame=on_frame,
        )
    finally:
        finalize_hf_tx_report(plan.tx_id)
        if manage_session:
            session.close()
    return plan


def receive_hf(
    config: AppConfig,
    *,
    out_q,
    stop_event,
    stats: dict,
    stats_lock,
    log_path,
    log_every_s: float = 2.0,
) -> None:
    """Read modem73 KISS and reassemble with the FM fragment reassembler."""
    from .viewer import (
        _Ax25FragmentReassembler,
        _compiled_bytes_to_matrix_and_page,
        _update_rx_log_summary,
        _write_json,
    )

    reassembler = _Ax25FragmentReassembler()
    beacons: dict = {}
    last_log = time.monotonic()
    session = Modem73Session(config)
    session.open()
    try:
        assert session.kiss is not None
        assert session.control is not None
        # Leave the TX mode alone. Only stop modem73 from gluing our CFX
        # fragments back together. Robust decode stays on every mode.
        try:
            session.control.set_config({"cmd": "set_config", "fragmentation_enabled": False})
        except (OSError, TimeoutError, ValueError) as exc:
            logging.warning("Could not disable modem73 fragmentation: %s", exc)
        while not stop_event.is_set():
            try:
                payload = session.kiss.read_payload(0.5)
            except ConnectionError as exc:
                logging.error("HF KISS closed: %s", exc)
                break
            if payload is None:
                continue
            with stats_lock:
                assembled = ingest_hf_payload(reassembler, payload, stats, beacons)
            if not assembled:
                if log_path and (time.monotonic() - last_log) >= log_every_s:
                    with stats_lock:
                        stats["updated_at"] = datetime.now().isoformat()
                        _update_rx_log_summary(stats)
                        _write_json(log_path, stats)
                    last_log = time.monotonic()
                continue
            tx_id, page, subpage, compiled = assembled
            page_obj, matrix = _compiled_bytes_to_matrix_and_page(page, subpage, compiled)
            out_q.put((page_obj, matrix))
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
                        "frequency": stats.get("frequency"),
                    }
                _update_rx_log_summary(stats)
                if log_path:
                    _write_json(log_path, stats)
            last_log = time.monotonic()
    finally:
        session.close(drain=False)
