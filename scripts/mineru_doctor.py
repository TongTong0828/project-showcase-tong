#!/usr/bin/env python3
"""Diagnose local MinerU/magic-pdf readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_rag.parse import mineru_local  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--try-parse", metavar="PDF", help="Run MinerU against one PDF")
    parser.add_argument("--paper-id", default="mineru:doctor", help="Paper id for --try-parse output")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = mineru_local.diagnose()
    payload = report.to_dict()

    if args.try_parse:
        try:
            out = mineru_local.parse_pdf(args.paper_id, args.try_parse)
            payload["try_parse"] = {"ok": True, "out_dir": str(out)}
        except mineru_local.MineruError as exc:
            reason, hint = mineru_local.classify_failure(str(exc))
            payload["try_parse"] = {
                "ok": False,
                "reason": reason,
                "error": str(exc),
                "hint": hint,
            }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)

    ok = bool(payload.get("ok"))
    if payload.get("try_parse"):
        ok = ok and bool(payload["try_parse"]["ok"])
    return 1 if args.strict and not ok else 0


def _print_human(payload: dict) -> None:
    print("MinerU doctor")
    print(f"  ok: {payload['ok']}")
    print(f"  cli: {payload.get('cli_path')}")
    print(f"  config: {payload.get('config_path')}")
    print("\nChecks:")
    for check in payload["checks"]:
        mark = "OK" if check["ok"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}")
        if not check["ok"] and check.get("hint"):
            print(f"        hint: {check['hint']}")
    if payload.get("try_parse"):
        trial = payload["try_parse"]
        print("\nTry parse:")
        print(f"  ok: {trial['ok']}")
        if trial["ok"]:
            print(f"  out_dir: {trial['out_dir']}")
        else:
            print(f"  reason: {trial['reason']}")
            if trial.get("hint"):
                print(f"  hint: {trial['hint']}")


if __name__ == "__main__":
    raise SystemExit(main())
