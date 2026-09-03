from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from paper_rag.store.sqlite_store import Chunk, Paper, Section, get_engine

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SPACE_RE = re.compile(r"\s+")


def validate_bounded_id(value: str, field_name: str, *, max_length: int = 180) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError(f"{field_name} is required")
    if len(candidate) > max_length:
        raise ValueError(f"{field_name} is too long")
    if any(token in candidate for token in ("..", "/", "\\", "\n", "\r", "\x00")):
        raise ValueError(f"{field_name} contains unsupported characters")
    return candidate


def redact_local_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if path.name:
        return f"[redacted]/{path.name}"
    return "[redacted]"


def parser_warnings_for_text(text: str) -> list[str]:
    warnings: list[str] = []
    if _HTML_COMMENT_RE.search(text):
        warnings.append("html_comment")
    if "Preprint." in text:
        warnings.append("preprint_marker")
    return warnings


def _normalized_text(text: str) -> str:
    without_comments = _HTML_COMMENT_RE.sub(" ", text or "")
    without_preprint = without_comments.replace("Preprint.", " ")
    return _SPACE_RE.sub(" ", without_preprint).strip().lower()


def _chunk_summary(chunk: Chunk) -> dict[str, Any]:
    text = chunk.text or chunk.context_text or ""
    return {
        "chunk_id": chunk.chunk_id,
        "paper_id": chunk.paper_id,
        "title": chunk.title,
        "section_id": chunk.section_id,
        "section": chunk.section,
        "section_idx": chunk.section_idx,
        "page": chunk.page,
        "modality": chunk.modality,
        "text": chunk.text,
        "snippet": text[:500],
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "warnings": parser_warnings_for_text(text),
    }


class WorkbenchReadStore:
    def __init__(self, *, engine: Any | None = None) -> None:
        self._engine = engine

    @property
    def engine(self):
        return self._engine or get_engine()

    def paper_detail(self, paper_id: str) -> dict[str, Any] | None:
        safe_id = validate_bounded_id(paper_id, "paper_id")
        with Session(self.engine) as session:
            paper = session.get(Paper, safe_id)
            if paper is None:
                return None
            sections = list(
                session.exec(
                    select(Section)
                    .where(Section.paper_id == safe_id)
                    .order_by(Section.idx)
                )
            )
            chunks = list(
                session.exec(
                    select(Chunk)
                    .where(Chunk.paper_id == safe_id)
                    .order_by(Chunk.section_idx, Chunk.page, Chunk.chunk_id)
                )
            )

        counts = Counter(chunk.section_id for chunk in chunks)
        return {
            "paper": {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "arxiv_id": paper.arxiv_id,
                "year": paper.year,
                "venue": paper.venue,
                "doi": paper.doi,
                "abstract": paper.abstract,
                "status": paper.status,
                "parsed_with": paper.parsed_with,
                "chunk_count": len(chunks),
                "updated_at": paper.updated_at.isoformat(),
            },
            "sections": [
                {
                    "section_id": section.section_id,
                    "name": section.name,
                    "idx": section.idx,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                    "chunk_count": counts.get(section.section_id, 0),
                }
                for section in sections
            ],
            "chunks": [_chunk_summary(chunk) for chunk in chunks],
            "warnings": _paper_warnings(sections, chunks),
        }

    def chunk_detail(
        self,
        chunk_id: str,
        *,
        neighbor_limit: int = 2,
    ) -> dict[str, Any] | None:
        safe_id = validate_bounded_id(chunk_id, "chunk_id")
        with Session(self.engine) as session:
            chunk = session.get(Chunk, safe_id)
            if chunk is None:
                return None
            paper = session.get(Paper, chunk.paper_id)
            peers = list(
                session.exec(
                    select(Chunk)
                    .where(Chunk.paper_id == chunk.paper_id)
                    .order_by(Chunk.section_idx, Chunk.page, Chunk.chunk_id)
                )
            )

        index = next(
            (idx for idx, peer in enumerate(peers) if peer.chunk_id == safe_id),
            -1,
        )
        start = max(0, index - neighbor_limit)
        end = min(len(peers), index + neighbor_limit + 1)
        neighbors = [peer for peer in peers[start:end] if peer.chunk_id != safe_id]
        return {
            "chunk": _chunk_summary(chunk),
            "paper": {
                "paper_id": paper.paper_id if paper else chunk.paper_id,
                "title": paper.title if paper else chunk.title,
                "arxiv_id": paper.arxiv_id if paper else None,
                "year": paper.year if paper else None,
            },
            "neighbors": [_chunk_summary(peer) for peer in neighbors],
        }

    def corpus_quality(self, limit: int = 8) -> dict[str, Any]:
        with Session(self.engine) as session:
            papers = list(session.exec(select(Paper)))
            chunks = list(session.exec(select(Chunk)))

        normalized_to_chunks: dict[str, list[Chunk]] = defaultdict(list)
        parser_samples: list[dict[str, Any]] = []
        parser_artifact_count = 0
        for chunk in chunks:
            text = chunk.text or chunk.context_text or ""
            normalized = _normalized_text(text)
            if normalized:
                normalized_to_chunks[normalized].append(chunk)
            warnings = parser_warnings_for_text(text)
            if warnings:
                parser_artifact_count += 1
                if len(parser_samples) < limit:
                    parser_samples.append(
                        {
                            "kind": "parser_artifact",
                            "paper_id": chunk.paper_id,
                            "chunk_id": chunk.chunk_id,
                            "warnings": warnings,
                            "preview": text[:180],
                        }
                    )

        duplicate_groups = [
            items for items in normalized_to_chunks.values() if len(items) > 1
        ]
        duplicate_samples = [
            {
                "kind": "duplicate_chunk",
                "paper_id": group[0].paper_id,
                "chunk_ids": [chunk.chunk_id for chunk in group[:4]],
                "preview": (group[0].text or group[0].context_text or "")[:180],
            }
            for group in duplicate_groups[:limit]
        ]
        missing_section_count = sum(
            1
            for paper in papers
            if not any(
                chunk.paper_id == paper.paper_id
                and (chunk.section or "").strip().lower()
                in {"abstract", "introduction"}
                for chunk in chunks
            )
        )
        return {
            "paper_count": len(papers),
            "chunk_count": len(chunks),
            "duplicate_chunk_count": sum(len(group) - 1 for group in duplicate_groups),
            "parser_artifact_count": parser_artifact_count,
            "missing_section_count": missing_section_count,
            "samples": (duplicate_samples + parser_samples)[:limit],
        }


def _paper_warnings(sections: list[Section], chunks: list[Chunk]) -> list[str]:
    warnings: list[str] = []
    if not sections:
        warnings.append("section_metadata_missing")
    if not any((chunk.section or "").strip().lower() == "abstract" for chunk in chunks):
        warnings.append("abstract_section_missing")
    if not any(
        (chunk.section or "").strip().lower() == "introduction" for chunk in chunks
    ):
        warnings.append("introduction_section_missing")
    if any(
        parser_warnings_for_text(chunk.text or chunk.context_text or "")
        for chunk in chunks
    ):
        warnings.append("parser_artifacts_detected")
    return warnings
