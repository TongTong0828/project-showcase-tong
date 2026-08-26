"""High-level build_chunks orchestrator.

Input: paper_id, parsed markdown path, title.
Output: (sections, chunks) ready to upsert into SQLite + Qdrant.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..utils.logger import get_logger
from . import multimodal_chunker as mm
from .contextual import with_context
from .section_splitter import split_sections
from .text_chunker import chunk_text

log = get_logger("chunk.builder")


def _chunk_id(paper_id: str, section_idx: int, kind: str, ord_: int) -> str:
    base = f"{paper_id}::{section_idx}::{kind}::{ord_}"
    return hashlib.sha1(base.encode()).hexdigest()[:20]


def _section_id(paper_id: str, idx: int) -> str:
    return hashlib.sha1(f"{paper_id}::sec::{idx}".encode()).hexdigest()[:16]


_PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")


def _page_for_offset(text: str, offset: int) -> int | None:
    page = None
    for m in _PAGE_RE.finditer(text):
        if m.start() > offset:
            break
        page = int(m.group(1))
    return page


def _resolve_asset_path(parsed_dir: Path, rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    p = Path(rel_path)
    if p.is_absolute():
        return str(p) if p.exists() else None
    candidate = (parsed_dir / p).resolve()
    return str(candidate) if candidate.exists() else None


def build_chunks(paper_id: str, parsed_dir: Path, *, title: str) -> tuple[list[dict], list[dict]]:
    md_path = parsed_dir / "paper.md"
    md = md_path.read_text(encoding="utf-8")
    source_path = str(md_path.resolve())

    sections: list[dict] = []
    chunks: list[dict] = []

    for raw_sec in split_sections(md):
        sec_id = _section_id(paper_id, raw_sec.idx)
        sections.append(
            {
                "section_id": sec_id,
                "paper_id": paper_id,
                "idx": raw_sec.idx,
                "name": raw_sec.name,
            }
        )

        for i, tc in enumerate(chunk_text(raw_sec.body)):
            ch_id = _chunk_id(paper_id, raw_sec.idx, "text", i)
            abs_start = raw_sec.start + tc.char_start
            abs_end = raw_sec.start + tc.char_end
            chunks.append(
                {
                    "chunk_id": ch_id,
                    "paper_id": paper_id,
                    "section_id": sec_id,
                    "section": raw_sec.name,
                    "section_idx": raw_sec.idx,
                    "modality": "text",
                    "page": _page_for_offset(md, abs_start),
                    "text": tc.text,
                    "context_text": with_context(tc.text, title=title, section=raw_sec.name),
                    "title": title,
                    "source_path": source_path,
                    "char_start": abs_start,
                    "char_end": abs_end,
                    "metadata": {
                        "section_level": raw_sec.level,
                        "chunk_ordinal": i,
                    },
                    "neighbors": [],
                }
            )

        for kind, items in (
            ("figure", mm.extract_figures(raw_sec.body)),
            ("table", mm.extract_tables(raw_sec.body)),
            ("formula", mm.extract_formulas(raw_sec.body)),
        ):
            for j, mmc in enumerate(items):
                ch_id = _chunk_id(paper_id, raw_sec.idx, kind, j)
                abs_start = raw_sec.start + mmc.char_start
                abs_end = raw_sec.start + mmc.char_end
                chunks.append(
                    {
                        "chunk_id": ch_id,
                        "paper_id": paper_id,
                        "section_id": sec_id,
                        "section": raw_sec.name,
                        "section_idx": raw_sec.idx,
                        "modality": mmc.modality,
                        "page": _page_for_offset(md, abs_start),
                        "text": mmc.text,
                        "context_text": with_context(mmc.text, title=title, section=raw_sec.name),
                        "title": title,
                        "source_path": source_path,
                        "asset_rel_path": mmc.asset_rel_path,
                        "asset_path": _resolve_asset_path(parsed_dir, mmc.asset_rel_path),
                        "char_start": abs_start,
                        "char_end": abs_end,
                        "raw_snippet": mmc.raw,
                        "metadata": {
                            "section_level": raw_sec.level,
                            "chunk_ordinal": j,
                            "element_type": mmc.modality,
                        },
                        "neighbors": [],
                    }
                )

    try:
        from paper_rag.vision.enrich import enrich_chunks

        chunks = enrich_chunks(paper_id, chunks)
    except Exception as exc:
        log.warning(f"visual enrichment skipped for {paper_id}: {exc}")

    log.info(f"built {len(sections)} sections, {len(chunks)} chunks for {paper_id}")
    return sections, chunks
