from __future__ import annotations

from unittest.mock import patch

from ceefax.src.hub_pages import _needs_station_setup, _stdin_is_interactive


def test_needs_station_setup_placeholders() -> None:
    assert _needs_station_setup("")
    assert _needs_station_setup("TEST")
    assert _needs_station_setup("N0CALL-1")
    assert not _needs_station_setup("M7TJF")


def test_empty_cli_defaults_to_debug_view() -> None:
    from ceefaxstation import __main__ as cli

    captured: list[list[str]] = []

    def fake_parse(self, args=None, namespace=None):  # noqa: ANN001
        captured.append(list(args or []))
        raise SystemExit(0)

    with patch.object(cli.argparse.ArgumentParser, "parse_args", fake_parse):
        try:
            cli.main([])
        except SystemExit:
            pass
    assert captured and captured[0][:1] == ["debug"]
    assert "--view" in captured[0]
    assert "--refresh" in captured[0]


def test_stdin_interactive_helper() -> None:
    # Should not raise; boolean result depends on environment.
    assert isinstance(_stdin_is_interactive(), bool)


def test_frequency_choices_include_common_bands() -> None:
    from ceefax.src.viewer import _frequency_choices

    choices = _frequency_choices()
    assert "144.800 MHz (2m)" in choices
    assert "433.500 MHz (70cm)" in choices
    assert "14.105 MHz (20m)" in choices
    # Stable HF → VHF → UHF order
    assert choices.index("3.580 MHz (80m)") < choices.index("144.800 MHz (2m)")
    assert choices.index("144.800 MHz (2m)") < choices.index("433.500 MHz (70cm)")
