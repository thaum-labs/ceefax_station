from __future__ import annotations

import curses

from ceefax.src.compiler import Page
from ceefax.src.viewer import (
    _edit_text_value,
    _find_page_index,
    _handle_page_key,
    _page_entry_result,
    _rx_footer_status,
    _rx_status_fields,
    _ui_layout,
)


def _page(number: str, subpage: int = 1) -> Page:
    return Page(page=number, title=f"Page {number}", timestamp="", subpage=subpage, content=[])


class _SizedWindow:
    def __init__(self, rows: int, columns: int) -> None:
        self.rows = rows
        self.columns = columns

    def getmaxyx(self) -> tuple[int, int]:
        return (self.rows, self.columns)


class _FakeWindow(_SizedWindow):
    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self.writes: list[tuple[int, int, str]] = []

    def clear(self) -> None:
        self.writes.clear()

    def addstr(self, row: int, column: int, text: str, _attr: int = 0) -> None:
        assert 0 <= row < self.rows
        assert 0 <= column < self.columns
        assert column + len(text) <= self.columns
        self.writes.append((row, column, text))

    def refresh(self) -> None:
        pass


def test_layout_reserves_footer_at_80x24_and_centers_when_taller() -> None:
    assert _ui_layout(_SizedWindow(24, 80)) == (0, 15, 22, 50)
    assert _ui_layout(_SizedWindow(30, 100)) == (2, 25, 23, 50)
    assert _ui_layout(_SizedWindow(13, 80)) is None
    assert _ui_layout(_SizedWindow(24, 49)) is None


def test_page_and_mode_screens_render_inside_80x24(monkeypatch) -> None:
    from ceefax.src import viewer
    from ceefax.src.compiler import compile_page_to_matrix

    monkeypatch.setattr(viewer.curses, "has_colors", lambda: False)
    monkeypatch.setattr(
        viewer,
        "_load_radio_config",
        lambda: {"callsign": "M7TJF", "frequency": "145.500 MHz"},
    )
    page = Page(
        page="101",
        title="London weather",
        timestamp="",
        subpage=1,
        content=["LONDON WEATHER", "Temperature 18 C", "Cloudy"],
    )
    window = _FakeWindow(24, 80)
    viewer._draw_page(window, page, compile_page_to_matrix(page), 0, 1)
    assert any(row == 22 and "PAGE" in text for row, _, text in window.writes)
    assert any(row == 23 and "PAGE 101" in text for row, _, text in window.writes)

    viewer._draw_mode_screen(
        window,
        mode="TX",
        title="Transmission ready",
        status="Check radio",
        fields=[("Callsign", "M7TJF"), ("Pages", "28")],
        progress=0.5,
        progress_label="Transmit",
        footer_status="ENTER: START  ESC: CANCEL",
    )
    assert any("TRANSMISSION READY" in text for _, _, text in window.writes)
    assert any(row == 23 and "ENTER: START" in text for row, _, text in window.writes)


def test_numeric_page_entry_opens_first_matching_subpage() -> None:
    pages = [_page("000"), _page("101"), _page("503", 1), _page("503", 2)]
    assert _find_page_index(pages, "503") == 2
    assert _page_entry_result(pages, "503") == (2, "PAGE 503")
    assert _page_entry_result(pages, "999") == (None, "PAGE 999 NOT FOUND")

    index, digits, notice, handled = _handle_page_key(ord("5"), pages, 0, "")
    assert (index, digits, notice, handled) == (0, "5", "", True)
    index, digits, notice, handled = _handle_page_key(ord("0"), pages, index, digits)
    assert (index, digits, notice, handled) == (0, "50", "", True)
    index, digits, notice, handled = _handle_page_key(ord("3"), pages, index, digits)
    assert (index, digits, notice, handled) == (2, "", "PAGE 503", True)


def test_numeric_page_entry_supports_backspace_and_preserves_page_on_miss() -> None:
    pages = [_page("000"), _page("101")]
    index, digits, _, _ = _handle_page_key(ord("9"), pages, 1, "")
    index, digits, _, _ = _handle_page_key(curses.KEY_BACKSPACE, pages, index, digits)
    assert (index, digits) == (1, "")

    for key in "999":
        index, digits, notice, handled = _handle_page_key(ord(key), pages, index, digits)
    assert (index, digits, notice, handled) == (1, "", "PAGE 999 NOT FOUND", True)


def test_tui_callsign_editor_accepts_safe_characters() -> None:
    value = ""
    for key in "m7tjf-1":
        value, submit, cancel = _edit_text_value(value, ord(key))
        assert not submit and not cancel
    assert value == "M7TJF-1"

    value, submit, cancel = _edit_text_value(value, curses.KEY_BACKSPACE)
    assert (value, submit, cancel) == ("M7TJF-", False, False)
    value, submit, cancel = _edit_text_value(value, 13)
    assert (value, submit, cancel) == ("M7TJF-", True, False)
    _, submit, cancel = _edit_text_value(value, 27)
    assert not submit and cancel


def test_rx_dashboard_summarizes_decoder_state() -> None:
    stats = {
        "rx_db": -12.34,
        "cfx_frames": 47,
        "station_callsign": "G1ABC",
        "pages_decoded": {"101.1": {}, "503.2": {}},
        "page_progress": {
            "101.1": {"total": 2, "got": [0, 1]},
            "304.1": {"total": 3, "got": [0]},
        },
    }
    fields = dict(_rx_status_fields(stats, source="Live audio", device="USB Audio"))
    assert fields == {
        "Source": "Live audio",
        "Audio": "USB Audio",
        "Signal": "-12.3 dB",
        "Frames": "47",
        "Pages": "2 complete / 1 partial",
        "Last station": "G1ABC",
    }
    assert _rx_footer_status(stats) == "RX -12.3 dB  47 FRAMES  2 PAGES  LAST G1ABC"
