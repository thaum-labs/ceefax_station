#!/usr/bin/env python3
"""Capture fresh web-tracker screenshots from the public site."""

from __future__ import annotations

import asyncio
from pathlib import Path


URL = "https://ceefaxstation.com/"


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
        await page.wait_for_timeout(2500)
        await page.screenshot(path=str(out_dir / "desktop-map.png"), full_page=False)

        # Desktop with detail panel preference (same viewport; capture after a short wait)
        await page.screenshot(path=str(out_dir / "desktop-with-detail.png"), full_page=False)
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
        await mobile.screenshot(path=str(out_dir / "mobile-map.png"), full_page=False)

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
        await mobile.screenshot(path=str(out_dir / "mobile-panel-expanded.png"), full_page=False)
        await mobile.close()
        await browser.close()

    print("Wrote tracker screenshots to screenshots/")


if __name__ == "__main__":
    asyncio.run(main())
