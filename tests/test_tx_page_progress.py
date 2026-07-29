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
