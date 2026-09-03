"""Pure-Python unit tests (no Qdrant / LLM needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_split_sections_basic():
    from paper_rag.chunk.section_splitter import split_sections

    md = "# Intro\nhello\n\n## Sub\nworld\n\n# Method\nbody"
    secs = split_sections(md)
    assert [s.name for s in secs] == ["Intro", "Sub", "Method"]
    assert "hello" in secs[0].body
    assert "world" in secs[1].body


def test_split_sections_no_header():
    from paper_rag.chunk.section_splitter import split_sections

    secs = split_sections("just a paragraph without headers")
    assert len(secs) == 1 and secs[0].name == "Body"


def test_split_sections_plain_academic_headings():
    from paper_rag.chunk.section_splitter import split_sections

    md = (
        "<!-- page 1 -->\n\n"
        "Paper Title\n"
        "Abstract—This paper introduces the idea.\n"
        "1\n"
        "Introduction\n"
        "Intro body.\n\n"
        "2\n"
        "RELATED WORK\n"
        "Prior work body.\n\n"
        "3.1\n"
        "TRAINING THE GENERATOR MODEL\n"
        "Method body.\n\n"
        "4\n"
        "EXPERIMENTS\n"
        "Experiment body.\n\n"
        "References\n"
        "[1] Someone.\n"
        "# Location\n"
        "This should stay in references.\n"
    )
    secs = split_sections(md)
    names = [s.name for s in secs]

    assert names == [
        "Abstract",
        "Introduction",
        "RELATED WORK",
        "TRAINING THE GENERATOR MODEL",
        "EXPERIMENTS",
        "References",
    ]
    assert secs[0].body.startswith("This paper introduces")
    assert "# Location" in secs[-1].body


def test_multimodal_extract():
    from paper_rag.chunk.multimodal_chunker import (
        extract_figures,
        extract_formulas,
        extract_tables,
    )

    md = (
        "Some text.\n\n"
        "![alt](figures/a.png)\n\n"
        "more text\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "$$E = mc^2$$\n"
    )
    figs = extract_figures(md)
    tabs = extract_tables(md)
    forms = extract_formulas(md)
    assert len(figs) == 1 and figs[0].modality == "figure"
    assert figs[0].asset_rel_path == "figures/a.png"
    assert len(tabs) == 1 and tabs[0].modality == "table"
    assert len(forms) == 1 and "E = mc^2" in forms[0].text


def test_multimodal_rejects_one_cell_table_artifact():
    from paper_rag.chunk.multimodal_chunker import extract_tables

    md = "Recall is defined as:\n\n|Q|\n|Q|\n\nwhere Q is the query set."
    assert extract_tables(md) == []


def test_chunk_text_token_budget():
    from paper_rag.chunk.text_chunker import chunk_text

    body = ("This is a paragraph. " * 50 + "\n\n") * 5
    chunks = chunk_text(body)
    assert len(chunks) >= 2
    for ch in chunks:
        assert ch.text


def test_citation_check_drops_invalid():
    from paper_rag.rag.citation_check import validate_citations

    retrieved = [{"chunk_id": "abc123def456"}, {"chunk_id": "0011223344"}]
    raw = "Statement one [chunk:abc123def456]. Again [chunk:abc123def456]. Bad [chunk:ffffffff]."
    cleaned, valid = validate_citations(raw, retrieved)
    assert "abc123def456" in cleaned
    assert "ffffffff" not in cleaned
    assert valid == ["abc123def456"]


def test_build_chunks_smoke(tmp_path: Path):
    from paper_rag.chunk.builder import build_chunks

    md = "# Abstract\nshort abstract paragraph.\n\n# Method\nWe propose foo. We compare bar.\n\n$$y = wx + b$$\n"
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    (parsed / "paper.md").write_text(md, encoding="utf-8")
    sections, chunks = build_chunks("sha1:deadbeef", parsed, title="Sample Paper")
    assert len(sections) >= 2
    assert any(c["modality"] == "formula" for c in chunks)
    assert all(c["paper_id"] == "sha1:deadbeef" for c in chunks)


def test_build_chunks_preserves_local_asset_metadata(tmp_path: Path):
    from paper_rag.chunk.builder import build_chunks

    parsed = tmp_path / "parsed"
    figures = parsed / "figures"
    figures.mkdir(parents=True)
    (figures / "a.png").write_bytes(b"fake")
    md = (
        "<!-- page 3 -->\n"
        "# Method\n"
        "We derive the equation below.\n\n"
        "![pipeline](figures/a.png)\n\n"
        "$$y = wx + b$$\n"
    )
    (parsed / "paper.md").write_text(md, encoding="utf-8")

    _, chunks = build_chunks("sha1:deadbeef", parsed, title="Sample Paper")
    fig = next(c for c in chunks if c["modality"] == "figure")
    formula = next(c for c in chunks if c["modality"] == "formula")

    assert fig["asset_rel_path"] == "figures/a.png"
    assert fig["asset_path"].endswith("figures/a.png")
    assert fig["source_path"].endswith("paper.md")
    assert fig["page"] == 3
    assert fig["metadata"]["element_type"] == "figure"
    assert formula["raw_snippet"] == "$$y = wx + b$$"
    assert formula["char_start"] < formula["char_end"]


def test_build_chunks_calls_visual_enrichment(tmp_path: Path, monkeypatch):
    from paper_rag.chunk import builder

    parsed = tmp_path / "parsed"
    figures = parsed / "figures"
    figures.mkdir(parents=True)
    (figures / "a.png").write_bytes(b"fake")
    (parsed / "paper.md").write_text(
        "# Method\n![pipeline](figures/a.png)\n",
        encoding="utf-8",
    )

    def fake_enrich(paper_id, chunks):
        assert paper_id == "sha1:deadbeef"
        for chunk in chunks:
            if chunk.get("modality") == "figure":
                chunk["text"] += "\nVisual summary: mocked"
                chunk["context_text"] += "\nVisual summary: mocked"
                chunk.setdefault("metadata", {})["visual_summary_status"] = "ok"
        return chunks

    monkeypatch.setattr("paper_rag.vision.enrich.enrich_chunks", fake_enrich)

    _, chunks = builder.build_chunks("sha1:deadbeef", parsed, title="Sample Paper")
    fig = next(c for c in chunks if c["modality"] == "figure")

    assert "Visual summary: mocked" in fig["text"]
    assert fig["metadata"]["visual_summary_status"] == "ok"


def test_metadata_path_report_ok_property():
    from paper_rag.validate.metadata_paths import MetadataPathReport

    report = MetadataPathReport(sqlite_chunks=2, qdrant_chunks=2)
    assert report.ok

    report.missing_asset_paths.append("chunk: missing.png")
    assert not report.ok

    payload = report.to_dict()
    assert payload["ok"] is False
    assert payload["sqlite_chunks"] == 2
