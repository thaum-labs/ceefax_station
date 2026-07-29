#!/usr/bin/env python3
"""
Refresh README / website logo assets from the master branding image.

Copies a black-knocked-out (transparent) version to:
  - screenshots/ceefax-station-logo.png
  - ceefaxweb/static/logo.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"
LOGO = BRANDING / "logo.png"
ICO = BRANDING / "ceefaxstation.ico"


def knockout_black(im: Image.Image, threshold: int = 18) -> Image.Image:
    out = im.convert("RGBA")
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, _a = px[x, y]
            if r <= threshold and g <= threshold and b <= threshold:
                px[x, y] = (0, 0, 0, 0)
    return out


def main() -> None:
    if not LOGO.exists():
        raise SystemExit(f"Missing master logo: {LOGO}")

    transparent = knockout_black(Image.open(LOGO))
    targets = [
        ROOT / "screenshots" / "ceefax-station-logo.png",
        ROOT / "ceefaxweb" / "static" / "logo.png",
    ]
    for dest in targets:
        dest.parent.mkdir(parents=True, exist_ok=True)
        transparent.save(dest, format="PNG", optimize=True)
        print(f"Wrote {dest.relative_to(ROOT)}")

    if ICO.exists():
        fav = ROOT / "ceefaxweb" / "static" / "favicon.ico"
        fav.write_bytes(ICO.read_bytes())
        print(f"Wrote {fav.relative_to(ROOT)}")
    else:
        print(f"WARNING: missing {ICO.relative_to(ROOT)}; favicon not updated")


if __name__ == "__main__":
    main()
