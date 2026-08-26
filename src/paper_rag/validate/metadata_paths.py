"""Validate chunk metadata and local asset paths.

The RAG index stores local parse artifacts in two places:

- SQLite keeps the canonical chunk rows, including source/asset paths.
- Qdrant keeps the same fields in each point payload for filtered recall.

This module checks that those two stores stay aligned and that local paths in
chunk metadata still point at files on disk.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from .. import config as cfg
from ..store import qdrant_store, sqlite_store


@dataclass
class MetadataPathReport:
    sqlite_chunks: int = 0
    qdrant_chunks: int | None = None
    modalities: dict[str, int] = field(default_factory=dict)
    parsed_with: dict[str, int] = field(default_factory=dict)
    chunks_with_source_path: int = 0
    chunks_with_asset_path: int = 0
    chunks_with_asset_rel_path: int = 0
    missing_source_paths: list[str] = field(default_factory=list)
    missing_asset_paths: list[str] = field(default_factory=list)
    qdrant_error: str | None = None
    qdrant_missing_payload_keys: dict[str, int] = field(default_factory=dict)
    qdrant_modalities: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        qdrant_aligned = self.qdrant_chunks is None or self.qdrant_chunks == self.sqlite_chunks
        return (
            qdrant_aligned
            and not self.missing_source_paths
            and not self.missing_asset_paths
            and not self.qdrant_error
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["ok"] = self.ok
        return out


def validate_metadata_paths(*, check_qdrant: bool = True, sample_missing: int = 20) -> MetadataPathReport:
    """Validate indexed chunk metadata and local paths.

    ``sample_missing`` bounds returned path examples so the report stays small
    even on large corpora.
    """
    report = MetadataPathReport()
    _validate_sqlite(report, sample_missing=sample_missing)
    if check_qdrant:
        _validate_qdrant(report)
    return report


def _validate_sqlite(report: MetadataPathReport, *, sample_missing: int) -> None:
    engine = sqlite_store.get_engine()
    modalities: Counter[str] = Counter()
    parsed_with: Counter[str] = Counter()

    with Session(engine) as session:
        papers = list(session.exec(select(sqlite_store.Paper)))
        for paper in papers:
            parsed_with[paper.parsed_with or "unknown"] += 1

        chunks = list(session.exec(select(sqlite_store.Chunk)))
        report.sqlite_chunks = len(chunks)
        for chunk in chunks:
            modalities[chunk.modality or "unknown"] += 1

            if chunk.source_path:
                report.chunks_with_source_path += 1
                if not Path(chunk.source_path).exists() and len(report.missing_source_paths) < sample_missing:
                    report.missing_source_paths.append(f"{chunk.chunk_id}: {chunk.source_path}")

            if chunk.asset_rel_path:
                report.chunks_with_asset_rel_path += 1

            if chunk.asset_path:
                report.chunks_with_asset_path += 1
                if not Path(chunk.asset_path).exists() and len(report.missing_asset_paths) < sample_missing:
                    report.missing_asset_paths.append(f"{chunk.chunk_id}: {chunk.asset_path}")
            elif chunk.asset_rel_path and len(report.missing_asset_paths) < sample_missing:
                report.missing_asset_paths.append(f"{chunk.chunk_id}: unresolved {chunk.asset_rel_path}")

    report.modalities = dict(sorted(modalities.items()))
    report.parsed_with = dict(sorted(parsed_with.items()))


def _validate_qdrant(report: MetadataPathReport) -> None:
    try:
        client = qdrant_store.get_client()
        coll = cfg.load().qdrant.collection_chunks
        points, next_page = client.scroll(
            collection_name=coll,
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )
        all_points = list(points)
        while next_page is not None:
            points, next_page = client.scroll(
                collection_name=coll,
                limit=1000,
                offset=next_page,
                with_payload=True,
                with_vectors=False,
            )
            all_points.extend(points)
    except Exception as exc:
        report.qdrant_error = f"{type(exc).__name__}: {exc}"
        return
    finally:
        qdrant_store.close_client()

    missing_keys: Counter[str] = Counter()
    modalities: Counter[str] = Counter()
    required = ("chunk_id", "paper_id", "modality", "text")
    for point in all_points:
        payload = dict(point.payload or {})
        for key in required:
            if key not in payload:
                missing_keys[key] += 1
        modalities[payload.get("modality") or "unknown"] += 1

    report.qdrant_chunks = len(all_points)
    report.qdrant_missing_payload_keys = dict(sorted(missing_keys.items()))
    report.qdrant_modalities = dict(sorted(modalities.items()))


__all__ = ["MetadataPathReport", "validate_metadata_paths"]
