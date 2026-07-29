from __future__ import annotations

from pathlib import Path


def test_frozen_ceefax_root_uses_localappdata(monkeypatch, tmp_path: Path) -> None:
    from ceefax.src import paths

    install = tmp_path / "Program Files" / "Ceefax Station"
    install_ceefax = install / "ceefax"
    install_ceefax.mkdir(parents=True)
    (install_ceefax / "config.toml").write_text("[general]\nmode='audio'\n", encoding="utf-8")
    (install_ceefax / "radio_config.json").write_text('{"callsign":"TEST"}', encoding="utf-8")

    user = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(user))
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(install / "ceefaxstation.exe"))

    root = paths.ceefax_root()
    assert root == user / "Ceefax Station" / "ceefax"
    assert (root / "config.toml").exists()
    assert (root / "radio_config.json").read_text(encoding="utf-8") == '{"callsign":"TEST"}'

    pages = paths.pages_dir()
    assert pages == root / "pages"
    assert pages.is_dir()


def test_dev_ceefax_root_is_repo_ceefax() -> None:
    from ceefax.src import paths

    root = paths.ceefax_root()
    assert root.name == "ceefax"
    assert (root.parent / "ceefaxstation").exists()
