#!/usr/bin/env python3
"""
Generate PNG screenshots of selected Ceefax terminal viewer pages.

This renders the compiled 50x23 page matrices into a lightweight HTML page
and screenshots the page container using Playwright (headless Chromium).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure repo root is on sys.path when executed as `python scripts/<file>.py`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ceefax.src.compiler import PAGE_HEIGHT, PAGE_WIDTH, compile_page_to_matrix, load_page_from_file
from ceefax.src.config import load_config


def _build_html(*, page_num: str, title: str, matrix: list[str]) -> str:
    now = datetime.now()
    clock = now.strftime("%H:%M %d %b").upper()  # e.g. "12:34 06 DEC"
    header_left = f"CEEFAX {page_num.rjust(3)} {(title or '').upper()[:20]}"
    header_left = header_left[:PAGE_WIDTH].ljust(PAGE_WIDTH)

    # Escape HTML, keep spacing.
    def esc(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    lines = "\n".join(esc(ln) for ln in matrix[:PAGE_HEIGHT])

    # Pure local fonts (no external requests) to keep this deterministic/offline.
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ceefax {esc(page_num)} - {esc(title)}</title>
    <style>
      :root {{
        --w: {PAGE_WIDTH};
        --h: {PAGE_HEIGHT};
      }}
      html, body {{
        height: 100%;
      }}
      body {{
        margin: 0;
        background: #0b0b0b;
        display: grid;
        place-items: center;
        font-family: ui-monospace, "Cascadia Mono", Consolas, "Courier New", monospace;
      }}
      .ceefax {{
        background: #000;
        border: 2px solid #2a2a2a;
        box-shadow: 0 16px 60px rgba(0,0,0,.6);
      }}
      .hdr {{
        background: #0000cc;
        color: #ffd34d;
        font-weight: 700;
        padding: 8px 10px;
        display: flex;
        justify-content: space-between;
        gap: 12px;
      }}
      .hdr .left {{
        white-space: pre;
      }}
      .hdr .right {{
        white-space: nowrap;
      }}
      pre {{
        margin: 0;
        padding: 10px 10px 12px;
        color: #f1f1f1;
        font-size: 18px;
        line-height: 1.05;
        white-space: pre;
      }}
      /* A tiny bit of CRT-ish softness without killing legibility */
      .ceefax {{
        filter: contrast(1.05) saturate(1.05);
      }}
    </style>
  </head>
  <body>
    <div class="ceefax" id="ceefax">
      <div class="hdr">
        <div class="left">{esc(header_left)}</div>
        <div class="right">{esc(clock)}</div>
      </div>
      <pre>{lines}</pre>
    </div>
  </body>
</html>
"""


async def _screenshot_html(*, html_path: Path, png_path: Path) -> None:
    from playwright.async_api import async_playwright  # lazy import

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1200, "height": 800},
            device_scale_factor=2,
        )
        await page.goto(html_path.resolve().as_uri())
        await page.wait_for_selector("#ceefax")
        el = page.locator("#ceefax")
        await el.screenshot(path=str(png_path))
        await browser.close()


async def main() -> None:
    cfg = load_config()
    pages_dir = Path(cfg.general.page_dir)

    out_dir = Path("screenshots/ceefax-terminal")
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path("screenshots/.tmp-ceefax-html")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Requested pages:
    # - 000 (start)
    # - TV guide (use 503: TV Highlights as the TV guide content page)
    # - Football fixtures (304: Fixtures & Results)
    # - London weather (101)
    # - UK weather map (103)
    targets: list[tuple[str, str]] = [
        ("000", "Start"),
        ("503", "TV Guide"),
        ("304", "Football Fixtures"),
        ("101", "London Weather"),
        ("103", "UK Weather Map"),
    ]

    for page_num, _label in targets:
        page_file = pages_dir / f"{page_num}.json"
        if not page_file.exists():
            raise SystemExit(f"Missing page file: {page_file}")

        page_obj = load_page_from_file(str(page_file))
        matrix = compile_page_to_matrix(page_obj)
        html = _build_html(page_num=page_obj.page, title=page_obj.title, matrix=matrix)

        html_path = tmp_dir / f"page-{page_num}.html"
        html_path.write_text(html, encoding="utf-8")

        png_path = out_dir / f"page-{page_num}.png"
        await _screenshot_html(html_path=html_path, png_path=png_path)
        print(f"Wrote {png_path}")


if __name__ == "__main__":
    asyncio.run(main())


