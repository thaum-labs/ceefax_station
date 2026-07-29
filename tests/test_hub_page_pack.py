from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ceefax.src.page_pack import (
    apply_pack_bytes,
    is_local_only_page,
    is_shared_page,
    publish_pack,
)
from ceefaxweb.page_pack_api import RateLimiter


def test_shared_vs_local_page_classification() -> None:
    assert is_shared_page("101.json")
    assert is_shared_page("503_2.json")
    assert is_local_only_page("000.json")
    assert is_local_only_page("102.json")
    assert is_local_only_page("700.json")
    assert is_local_only_page("900.json")
    assert not is_shared_page("102.json")
    assert not is_shared_page("000.json")
    assert not is_shared_page("readme.txt")


def test_publish_and_apply_preserves_local_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    pack = tmp_path / "pack"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()

    (source / "200.json").write_text(
        json.dumps({"page": "200", "title": "News", "content": ["Hello"], "subpage": 1}),
        encoding="utf-8",
    )
    (source / "102.json").write_text(
        json.dumps({"page": "102", "title": "Local", "content": ["Mine"], "subpage": 1}),
        encoding="utf-8",
    )
    (dest / "102.json").write_text(
        json.dumps({"page": "102", "title": "Keep", "content": ["Local"], "subpage": 1}),
        encoding="utf-8",
    )
    (dest / "700.json").write_text(
        json.dumps({"page": "700", "title": "Call", "content": ["Radio"], "subpage": 1}),
        encoding="utf-8",
    )

    manifest = publish_pack(source_pages_dir=source, pack_dir=pack)
    assert manifest["page_count"] == 1
    assert (pack / "200.json").exists()
    assert not (pack / "102.json").exists()
    assert (pack / "pages.zip").exists()

    applied = apply_pack_bytes(pack_bytes=(pack / "pages.zip").read_bytes(), pages_dir=dest)
    assert applied["page_count"] == 1
    assert json.loads((dest / "200.json").read_text(encoding="utf-8"))["title"] == "News"
    assert json.loads((dest / "102.json").read_text(encoding="utf-8"))["title"] == "Keep"
    assert json.loads((dest / "700.json").read_text(encoding="utf-8"))["title"] == "Call"


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False
    assert limiter.allow("5.6.7.8") is True


def test_api_pages_manifest_and_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    pack = tmp_path / "pack"
    source.mkdir()
    (source / "304.json").write_text(
        json.dumps({"page": "304", "title": "Fixtures", "content": ["A v B"], "subpage": 1}),
        encoding="utf-8",
    )
    publish_pack(source_pages_dir=source, pack_dir=pack)
    monkeypatch.setenv("CEEFAXWEB_PAGE_PACK_DIR", str(pack))

    from ceefaxweb.server import create_app

    with TestClient(create_app()) as client:
        manifest_resp = client.get("/api/pages/manifest")
        assert manifest_resp.status_code == 200
        body = manifest_resp.json()
        assert body["page_count"] == 1
        assert body["pages"][0]["file"] == "304.json"

        pack_resp = client.get("/api/pages/pack")
        assert pack_resp.status_code == 200
        assert pack_resp.content.startswith(b"PK")
        assert "application/zip" in pack_resp.headers.get("content-type", "")


def test_api_pages_404_without_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty-pack"
    empty.mkdir()
    monkeypatch.setenv("CEEFAXWEB_PAGE_PACK_DIR", str(empty))
    from ceefaxweb.server import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/pages/manifest").status_code == 404
        assert client.get("/api/pages/pack").status_code == 404
