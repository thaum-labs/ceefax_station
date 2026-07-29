#!/usr/bin/env python3
"""Capture fresh web-tracker screenshots from the public site."""

from __future__ import annotations

import asyncio
from pathlib import Path


URL = "https://ceefaxstation.com/"
# New filenames bust GitHub's image CDN cache when the README path changes.
DESKTOP_MAP = "desktop-tracker.png"
DESKTOP_DETAIL = "desktop-with-detail.png"
MOBILE_MAP = "mobile-map.png"
MOBILE_PANEL = "mobile-panel-expanded.png"


async def main() -> None:
    from playwright.async_api import async_playwright

    out_dir = Path("screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # Desktop main view
        page = await browser.new_page(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
        )
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_selector("img.logo", timeout=15000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(out_dir / DESKTOP_MAP), full_page=False)

        # Desktop with detail panel preference (same viewport; capture after a short wait)
        await page.screenshot(path=str(out_dir / DESKTOP_DETAIL), full_page=False)
        await page.close()

        # Mobile map
        mobile = await browser.new_page(
            viewport={"width": 430, "height": 900},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        await mobile.goto(URL, wait_until="networkidle", timeout=60000)
        await mobile.wait_for_timeout(2500)
        await mobile.screenshot(path=str(out_dir / MOBILE_MAP), full_page=False)

        # Mobile panel expanded if the toggle exists
        for selector in (
            "text=filters & settings",
            "button:has-text('filters')",
            "[aria-label*='filter' i]",
            "text=Refresh",
        ):
            try:
                loc = mobile.locator(selector).first
                if await loc.count():
                    await loc.click(timeout=2000)
                    await mobile.wait_for_timeout(800)
                    break
            except Exception:  # noqa: BLE001
                continue
        await mobile.screenshot(path=str(out_dir / MOBILE_PANEL), full_page=False)
        await mobile.close()
        await browser.close()

    print(f"Wrote tracker screenshots to screenshots/ ({DESKTOP_MAP}, …)")


if __name__ == "__main__":
    asyncio.run(main())
