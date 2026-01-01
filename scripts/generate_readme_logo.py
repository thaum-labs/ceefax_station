#!/usr/bin/env python3
"""
Generate a README logo image that renders consistently on GitHub.

Creates:
  - screenshots/readme-logo.png (transparent background, yellow text)
"""

from __future__ import annotations

import asyncio
from pathlib import Path


LOGO_TEXT = """  ░█▀▀░█▀▀░█▀▀░█▀▀░█▀█░█░█░░
  ░█░░░█▀▀░█▀▀░█▀▀░█▀█░▄▀▄░░
  ░▀▀▀░▀▀▀░▀▀▀░▀░░░▀░▀░▀░▀░░
░█▀▀░▀█▀░█▀█░▀█▀░▀█▀░█▀█░█▀█
░▀▀█░░█░░█▀█░░█░░░█░░█░█░█░█
░▀▀▀░░▀░░▀░▀░░▀░░▀▀▀░▀▀▀░▀░▀"""


HTML = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      html, body {{
        margin: 0;
        background: transparent;
      }}
      body {{
        display: inline-block;
        padding: 8px 12px;
      }}
      pre {{
        margin: 0;
        color: #ffd34d;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 20px;
        line-height: 1.05;
        white-space: pre;
        text-shadow: 0 0 8px rgba(255, 211, 77, 0.12);
      }}
    </style>
  </head>
  <body>
    <pre id="logo">{LOGO_TEXT}</pre>
  </body>
</html>
"""


async def main() -> None:
    from playwright.async_api import async_playwright

    out_dir = Path("screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "readme-logo.png"

    tmp = Path("screenshots/.tmp-readme-logo.html")
    tmp.write_text(HTML, encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1200, "height": 400}, device_scale_factor=2)
        await page.goto(tmp.resolve().as_uri())
        el = page.locator("#logo")
        await el.screenshot(path=str(out_path), omit_background=True)
        await browser.close()

    tmp.unlink(missing_ok=True)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())


