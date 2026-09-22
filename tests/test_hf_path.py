"""HF is opt-in. A config with no band key must stay on the FM AFSK path."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
import threading
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vhf_page_101.json"
TX_ID = "11111111-1111-1111-1111-111111111111"
FRAME_SHA = "d7414ba9cd721e8e2e4776843176245c3ae517b2a350a0fadb50e156e0c1938f"
BIT_SHA = "b8715842e2e617c38e578b73974f9f6aca99d6141503f19cf951477deaa40ad9"
PCM_SHA = "08dab2ee02af61617b72e1d980927ca095e1111ea9cfafd7ae90b2ca6912fd0d"

VHF_TOML = """
[general]
mode = "ax25_audio"
page_dir = "pages"
log_level = "INFO"
output_dir = "out"

[audio]
sample_rate = 48000
symbol_rate = 1200
frequency_mark = 1200.0
frequency_space = 2200.0
amplitude = 0.5
pre_tone_ms = 300
post_tone_ms = 300
vox_hold_ms = 250
output = "files"

[ax25]
enabled = true
callsign = "N0CALL-1"
kiss_port = "/dev/ttyUSB0"
baud_rate = 9600
dest_callsign = "CEEFAX"
max_info_bytes = 240
preamble_flags = 150
inter_frame_flags = 2
postamble_flags = 20
loops_per_hour = 3
refresh_lead_seconds = 180

[carousel]
page_duration_ms = 1500
loop_delay_ms = 200
"""


def _write_config(tmp_path: Path, extra: str = "") -> str:
    path = tmp_path / "config.toml"
    path.write_text(VHF_TOML + extra, encoding="utf-8")
    return str(path)


def test_save_link_settings_updates_band_and_keeps_other_keys(tmp_path: Path) -> None:
    from ceefax.src.config import load_config, save_link_settings

    path = _write_config(tmp_path)
    save_link_settings("hf", "RDM-300S", path)
    cfg = load_config(path)
    assert cfg.radio.band == "hf"
    assert cfg.hf.mode == "RDM-300S"
    assert cfg.ax25.loops_per_hour == 3
    assert cfg.hf.loops_per_hour == 1
    text = Path(path).read_text(encoding="utf-8")
    assert text.count("[radio]") == 1
    assert text.count("[hf]") == 1


def test_default_config_without_new_keys_stays_on_fm(tmp_path: Path) -> None:
    from ceefax.src.config import load_config
    from ceefax.src.hourly_ax25_audio import hourly_transport

    cfg = load_config(_write_config(tmp_path))
    assert cfg.radio.band == "vhf"
    assert cfg.ax25.loops_per_hour == 3
    assert cfg.ax25.max_info_bytes == 240
    assert cfg.hf.mode == "RDM-600S"
    assert cfg.hf.loops_per_hour == 1
    assert cfg.hf.max_frame_bytes == 170
    assert hourly_transport(cfg) == "vhf"


def test_config_rejects_unknown_band_and_hf_mode(tmp_path: Path) -> None:
    from ceefax.src.config import load_config

    with pytest.raises(ValueError, match="radio.band"):
        load_config(_write_config(tmp_path, '\n[radio]\nband = "uhf"\n'))
    with pytest.raises(ValueError, match="hf.mode"):
        load_config(_write_config(tmp_path, '\n[hf]\nmode = "OFDM"\n'))
    with pytest.raises(ValueError, match="hf.mode"):
        load_config(_write_config(tmp_path, '\n[radio]\nband = "hf"\n[hf]\nmode = "RDM-1200"\n'))
    cfg = load_config(_write_config(tmp_path, '\n[radio]\nband = "hf"\n[hf]\nmode = "RDM-300S"\n'))
    assert cfg.radio.band == "hf"
    assert cfg.hf.mode == "RDM-300S"


def test_vhf_scheduler_does_not_start_modem73() -> None:
    from ceefax.src.hourly_ax25_audio import run_hourly_ax25_audio

    source = inspect.getsource(run_hourly_ax25_audio)
    vhf_body = source.split("return", 1)[1]
    assert "run_hf_pass" not in vhf_body
    assert "modem73" not in vhf_body.lower()
    assert "Modem73" not in vhf_body


def test_vhf_plan_matches_current_afsk_bitstream() -> None:
    from ceefax.src.afsk import Afsk1200Modulator
    from ceefax.src.ax25_audio import build_ax25_audio_plan, iter_ax25_afsk_bits_for_frames
    from ceefax.src.compiler import load_page_from_file

    page = load_page_from_file(str(FIXTURE))
    plan = build_ax25_audio_plan(
        pages=[page],
        loops=1,
        dest_callsign="CEEFAX",
        src_callsign="N0CALL-1",
        max_info_bytes=240,
        tx_id=TX_ID,
    )
    frames = b"".join(plan.ui_frames)
    assert hashlib.sha256(frames).hexdigest() == FRAME_SHA
    bits = list(
        iter_ax25_afsk_bits_for_frames(
            plan.ui_frames,
            preamble_flags=150,
            inter_frame_flags=2,
            postamble_flags=20,
        )
    )
    assert hashlib.sha256(bytes(bits)).hexdigest() == BIT_SHA
    mod = Afsk1200Modulator(
        sample_rate=48000,
        symbol_rate=1200,
        frequency_mark=1200.0,
        frequency_space=2200.0,
        amplitude=0.5,
    )
    pcm = mod.modulate_bits(bits)
    assert hashlib.sha256(pcm).hexdigest() == PCM_SHA


def test_hf_page_splits_to_kiss_payloads_that_reassemble(tmp_path: Path) -> None:
    from ceefax.src.compiler import compile_page_to_frame, load_page_from_file
    from ceefax.src.config import load_config
    from ceefax.src.hf import build_hf_pass_plan, parse_station_beacon
    from ceefax.src.viewer import _Ax25FragmentReassembler, _parse_cfx_info

    page = load_page_from_file(str(FIXTURE))
    original = compile_page_to_frame(page)
    assert len(original) > 170
    cfg = load_config(_write_config(tmp_path, '\n[radio]\nband = "hf"\n'))
    plan = build_hf_pass_plan(
        pages=[page],
        loops=cfg.hf.loops_per_hour,
        src_callsign="N0CALL-1",
        frequency="7.040 MHz",
        grid="IO91WM",
        max_frame_bytes=cfg.hf.max_frame_bytes,
        mode=cfg.hf.mode,
        tx_id=TX_ID,
    )
    assert plan.payloads
    beacon = parse_station_beacon(plan.payloads[0])
    assert beacon is not None
    assert beacon["tx_id"] == TX_ID
    assert beacon["callsign"] == "N0CALL-1"
    assert beacon["grid"] == "IO91WM"
    fragments = plan.payloads[1:]
    assert fragments
    assert all(len(payload) <= 170 for payload in plan.payloads)
    parsed = [_parse_cfx_info(payload) for payload in fragments]
    assert all(item and item["tx_id"] == TX_ID for item in parsed)
    indexes = [item["idx"] for item in parsed]
    assert indexes == list(range(len(fragments)))

    reassembler = _Ax25FragmentReassembler()
    assembled = None
    for payload in fragments:
        assembled = reassembler.add(payload) or assembled
    assert assembled is not None
    tx_id, page_no, subpage, data = assembled
    assert tx_id == TX_ID
    assert page_no == "101"
    assert subpage == 1
    assert data == original
    assert reassembler.pending_count() == 0


def test_reassembler_evicts_stale_partials_and_stays_bounded() -> None:
    from ceefax.src.ax25 import build_fragment_header_v2
    from uuid import UUID

    from ceefax.src.viewer import _Ax25FragmentReassembler

    tx = UUID(TX_ID).bytes
    clock = {"now": 0.0}

    def now() -> float:
        return clock["now"]

    limited = _Ax25FragmentReassembler(max_partials=2, max_age_s=10_000, clock=now)
    for index in range(4):
        header = build_fragment_header_v2(
            tx_id_bytes=tx,
            page=f"{index:03d}",
            subpage=1,
            index=0,
            total=2,
        )
        assert limited.add(header + b"x") is None
        clock["now"] += 1
    assert limited.pending_count() <= 2

    aging = _Ax25FragmentReassembler(max_partials=8, max_age_s=10, clock=now)
    clock["now"] = 0
    first = build_fragment_header_v2(tx_id_bytes=tx, page="200", subpage=1, index=0, total=2)
    assert aging.add(first + b"a") is None
    assert aging.pending_count() == 1
    clock["now"] = 100
    second = build_fragment_header_v2(tx_id_bytes=tx, page="201", subpage=1, index=0, total=2)
    assert aging.add(second + b"b") is None
    assert aging.pending_count() == 1

    completing = _Ax25FragmentReassembler(clock=now)
    clock["now"] = 0
    pieces = []
    for index in range(2):
        pieces.append(
            build_fragment_header_v2(tx_id_bytes=tx, page="202", subpage=1, index=index, total=2)
            + bytes([index])
        )
    assert completing.add(pieces[0]) is None
    done = completing.add(pieces[1])
    assert done is not None
    assert done[3] == bytes([0, 1])
    assert completing.pending_count() == 0


def test_missed_beacon_still_reassembles_page() -> None:
    from ceefax.src.hf import ingest_hf_payload
    from ceefax.src.ax25 import build_fragment_header_v2
    from uuid import UUID

    from ceefax.src.viewer import _Ax25FragmentReassembler

    tx = UUID(TX_ID).bytes
    stats = {}
    beacons = {}
    reassembler = _Ax25FragmentReassembler()
    payloads = [
        build_fragment_header_v2(tx_id_bytes=tx, page="101", subpage=1, index=index, total=2) + bytes([index])
        for index in range(2)
    ]
    result = None
    for payload in payloads:
        result = ingest_hf_payload(reassembler, payload, stats, beacons) or result
    assert result is not None
    assert result[3] == bytes([0, 1])
    assert not stats.get("station_callsign")


def test_kiss_roundtrip_escapes_frame_markers() -> None:
    from ceefax.src.kissframe import encode_kiss_frame, iter_kiss_frames, payload_from_kiss_frame

    payload = bytes([0xC0, 0xDB, 0x00, 0xFF])
    encoded = encode_kiss_frame(payload)
    buf = bytearray(encoded + encoded)
    frames = list(iter_kiss_frames(buf))
    assert [payload_from_kiss_frame(frame) for frame in frames] == [payload, payload]
    assert buf == bytearray()


def test_set_config_uses_published_robust_modes() -> None:
    from ceefax.src.hf import hf_set_config

    assert hf_set_config("RDM-600S") == {
        "cmd": "set_config",
        "modem_type": 2,
        "robust_mode": 6,
        "csma_band": 0,
        "csma_enabled": True,
        "fragmentation_enabled": False,
    }
    assert hf_set_config("RDM-300S")["robust_mode"] == 7
    with pytest.raises(ValueError):
        hf_set_config("RDM-1200")


def test_control_port_length_prefix_roundtrip() -> None:
    from ceefax.src.hf import ControlClient

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    seen = {}

    def serve() -> None:
        conn, _addr = server.accept()
        import struct

        raw_len = conn.recv(4)
        size = struct.unpack(">I", raw_len)[0]
        body = b""
        while len(body) < size:
            body += conn.recv(size - len(body))
        seen["cmd"] = json.loads(body.decode("utf-8"))
        reply = json.dumps({"channel_state": "idle", "ptt_on": False, "tx_frame_count": 0}).encode()
        conn.sendall(struct.pack(">I", len(reply)) + reply)
        conn.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        client = ControlClient("127.0.0.1", port, timeout_s=2)
        status = client.get_status()
        client.close()
    finally:
        thread.join(timeout=2)
        server.close()
    assert seen["cmd"] == {"cmd": "get_status"}
    assert status["channel_state"] == "idle"
