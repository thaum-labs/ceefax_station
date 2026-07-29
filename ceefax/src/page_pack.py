"""Shared Ceefax hub page-pack helpers.

The hub publishes national/shared teletext pages. Each station keeps local-only
pages (local weather + callsign activity) and may overlay them after a pull.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACK_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"

# Station-specific pages that must never be overwritten by a hub pack.
LOCAL_ONLY_PAGE_PREFIXES: tuple[str, ...] = ("000", "102", "700", "900")

_PAGE_FILE_RE = re.compile(r"^(\d{3})(?:_(\d+))?\.json$")


def page_stem(path: Path | str) -> str:
    return Path(path).stem


def is_page_json_name(name: str) -> bool:
    return bool(_PAGE_FILE_RE.match(Path(name).name))


def is_local_only_page(name: str) -> bool:
    """True for 102 / 102_2 / 700 etc."""
    match = _PAGE_FILE_RE.match(Path(name).name)
    if not match:
        return False
    return match.group(1) in LOCAL_ONLY_PAGE_PREFIXES


def is_shared_page(name: str) -> bool:
    return is_page_json_name(name) and not is_local_only_page(name)


def iter_shared_page_files(pages_dir: Path) -> list[Path]:
    if not pages_dir.is_dir():
        return []
    files = [p for p in pages_dir.iterdir() if p.is_file() and is_shared_page(p.name)]
    return sorted(files, key=lambda p: p.name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    pages_dir: Path,
    generated_at: str | None = None,
    source: str = "ceefaxstation-hub",
) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    for path in iter_shared_page_files(pages_dir):
        pages.append(
            {
                "id": path.stem,
                "file": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "format_version": PACK_FORMAT_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source": source,
        "page_count": len(pages),
        "pages": pages,
    }


def write_manifest(pages_dir: Path, manifest: dict[str, Any]) -> Path:
    path = pages_dir / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def publish_pack(*, source_pages_dir: Path, pack_dir: Path) -> dict[str, Any]:
    """
    Copy shared pages from source_pages_dir into pack_dir and write manifest + zip.
    Local-only pages (102/700) are never published.
    """
    pack_dir.mkdir(parents=True, exist_ok=True)

    # Remove previously published page JSON (keep unrelated files alone).
    for existing in pack_dir.glob("*.json"):
        if existing.name == MANIFEST_NAME or is_page_json_name(existing.name):
            existing.unlink()

    shared = iter_shared_page_files(source_pages_dir)
    if not shared:
        raise FileNotFoundError(f"No shared pages found in {source_pages_dir}")

    for src in shared:
        dest = pack_dir / src.name
        dest.write_bytes(src.read_bytes())

    manifest = build_manifest(pages_dir=pack_dir)
    write_manifest(pack_dir, manifest)

    zip_path = pack_dir / "pages.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(pack_dir / MANIFEST_NAME, arcname=MANIFEST_NAME)
        for page in manifest["pages"]:
            zf.write(pack_dir / str(page["file"]), arcname=str(page["file"]))

    return manifest


def load_manifest(pack_dir: Path) -> dict[str, Any]:
    path = pack_dir / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(f"No page pack manifest at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def apply_pack_bytes(*, pack_bytes: bytes, pages_dir: Path) -> dict[str, Any]:
    """
    Extract a hub zip into pages_dir without touching local-only pages.
    Returns the manifest from the pack.
    """
    pages_dir.mkdir(parents=True, exist_ok=True)
    import io

    with zipfile.ZipFile(io.BytesIO(pack_bytes)) as zf:
        names = set(zf.namelist())
        if MANIFEST_NAME not in names:
            raise ValueError("page pack is missing manifest.json")
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("invalid manifest")

        written: list[str] = []
        for info in zf.infolist():
            name = Path(info.filename).name
            if name == MANIFEST_NAME:
                continue
            if not is_shared_page(name):
                # Skip local-only or non-page entries defensively.
                continue
            target = pages_dir / name
            target.write_bytes(zf.read(info))
            written.append(name)

        if not written:
            raise ValueError("page pack contained no shared pages")

        # Persist hub manifest beside pages for debugging / status.
        (pages_dir / "hub_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest


def validate_pack_dir(pack_dir: Path) -> dict[str, Any]:
    """Load manifest and verify on-disk sha256 hashes."""
    manifest = load_manifest(pack_dir)
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("manifest has no pages")
    for entry in pages:
        if not isinstance(entry, dict):
            raise ValueError("invalid manifest page entry")
        name = str(entry.get("file") or "")
        path = pack_dir / name
        if not path.exists():
            raise FileNotFoundError(f"missing packed page: {name}")
        expected = str(entry.get("sha256") or "")
        actual = sha256_file(path)
        if expected and actual != expected:
            raise ValueError(f"checksum mismatch for {name}")
    return manifest
