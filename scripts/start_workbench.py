#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml


def build_launcher_env(repo: Path, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env["OPENAI_BASE_URL"] = "https://api.deepseek.com"
    env["CHAT_MODEL"] = "deepseek-v4-flash"
    env["SMALL_MODEL"] = "deepseek-v4-flash"
    env.setdefault(
        "PAPER_RAG_DSH_CREDENTIALS_PATH",
        str(repo / "data/runtime/deepseek-harness/credentials/.credentials.yaml"),
    )
    _load_dsh_credentials(env)
    return env


def _load_dsh_credentials(env: dict[str, str]) -> None:
    path = Path(env["PAPER_RAG_DSH_CREDENTIALS_PATH"])
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return
    deepseek_key = data.get("DEEPSEEK_API_KEY")
    openai_key = data.get("OPENAI_API_KEY")
    if isinstance(deepseek_key, str) and deepseek_key:
        env.setdefault("DEEPSEEK_API_KEY", deepseek_key)
    if isinstance(openai_key, str) and openai_key:
        env.setdefault("OPENAI_API_KEY", openai_key)
    elif isinstance(deepseek_key, str) and deepseek_key:
        env.setdefault("OPENAI_API_KEY", deepseek_key)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    env = build_launcher_env(repo)
    api = subprocess.Popen(
        [sys.executable, "-m", "paper_rag.workbench", "--host", "127.0.0.1", "--port", "3091"],
        cwd=repo,
        env={**env, "PYTHONPATH": str(repo / "src")},
    )
    ui = subprocess.Popen(
        ["pnpm", "--dir", "integrations/paper-rag-workbench", "dev"],
        cwd=repo,
        env=env,
    )
    print("paper rag workbench: http://127.0.0.1:3090", flush=True)
    try:
        return ui.wait()
    finally:
        for proc in (ui, api):
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)


if __name__ == "__main__":
    raise SystemExit(main())
