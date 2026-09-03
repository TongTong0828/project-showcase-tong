"""Artifact file helpers for MCP deliverable tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def write_artifact(
    artifact_root: Path,
    *,
    tool: str,
    filename: str,
    content_bytes: bytes,
    content_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = artifact_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    artifact_id = str(uuid4())
    artifact_dir = (root / artifact_id).resolve()
    _ensure_under(artifact_dir, root)
    artifact_dir.mkdir(parents=False)

    safe_name = sanitize_filename(filename)
    final_path = (artifact_dir / safe_name).resolve()
    _ensure_under(final_path, artifact_dir)
    _atomic_write_bytes(final_path, content_bytes)
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    manifest = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "tool": tool,
        "created_at": time.time(),
        "files": [
            {
                "filename": safe_name,
                "path": str(final_path),
                "content_type": content_type,
                "size_bytes": len(content_bytes),
                "sha256": sha256,
            }
        ],
        "metadata": metadata or {},
    }
    manifest_path = artifact_dir / "manifest.json"
    _atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return {
        "artifact_id": artifact_id,
        "path": str(artifact_dir),
        "manifest_path": str(manifest_path),
        "files": manifest["files"],
    }


def cleanup_artifacts(
    artifact_root: Path,
    *,
    older_than_days: int = 30,
    protected_roots: list[Path] | None = None,
) -> dict[str, list[str]]:
    root = artifact_root.resolve()
    protected = [path.resolve() for path in protected_roots or []]
    if any(_is_relative_to(root, item) or root == item for item in protected):
        raise ValueError("artifact root overlaps a protected root")
    if not root.exists():
        return {"deleted": [], "kept": []}

    cutoff = time.time() - older_than_days * 24 * 3600
    deleted: list[str] = []
    kept: list[str] = []
    for child in sorted(root.iterdir()):
        resolved = child.resolve()
        if not child.is_dir() or not (child / "manifest.json").exists():
            kept.append(str(resolved))
            continue
        _ensure_under(resolved, root)
        if child.stat().st_mtime < cutoff:
            shutil.rmtree(resolved)
            deleted.append(str(resolved))
        else:
            kept.append(str(resolved))
    return {"deleted": deleted, "kept": kept}


def sanitize_filename(filename: str) -> str:
    name = Path(filename.replace("\x00", "")).name
    name = _SAFE_FILENAME_RE.sub("_", name).strip("._")
    return name or "artifact.bin"


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_write_text(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def _ensure_under(path: Path, root: Path) -> None:
    if not _is_relative_to(path, root):
        raise ValueError(f"path escapes artifact root: {path}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
