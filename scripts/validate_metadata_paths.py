#!/usr/bin/env python3
"""Validate SQLite/Qdrant chunk metadata and local asset paths."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_rag.validate.metadata_paths import validate_metadata_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-qdrant", action="store_true", help="Skip Qdrant payload checks")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if validation fails")
    parser.add_argument("--sample-missing", type=int, default=20)
    args = parser.parse_args()

    report = validate_metadata_paths(
        check_qdrant=not args.no_qdrant,
        sample_missing=args.sample_missing,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.strict and not report.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
