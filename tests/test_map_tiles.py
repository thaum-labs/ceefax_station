"""CARTO basemap tiles must carry the API key or they render a watermark."""

from __future__ import annotations

from pathlib import Path

CARTO_BASEMAP_KEY = "cb1_3nxz_2_5c52e4284e978fc6401ea327"
INDEX_HTML = Path(__file__).resolve().parents[1] / "ceefaxweb" / "static" / "index.html"


def test_carto_basemap_urls_include_api_key() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert f"const CARTO_BASEMAP_KEY = '{CARTO_BASEMAP_KEY}';" in html
    assert (
        "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?key=' + CARTO_BASEMAP_KEY"
    ) in html
    assert (
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=' + CARTO_BASEMAP_KEY"
    ) in html
