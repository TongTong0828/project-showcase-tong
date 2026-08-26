#!/usr/bin/env python3
"""Smoke-check the embedded DeerFlow paper_rag gateway endpoints."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_TIMEOUT_SECONDS = 120.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: int | None
    detail: str


def _request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def _summarize_body(body: str, limit: int = 180) -> str:
    compact = " ".join(body.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _parse_json(body: str) -> dict[str, Any]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _qa_validator(require_llm_answer: bool) -> Callable[[int, str], tuple[bool, str]]:
    def _validate(status: int, body: str) -> tuple[bool, str]:
        if not 200 <= status < 300:
            return False, _summarize_body(body)
        payload = _parse_json(body)
        answer = str(payload.get("answer") or "")
        n_chunks = payload.get("n_chunks")
        evidence_only = answer.startswith("(LLM unavailable")
        mode = "evidence-only" if evidence_only else "llm-answer"
        detail = f"{mode}; chunks={n_chunks}; answer={_summarize_body(answer)}"
        if require_llm_answer and evidence_only:
            return False, detail
        return True, detail

    return _validate


def _status_validator(status: int, body: str) -> tuple[bool, str]:
    if not 200 <= status < 300:
        return False, _summarize_body(body)
    payload = _parse_json(body)
    mode = "evidence-only" if payload.get("evidence_only") else "llm-ready"
    embedding = "embed-ok" if payload.get("embedding_available") else "embed-missing"
    qdrant = "qdrant-ok" if payload.get("qdrant_available") else "qdrant-missing"
    points = payload.get("qdrant_points")
    warnings = payload.get("warnings") or []
    warning_text = f"; warnings={len(warnings)}" if warnings else ""
    return True, f"{mode}; {embedding}; {qdrant}; vectors={points}{warning_text}"


def _check(
    base_url: str,
    name: str,
    method: str,
    path: str,
    payload=None,
    validator: Callable[[int, str], tuple[bool, str]] | None = None,
) -> CheckResult:
    try:
        status, body = _request(base_url, method, path, payload)
    except Exception as exc:
        return CheckResult(name, False, None, str(exc))
    if validator:
        ok, detail = validator(status, body)
        return CheckResult(name, ok, status, detail)
    return CheckResult(name, 200 <= status < 300, status, _summarize_body(body))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--qa-question", help="Also exercise /api/paper_rag/qa/sync.")
    parser.add_argument(
        "--require-llm-answer",
        action="store_true",
        help="Fail QA when the gateway returns evidence-only fallback instead of a real LLM answer.",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    global _TIMEOUT_SECONDS
    _TIMEOUT_SECONDS = args.timeout

    checks = [
        ("health", "GET", "/health", None),
        ("metrics", "GET", "/metrics", None),
        ("runtime_status", "GET", "/api/paper_rag/status", None, _status_validator),
        ("papers", "GET", "/api/paper_rag/papers", None),
        ("inbox", "GET", "/api/paper_rag/inbox?unread_only=false&limit=10", None),
        ("subscriptions", "GET", "/api/paper_rag/subscriptions", None),
    ]
    if args.qa_question:
        checks.append(
            (
                "qa_sync",
                "POST",
                "/api/paper_rag/qa/sync",
                {"question": args.qa_question},
                _qa_validator(args.require_llm_answer),
            )
        )

    results = [_check(args.base_url, *check) for check in checks]
    for result in results:
        marker = "ok" if result.ok else "FAIL"
        status = "-" if result.status is None else str(result.status)
        print(f"{marker:4} {status:>3} {result.name}: {result.detail}")

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
