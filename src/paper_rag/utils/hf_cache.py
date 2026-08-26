"""Helpers for resolving HuggingFace snapshots from a local cache."""

from __future__ import annotations

from pathlib import Path


def resolve_cached_snapshot(model_name: str, cache_dir: str | Path) -> str:
    """Return a local snapshot path when available, otherwise ``model_name``.

    Passing the snapshot path avoids opportunistic network calls from
    transformers/huggingface_hub in offline demo and test environments.
    """
    p = Path(model_name)
    if p.exists():
        return str(p)
    if "/" not in model_name:
        return model_name

    repo_dir = Path(cache_dir) / f"models--{model_name.replace('/', '--')}"
    refs_main = repo_dir / "refs" / "main"
    if refs_main.exists():
        snapshot = repo_dir / "snapshots" / refs_main.read_text(encoding="utf-8").strip()
        if snapshot.exists():
            return str(snapshot)

    snapshots = repo_dir / "snapshots"
    if snapshots.exists():
        for snapshot in sorted(snapshots.iterdir()):
            if snapshot.is_dir() and (snapshot / "config.json").exists():
                return str(snapshot)
    return model_name
