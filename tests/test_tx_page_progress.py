from __future__ import annotations

import wave
from pathlib import Path

from ceefax.src.viewer import _estimate_tx_page, _wav_duration_seconds


def test_estimate_tx_page_spreads_evenly() -> None:
    pages = ["101", "200", "300", "400"]
    assert _estimate_tx_page(pages, loop_elapsed=0.0, loop_duration=40.0) == ("101", 1, 4)
    assert _estimate_tx_page(pages, loop_elapsed=10.0, loop_duration=40.0) == ("200", 2, 4)
    assert _estimate_tx_page(pages, loop_elapsed=20.0, loop_duration=40.0) == ("300", 3, 4)
    assert _estimate_tx_page(pages, loop_elapsed=39.9, loop_duration=40.0) == ("400", 4, 4)


def test_estimate_tx_page_empty_list() -> None:
    assert _estimate_tx_page([], loop_elapsed=5.0, loop_duration=10.0) == ("?", 1, 1)


def test_hf_progress_uses_rdm_frame_time_not_ax25_wav() -> None:
    from ceefax.src.viewer import _hf_tx_progress

    pages = ["101", "200", "300", "400"]
    # 4 frames at 3.6 s is 14.4 s on RDM-600S. An AX.25 WAV of the same pages is much shorter.
    early = _hf_tx_progress(
        elapsed_s=3.6,
        frame_count=4,
        seconds_per_frame=3.6,
        page_ids=pages,
    )
    assert early["duration_s"] == 14.4
    assert early["on_air_frame"] == 2
    assert early["page_id"] == "200"
    assert early["remaining_s"] == 10.8
    assert early["fraction"] < 0.99

    slow = _hf_tx_progress(
        elapsed_s=7.1,
        frame_count=4,
        seconds_per_frame=7.1,
        page_ids=pages,
    )
    assert abs(slow["duration_s"] - 28.4) < 0.01
    assert slow["on_air_frame"] == 2
    assert abs(slow["remaining_s"] - 21.3) < 0.01

    done = _hf_tx_progress(
        elapsed_s=3.0,
        frame_count=4,
        seconds_per_frame=3.6,
        page_ids=pages,
        finished=True,
    )
    assert done["fraction"] == 1.0
    assert done["remaining_s"] == 0.0


def test_wav_duration_seconds(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    rate = 8000
    frames = rate * 2  # 2 seconds
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames)
    assert abs(_wav_duration_seconds(str(path)) - 2.0) < 0.01
