"""Load repo-root `.env` into process env (unset keys only).

systemd may already inject vars via EnvironmentFile; this makes
`RESEND_API_KEY` / `CEEFAXWEB_*` work when they only exist in the
checkout `.env` (the common DigitalOcean layout).
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_repo_dotenv(root: Path | None = None) -> Path | None:
    """
    Parse `<root>/.env` and set os.environ for keys that are not already set.

    Returns the path loaded, or None if missing/unreadable.
    """
    env_path = (root or repo_root()) / ".env"
    if not env_path.is_file():
        return None
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val
    return env_path
