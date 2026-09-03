from __future__ import annotations


def test_resolve_wiki_context_matches_alias(monkeypatch):
    from paper_rag.wiki import context
    from paper_rag.wiki.schema import WikiEntry

    entry = WikiEntry(
        entry_id="concept:contrastivelearning",
        name="Contrastive Learning",
        aliases=["对比学习", "CL"],
        definition="Learns representations by pulling positives together [chunk:c1].",
        key_papers=["paper-1"],
        evidence_chunks=["c1"],
        version=3,
    )
    monkeypatch.setattr(context.wstore, "list_all", lambda: [entry])

    out = context.resolve_wiki_context("对比学习怎么评估?", paper_ids=None)

    assert out["role"] == "background_not_evidence"
    assert out["fingerprint"] == "concept:contrastivelearning:3"
    assert out["entries"][0]["entry_id"] == "concept:contrastivelearning"
    assert out["entries"][0]["aliases"] == ["对比学习", "CL"]
    assert out["entries"][0]["evidence_chunks"] == ["c1"]


def test_resolve_wiki_context_uses_paper_overlap_when_question_is_generic(monkeypatch):
    from paper_rag.wiki import context
    from paper_rag.wiki.schema import WikiEntry

    entry = WikiEntry(
        entry_id="concept:rag",
        name="RAG",
        definition="Retrieval augmented generation.",
        key_papers=["paper-2"],
        version=1,
    )
    monkeypatch.setattr(context.wstore, "list_all", lambda: [entry])

    out = context.resolve_wiki_context("What does this paper evaluate?", paper_ids=["paper-2"])

    assert [e["entry_id"] for e in out["entries"]] == ["concept:rag"]
    assert out["fingerprint"] == "concept:rag:1"


def test_format_wiki_background_marks_not_evidence():
    from paper_rag.wiki.context import format_wiki_background

    block = format_wiki_background({
        "role": "background_not_evidence",
        "entries": [{
            "name": "RAG",
            "definition": "Retrieval augmented generation.",
            "aliases": ["Retrieval-Augmented Generation"],
            "key_papers": ["paper-1"],
            "version": 2,
        }],
    })

    assert "Wiki background (not evidence)" in block
    assert "Do not cite this background" in block
    assert "RAG" in block


def test_wiki_rewrite_hints_compacts_aliases_and_definition_terms():
    from paper_rag.wiki.context import wiki_rewrite_hints

    hints = wiki_rewrite_hints({
        "entries": [{
            "name": "Contrastive Learning",
            "aliases": ["CL", "对比学习"],
            "definition": "Learns representations from positive and negative pairs.",
            "key_papers": ["paper-1"],
        }]
    })

    assert "Contrastive Learning" in hints["dense_queries"]
    assert "CL" in hints["dense_queries"]
    assert "positive negative pairs" in hints["dense_queries"]
    assert "contrastive learning" in hints["bm25_query"]
