from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from paper_rag.store.sqlite_store import Chunk, Paper, Section


def _engine(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'paper-rag.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(engine) -> None:
    with Session(engine) as session:
        session.add(
            Paper(
                paper_id="arxiv:2310.11511",
                title="Self-RAG",
                arxiv_id="2310.11511",
                year=2023,
                abstract="Self-RAG abstract.",
                status="done",
                parsed_with="pymupdf",
            )
        )
        session.add(
            Section(
                section_id="sec-intro",
                paper_id="arxiv:2310.11511",
                idx=1,
                name="Introduction",
                page_start=1,
                page_end=2,
            )
        )
        session.add(
            Chunk(
                chunk_id="chunk-a",
                paper_id="arxiv:2310.11511",
                section_id="sec-intro",
                section="Introduction",
                section_idx=1,
                page=1,
                title="Self-RAG",
                text="SELF-RAG retrieves passages on demand.",
                context_text="SELF-RAG retrieves passages on demand.",
                source_path="/Users/at/private/papers/self-rag.pdf",
                asset_path="/Users/at/private/assets/page-1.png",
            )
        )
        session.add(
            Chunk(
                chunk_id="chunk-b",
                paper_id="arxiv:2310.11511",
                section_id="sec-intro",
                section="Introduction",
                section_idx=1,
                page=2,
                title="Self-RAG",
                text="<!-- page 2 --> SELF-RAG retrieves passages on demand. Preprint.",
                context_text="<!-- page 2 --> SELF-RAG retrieves passages on demand. Preprint.",
            )
        )
        session.commit()


def test_paper_detail_returns_sections_chunks_and_redacts_paths(tmp_path):
    from paper_rag.workbench.read_store import WorkbenchReadStore

    engine = _engine(tmp_path)
    _seed(engine)

    detail = WorkbenchReadStore(engine=engine).paper_detail("arxiv:2310.11511")

    assert detail is not None
    assert detail["paper"]["paper_id"] == "arxiv:2310.11511"
    assert detail["paper"]["title"] == "Self-RAG"
    assert detail["sections"] == [
        {
            "section_id": "sec-intro",
            "name": "Introduction",
            "idx": 1,
            "page_start": 1,
            "page_end": 2,
            "chunk_count": 2,
        }
    ]
    assert detail["chunks"][0]["chunk_id"] == "chunk-a"
    assert "source_path" not in str(detail)
    assert "asset_path" not in str(detail)
    assert "/Users/at/private" not in str(detail)


def test_chunk_detail_returns_neighbors_and_parser_warnings(tmp_path):
    from paper_rag.workbench.read_store import WorkbenchReadStore

    engine = _engine(tmp_path)
    _seed(engine)

    detail = WorkbenchReadStore(engine=engine).chunk_detail("chunk-b")

    assert detail is not None
    assert detail["chunk"]["chunk_id"] == "chunk-b"
    assert "html_comment" in detail["chunk"]["warnings"]
    assert "preprint_marker" in detail["chunk"]["warnings"]
    assert [chunk["chunk_id"] for chunk in detail["neighbors"]] == ["chunk-a"]


def test_corpus_quality_detects_duplicate_text_and_parser_artifacts(tmp_path):
    from paper_rag.workbench.read_store import WorkbenchReadStore

    engine = _engine(tmp_path)
    _seed(engine)

    quality = WorkbenchReadStore(engine=engine).corpus_quality()

    assert quality["paper_count"] == 1
    assert quality["chunk_count"] == 2
    assert quality["duplicate_chunk_count"] == 1
    assert quality["parser_artifact_count"] == 1
    assert quality["samples"][0]["kind"] in {"duplicate_chunk", "parser_artifact"}


@pytest.mark.parametrize("value", ["", "x" * 181, "../paper", "paper\nid"])
def test_validate_bounded_id_rejects_unsafe_values(value):
    from paper_rag.workbench.read_store import validate_bounded_id

    with pytest.raises(ValueError):
        validate_bounded_id(value, "paper_id")
