#!/usr/bin/env python3
"""Download the enabled MinerU layout model into the project model directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_rag.parse import mineru_local  # noqa: E402

DEFAULT_URL = (
    "https://github.com/doclayout_yolo/assets/releases/download/v8.1.0/"
    "doclayout_yolo_docstructbench_imgsz1280_2501.pt"
)
DEFAULT_OUT = (
    ROOT
    / "data"
    / "index"
    / "mineru_models"
    / "Layout"
    / "YOLO"
    / "doclayout_yolo_docstructbench_imgsz1280_2501.pt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mineru_local._ensure_runtime_env()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from doclayout_yolo.utils.downloads import safe_download

        safe_download(url=args.url, file=args.out, min_bytes=100_000, progress=True)
    except Exception as exc:
        reason, hint = mineru_local.classify_failure(str(exc))
        print(f"download failed ({reason}): {exc}", file=sys.stderr)
        if hint:
            print(f"hint: {hint}", file=sys.stderr)
        return 1

    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
