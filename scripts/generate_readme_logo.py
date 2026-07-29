#!/usr/bin/env python3
"""
Refresh README / website logo assets from the master branding image.

Copies:
  - branding/logo.png → screenshots/readme-logo.png
  - branding/logo.png → ceefaxweb/static/logo.png
  - branding/ceefaxstation.ico → ceefaxweb/static/favicon.ico
"""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"
LOGO = BRANDING / "logo.png"
ICO = BRANDING / "ceefaxstation.ico"


def main() -> None:
    if not LOGO.exists():
        raise SystemExit(f"Missing master logo: {LOGO}")

    targets = [
        ROOT / "screenshots" / "readme-logo.png",
        ROOT / "ceefaxweb" / "static" / "logo.png",
    ]
    for dest in targets:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LOGO, dest)
        print(f"Wrote {dest.relative_to(ROOT)}")

    if ICO.exists():
        fav = ROOT / "ceefaxweb" / "static" / "favicon.ico"
        shutil.copy2(ICO, fav)
        print(f"Wrote {fav.relative_to(ROOT)}")
    else:
        print(f"WARNING: missing {ICO.relative_to(ROOT)}; favicon not updated")


if __name__ == "__main__":
    main()
