from __future__ import annotations

import os

import uvicorn

from .envfile import load_repo_dotenv
from .server import create_app


def main() -> None:
    load_repo_dotenv()
    host = os.environ.get("CEEFAXWEB_HOST", "127.0.0.1")
    port = int(os.environ.get("CEEFAXWEB_PORT", "8088"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()


