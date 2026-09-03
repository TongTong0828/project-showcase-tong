#!/usr/bin/env python3
"""Lightweight repository secret scan for release preflight.

This is intentionally conservative and dependency-free. It scans source,
config, docs, tests, and integration adapters for common API key shapes while
allowing documented placeholders.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PATHS = (
    ".github",
    "config",
    "docs",
    "examples",
    "integrations/deepseek-harness",
    "scripts",
    "src",
    "tests",
    ".env.example",
    "Makefile",
    "README.md",
    "pyproject.toml",
)

TEXT_EXTS = {
    "",
    ".css",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".tsx",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}

PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{40,}\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{32,}", re.IGNORECASE),
)

ALLOW_RE = re.compile(
    r"(placeholder|your[-_ ]?(?:key|token|secret)|test[-_ ]?(?:key|secret|token)|"
    r"sk-your-key-here|sk-secret-test-value|ABCDEFGHIJKLMNOPQRSTUVWXYZ|REDACTED|\$[A-Z0-9_]+)",
    re.IGNORECASE,
)


def iter_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = (ROOT / raw).resolve()
        if not path.exists():
            continue
        if path.is_file():
            files.append(path)
            continue
        for child in path.rglob("*"):
            if child.is_file() and child.suffix in TEXT_EXTS:
                files.append(child)
    return sorted(set(files))


def scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if ALLOW_RE.search(line):
            continue
        for pattern in PATTERNS:
            if pattern.search(line):
                hits.append((lineno, line.strip()))
                break
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS))
    args = parser.parse_args()

    findings: list[tuple[Path, int, str]] = []
    for path in iter_files(args.paths):
        rel = path.relative_to(ROOT)
        if any(part in {".git", ".venv", "node_modules", ".next", "data"} for part in rel.parts):
            continue
        for lineno, line in scan_file(path):
            findings.append((rel, lineno, line))

    if findings:
        print("Potential secrets found:")
        for rel, lineno, line in findings:
            print(f"  {rel}:{lineno}: {line[:180]}")
        return 1
    print("secret scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
