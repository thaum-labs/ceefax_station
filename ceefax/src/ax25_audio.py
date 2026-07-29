from __future__ import annotations

import os
import sys
import json
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional
from uuid import UUID, uuid4

from .afsk import Afsk1200Modulator
from .ax25 import bit_stuff, build_ui_frame, bytes_to_bits_lsb, flag_bits
from .compiler import Page, compile_page_to_frame


@dataclass(frozen=True)
class Ax25AudioPlan:
    """
    Fully expanded plan of what to transmit for one cycle.
    """

    ui_frames: List[bytes]
    pages: int
    fragments: int
    loops: int
    tx_id: str
    src_callsign: str
    dest_callsign: str
    page_ids: List[str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tx_log_dir() -> Path:
    # Store TX logs under ceefax/logs_tx/
    from .paths import ceefax_root

    return ceefax_root() / "logs_tx"


def _tx_log_path_for_wav(wav_path: str | Path) -> Path:
    p = Path(wav_path)
    out = _tx_log_dir()
    out.mkdir(parents=True, exist_ok=True)
    return out / f"{p.stem}.json"


def _load_radio_config() -> dict:
    """
    Best-effort read of ceefax/radio_config.json so we can include frequency/grid
    metadata in TX logs for the web tracker.
    """
    try:
        from .paths import ceefax_root

        p = ceefax_root() / "radio_config.json"
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_tx_log(*, wav_path: str, plan: Ax25AudioPlan) -> str:
    """
    Write a transmitter-side report for a prepared WAV.

    Does not upload yet — call finalize_tx_report() after playback so the map
    "last seen" time reflects end of TX, not WAV build time.
    """
    p = Path(wav_path)
    log_path = _tx_log_path_for_wav(p)

    rcfg = _load_radio_config()
    freq = (rcfg.get("frequency") or "").strip() if isinstance(rcfg, dict) else ""
    grid = (rcfg.get("grid") or "").strip().upper() if isinstance(rcfg, dict) else ""

    data = {
        "schema": 1,
        "kind": "ceefax_tx_report",
        "tx_id": plan.tx_id,
        "station_callsign": plan.src_callsign,
        "station_grid": grid or None,
        "dest_callsign": plan.dest_callsign,
        "frequency": freq or None,
        "wav_name": p.name,
        "wav_path": str(p),
        "generated_at": _utc_now_iso(),
        "loops": plan.loops,
        "page_ids": plan.page_ids,
        "page_count": len(plan.page_ids),
        "fragments_total": plan.fragments,
        "ui_frames_total": len(plan.ui_frames),
    }
    log_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(log_path)


def finalize_tx_report(wav_path: str | Path | None) -> str | None:
    """
    Stamp completed_at (UTC) on the TX log and upload it to the hub.
    """
    if not wav_path:
        return None
    log_path = _tx_log_path_for_wav(wav_path)
    if not log_path.is_file():
        return None
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        data["completed_at"] = _utc_now_iso()
        log_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None

    try:
        from ceefaxstation.uploader import auto_upload_log

        auto_upload_log(log_path, wait_stable=False)
    except Exception:  # noqa: BLE001
        pass
    return str(log_path)


def iter_ax25_afsk_bits_for_frames(
    ui_frames: List[bytes],
    *,
    preamble_flags: int,
    inter_frame_flags: int,
    postamble_flags: int,
) -> Iterable[int]:
    """
    Yield the complete bitstream (including flags) to be fed into NRZI/AFSK.
    """
    fb = flag_bits()

    for _ in range(max(0, preamble_flags)):
        yield from fb

    for frame in ui_frames:
        # Start delimiter
        yield from fb
        # Frame bits (LSB-first) + bit stuffing (flags excluded)
        yield from bit_stuff(bytes_to_bits_lsb(frame))
        # End delimiter + idle flags between frames
        for _ in range(max(1, inter_frame_flags)):
            yield from fb

    for _ in range(max(0, postamble_flags)):
        yield from fb


def build_ax25_audio_plan(
    *,
    pages: List[Page],
    loops: int,
    dest_callsign: str,
    src_callsign: str,
    max_info_bytes: int,
    tx_id: str | None = None,
) -> Ax25AudioPlan:
    """
    Build a list of UI frames (without flags) to transmit for `loops` full carousel loops.
    """
    from .ax25 import fragment_page_bytes

    tx_uuid: UUID = UUID(tx_id) if tx_id else uuid4()
    tx_id_str = str(tx_uuid)
    tx_id_bytes = tx_uuid.bytes

    ui_frames: List[bytes] = []
    fragments = 0
    page_ids: List[str] = []

    for _ in range(max(1, loops)):
        for page in pages:
            page_bytes = compile_page_to_frame(page)
            frags = fragment_page_bytes(
                tx_id_bytes=tx_id_bytes,
                page=page.page,
                subpage=page.subpage,
                page_bytes=page_bytes,
                max_info_bytes=max_info_bytes,
            )
            for frag in frags:
                ui_frames.append(
                    build_ui_frame(dest=dest_callsign, src=src_callsign, info=frag.payload)
                )
            fragments += len(frags)
            page_ids.append(page.page_id)

    return Ax25AudioPlan(
        ui_frames=ui_frames,
        pages=len(pages),
        fragments=fragments,
        loops=max(1, loops),
        tx_id=tx_id_str,
        src_callsign=src_callsign,
        dest_callsign=dest_callsign,
        page_ids=page_ids,
    )


def write_ax25_audio_wav_and_or_stdout(
    *,
    plan: Ax25AudioPlan,
    sample_rate: int,
    symbol_rate: int,
    frequency_mark: float,
    frequency_space: float,
    amplitude: float,
    preamble_flags: int,
    inter_frame_flags: int,
    postamble_flags: int,
    output_dir: str,
    output_mode: str,
    wav_basename: Optional[str] = None,
) -> str:
    """
    Produce one continuous WAV for the whole transmission. Optionally stream PCM to stdout too.

    Returns the WAV path.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_mode = (output_mode or "files").lower()

    if not wav_basename:
        wav_basename = datetime.now().strftime(f"ceefax_ax25_{plan.loops}x_%Y%m%d_%H%M%S.wav")
    wav_path = os.path.join(output_dir, wav_basename)

    mod = Afsk1200Modulator(
        sample_rate=sample_rate,
        symbol_rate=symbol_rate,
        frequency_mark=frequency_mark,
        frequency_space=frequency_space,
        amplitude=amplitude,
    )
    mod.reset()

    bits = iter_ax25_afsk_bits_for_frames(
        plan.ui_frames,
        preamble_flags=preamble_flags,
        inter_frame_flags=inter_frame_flags,
        postamble_flags=postamble_flags,
    )

    to_stdout = output_mode in ("stdout", "both")
    to_files = output_mode in ("files", "both")

    if not to_stdout and not to_files:
        raise ValueError(f"Unknown audio output mode: {output_mode}")

    wf = None
    try:
        if to_files:
            wf = wave.open(wav_path, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)

        def write_pcm(pcm: bytes) -> None:
            if to_files and wf is not None:
                wf.writeframes(pcm)
            if to_stdout:
                sys.stdout.buffer.write(pcm)
                sys.stdout.buffer.flush()

        mod.modulate_bits_to(bits, write_pcm)
    finally:
        if wf is not None:
            wf.close()

    # Write TX report alongside WAV generation so RX reports can be correlated.
    _write_tx_log(wav_path=wav_path, plan=plan)

    return wav_path

