"""File-backed cache for visual summaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schema import VisualSummaryRequest, VisualSummaryResult


class VisionSummaryCache:
    """JSON cache keyed by image bytes, context, model, and prompt version."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)

    def key_for(self, request: VisualSummaryRequest) -> str:
        h = hashlib.sha256()
        h.update(request.asset_path.read_bytes())
        for value in (
            request.paper_id,
            request.chunk_id,
            request.modality,
            request.caption,
            request.surrounding_context,
            request.model or "",
            request.prompt_version,
        ):
            h.update(b"\0")
            h.update(value.encode("utf-8", errors="replace"))
        return f"sha256:{h.hexdigest()}"

    def read(self, key: str) -> VisualSummaryResult | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return VisualSummaryResult(**payload)

    def write(self, key: str, result: VisualSummaryResult) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": result.status,
            "summary": result.summary,
            "provider": result.provider,
            "model": result.model,
            "raw": result.raw,
            "error": result.error,
            "cache_key": key,
            "warnings": result.warnings,
        }
        self._path_for(key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _path_for(self, key: str) -> Path:
        safe = key.replace(":", "_")
        return self.cache_dir / f"{safe}.json"
