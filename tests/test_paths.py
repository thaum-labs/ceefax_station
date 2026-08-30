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


def test_packaged_ceefax_root_uses_user_data(monkeypatch, tmp_path: Path) -> None:
    from ceefax.src import paths

    data = tmp_path / "user-data"
    monkeypatch.setenv("CEEFAX_PACKAGED", "1")
    monkeypatch.setenv("CEEFAX_DATA_DIR", str(data))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    root = paths.ceefax_root()
    assert root == data / "ceefax"
    assert (root / "config.toml").is_file()
    assert (root / "radio_config.json").is_file()
    assert "YOUR_CALLSIGN" in (root / "radio_config.json").read_text(encoding="utf-8")
    assert paths.pages_dir() == root / "pages"
    assert paths.repo_root() == data
    assert paths.uses_user_data()


def test_load_config_falls_back_to_default_toml() -> None:
    from ceefax.src.config import load_config

    default = Path(__file__).resolve().parents[1] / "ceefax" / "config.default.toml"
    cfg = load_config(str(default))
    assert cfg.audio.sample_rate == 48000
    assert cfg.ax25.dest_callsign == "CEEFAX"
