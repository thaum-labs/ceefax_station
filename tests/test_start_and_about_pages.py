from __future__ import annotations


def test_start_page_contains_logo_and_callsign_placeholder() -> None:
    from ceefax.src.update_start_page import build_start_page

    lines = build_start_page()
    joined = "\n".join(lines)
    assert "CEEFAX" in joined or "░█" in joined
    assert "{{users callsign}}" in joined
    assert "created by M7TJF" in joined
    assert all(len(line) == 50 for line in lines)


def test_about_page_mentions_hub_and_creator() -> None:
    from ceefax.src.update_about_page import build_about_page

    lines = build_about_page()
    joined = "\n".join(lines)
    assert "ABOUT CEEFAX STATION" in joined
    assert "ceefaxstation.com" in joined
    assert "Pack time:" in joined
    assert "M7TJF" in joined
    assert all(len(line) == 50 for line in lines)


def test_hub_pack_stamp_formats_generated_at() -> None:
    from ceefax.src.page_pack import format_hub_pack_stamp

    stamp = format_hub_pack_stamp(
        {"generated_at": "2026-07-29T15:54:10.036249+00:00", "page_count": 30}
    )
    assert stamp == "2026-07-29 15:54 UTC (30 pages)"
    assert format_hub_pack_stamp(None) == "not pulled yet"
