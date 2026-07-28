"""Publish shared Ceefax pages into the hub page-pack directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ceefax.src.page_pack import publish_pack
from ceefaxweb.page_pack_api import default_pack_dir


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish shared teletext pages for hub download (excludes 102/700)."
    )
    parser.add_argument(
        "--pages-dir",
        default=str(_repo_root() / "ceefax" / "pages"),
        help="Source pages directory after a local refresh (default: ceefax/pages).",
    )
    parser.add_argument(
        "--pack-dir",
        default=None,
        help="Destination pack directory (default: CEEFAXWEB_PAGE_PACK_DIR or ceefaxweb/data/page_pack).",
    )
    args = parser.parse_args(argv)

    source = Path(args.pages_dir).expanduser().resolve()
    pack_dir = Path(args.pack_dir).expanduser().resolve() if args.pack_dir else default_pack_dir(_repo_root())

    try:
        manifest = publish_pack(source_pages_dir=source, pack_dir=pack_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Publish failed: {exc}", file=sys.stderr)
        return 1

    print(f"Published {manifest['page_count']} shared pages to {pack_dir}")
    print(f"Generated at: {manifest['generated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
