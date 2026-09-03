#!/usr/bin/env python3
"""Rebuild chunks, embeddings, SQLite rows, and Qdrant points from parsed files.

This is useful after changing chunking/metadata logic when PDFs have already
been downloaded and parsed under ``data/parsed``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_rag.chunk.builder import build_chunks  # noqa: E402
from paper_rag.embed import bge_m3  # noqa: E402
from paper_rag.store import qdrant_store, sqlite_store  # noqa: E402
from paper_rag.store.ingest_pipeline import (  # noqa: E402
    _paper_metadata_chunk,
    _replace_qdrant_chunks,
)
from paper_rag.utils.paths import parsed_dir  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", action="append", help="Rebuild one or more paper ids")
    parser.add_argument("--skip-qdrant", action="store_true", help="Only update SQLite chunks")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = sqlite_store.get_engine()
    with Session(engine) as session:
        stmt = select(sqlite_store.Paper)
        if args.paper_id:
            stmt = stmt.where(sqlite_store.Paper.paper_id.in_(args.paper_id))
        papers = list(session.exec(stmt))

    rebuilt = 0
    for paper in papers:
        pdir = parsed_dir(paper.paper_id)
        if not (pdir / "paper.md").exists():
            print(f"skip missing parsed: {paper.paper_id} ({pdir})")
            continue

        meta = SimpleNamespace(
            paper_id=paper.paper_id,
            title=paper.title,
            authors=json.loads(paper.authors_json or "[]"),
            year=paper.year,
            venue=paper.venue,
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
            abstract=paper.abstract,
            source="arxiv" if paper.arxiv_id else "local",
        )
        sections, chunks = build_chunks(paper.paper_id, pdir, title=paper.title or paper.paper_id)
        chunks.insert(0, _paper_metadata_chunk(meta))
        sqlite_store.upsert_sections_and_chunks(paper.paper_id, sections, chunks)

        if not args.skip_qdrant:
            vectors = bge_m3.encode([chunk["context_text"] for chunk in chunks])
            _replace_qdrant_chunks(paper.paper_id, chunks, vectors)

        rebuilt += 1
        print(f"{paper.paper_id}: sections={len(sections)} chunks={len(chunks)}")

    qdrant_store.close_client()
    print(f"rebuilt={rebuilt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
