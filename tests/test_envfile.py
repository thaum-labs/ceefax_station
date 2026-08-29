from __future__ import annotations

import os
from pathlib import Path

from ceefaxweb.envfile import load_repo_dotenv


def test_load_repo_dotenv_sets_unset_keys(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "RESEND_API_KEY=re_from_file\n"
        "export CEEFAXWEB_NOTIFY_TO=owner@example.com\n"
        "# comment\n"
        "ALREADY=from_file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("CEEFAXWEB_NOTIFY_TO", raising=False)
    monkeypatch.setenv("ALREADY", "preexisting")

    loaded = load_repo_dotenv(tmp_path)
    assert loaded == env
    assert os.environ["RESEND_API_KEY"] == "re_from_file"
    assert os.environ["CEEFAXWEB_NOTIFY_TO"] == "owner@example.com"
    assert os.environ["ALREADY"] == "preexisting"


def test_load_repo_dotenv_missing_file(tmp_path: Path) -> None:
    assert load_repo_dotenv(tmp_path) is None
