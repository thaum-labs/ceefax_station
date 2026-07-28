"""Non-interactive hub refresh + page-pack publish for the official site.

Reads provider API keys from the environment, refreshes shared pages locally,
then publishes the pack served by the public page-pack API.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Ceefax pages with server API keys and publish the hub pack."
    )
    parser.add_argument(
        "--pages-dir",
        default=str(_repo_root() / "ceefax" / "pages"),
        help="Pages directory to write (default: ceefax/pages).",
    )
    parser.add_argument(
        "--pack-dir",
        default=None,
        help="Pack output directory (default: CEEFAXWEB_PAGE_PACK_DIR or ceefaxweb/data/page_pack).",
    )
    parser.add_argument(
        "--callsign",
        default=None,
        help="Hub callsign for priming (default: CEEFAX_HUB_CALLSIGN or CEEFAX).",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Only publish an existing pages directory (do not fetch live data).",
    )
    args = parser.parse_args(argv)

    # Ensure hub refresh never tries to pull from itself.
    os.environ["CEEFAX_PAGES_SOURCE"] = "local"

    pages_dir = Path(args.pages_dir).expanduser().resolve()
    pages_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_refresh:
        from ceefax.src.hub_pages import refresh_station_pages

        callsign = (
            (args.callsign or os.environ.get("CEEFAX_HUB_CALLSIGN") or "CEEFAX").strip().upper()
        )
        print(f"Refreshing hub pages locally as {callsign} ...")
        try:
            result = refresh_station_pages(
                callsign=callsign,
                frequency="",
                auto_location=True,
                source="local",
                pages_dir=pages_dir,
            )
            print(f"Refresh mode: {result.get('mode')}")
        except Exception as exc:  # noqa: BLE001
            print(f"Hub page refresh failed: {exc}", file=sys.stderr)
            return 1

    from ceefax.src.page_pack import publish_pack
    from ceefaxweb.page_pack_api import default_pack_dir

    pack_dir = (
        Path(args.pack_dir).expanduser().resolve()
        if args.pack_dir
        else default_pack_dir(_repo_root())
    )
    try:
        manifest = publish_pack(source_pages_dir=pages_dir, pack_dir=pack_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Hub page publish failed: {exc}", file=sys.stderr)
        return 1

    print(f"Published {manifest['page_count']} shared pages to {pack_dir}")
    print(f"Generated at: {manifest['generated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
