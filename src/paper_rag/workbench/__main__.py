from __future__ import annotations

import argparse

from .api import create_app
from .settings import WorkbenchSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Paper RAG Workbench API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3091)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        create_app(WorkbenchSettings.from_env()),
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
