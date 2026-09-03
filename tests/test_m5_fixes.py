"""Tests for the new P0 fixes (M5)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_suspicious_citations_numeric():
    from paper_rag.rag.citation_check import detect_suspicious_citations

    rep = detect_suspicious_citations(
        "Foo bar [1]. Other thing [chunk:abcd1234]. More [12] stuff."
    )
    assert rep["count"] == 2
    assert "[1]" in rep["numeric"]
    assert "[12]" in rep["numeric"]


def test_suspicious_citations_author_year():
    from paper_rag.rag.citation_check import detect_suspicious_citations

    rep = detect_suspicious_citations(
        "Transformers (Vaswani et al., 2017) outperform RNNs (Bahdanau 2015)."
    )
    assert rep["count"] == 2
    assert any("2017" in s for s in rep["author_year"])
    assert any("2015" in s for s in rep["author_year"])


def test_suspicious_citations_clean():
    from paper_rag.rag.citation_check import detect_suspicious_citations

    rep = detect_suspicious_citations(
        "All claims cite [chunk:abc123] and [chunk:def456]."
    )
    assert rep["count"] == 0


def test_validate_citations_drops_unknown():
    from paper_rag.rag.citation_check import validate_citations

    retrieved = [{"chunk_id": "a1b2c3d4"}, {"chunk_id": "deadbeef"}]
    raw = "S1 [chunk:a1b2c3d4]. S2 [chunk:ffffffff]. S3 [chunk:deadbeef]."
    cleaned, valid = validate_citations(raw, retrieved)
    assert "a1b2c3d4" in cleaned
    assert "deadbeef" in cleaned
    assert "ffffffff" not in cleaned
    assert set(valid) == {"a1b2c3d4", "deadbeef"}


def test_compact_citations_removes_extra_chunk_tokens_from_answer():
    from paper_rag.rag.citation_check import compact_citations

    answer = (
        "Direct support [chunk:aaa111]. "
        "Adjacent background [chunk:bbb222]. "
        "Repeat support [chunk:aaa111]."
    )

    cleaned, kept = compact_citations(answer, ["aaa111", "bbb222"], max_citations=1)

    assert kept == ["aaa111"]
    assert "[chunk:aaa111]" in cleaned
    assert "[chunk:bbb222]" not in cleaned
    assert "Adjacent background ." not in cleaned


def test_strip_suspicious_citation_forms_keeps_chunk_citations():
    from paper_rag.rag.citation_check import strip_suspicious_citation_forms

    cleaned = strip_suspicious_citation_forms(
        "RAG combines memories (Lewis et al., 2020) [chunk:abc123]. Extra [12]."
    )

    assert "(Lewis et al., 2020)" not in cleaned
    assert "[12]" not in cleaned
    assert "[chunk:abc123]" in cleaned


def test_mineru_image_path_rewrite_logic():
    """The internal _IMAGE_REF_RE + rewrite should redirect to figures/."""
    from paper_rag.parse.mineru_local import _IMAGE_REF_RE

    md = "Some text\n![alt](images/fig1.png)\n"
    asset_map = {"fig1.png": "figures/fig1.png"}

    def _rewrite(m):
        alt, path = m.group(1), m.group(2)
        return f"![{alt}]({asset_map.get(Path(path).name, path)})"

    from pathlib import Path
    out = _IMAGE_REF_RE.sub(_rewrite, md)
    assert "figures/fig1.png" in out
    assert "images/fig1.png" not in out


def test_mineru_failure_classifier_cv2():
    from paper_rag.parse.mineru_local import classify_failure

    reason, hint = classify_failure("ModuleNotFoundError: No module named 'cv2'")
    assert reason == "missing_cv2"
    assert ".[mineru]" in hint


def test_mineru_failure_classifier_full_extra():
    from paper_rag.parse.mineru_local import classify_failure

    reason, hint = classify_failure("ModuleNotFoundError: No module named 'ultralytics'")
    assert reason == "missing_mineru_full_extra"
    assert ".[mineru]" in hint


def test_mineru_doctor_report_serializes():
    from paper_rag.parse.mineru_local import MineruCheck, MineruDoctorReport

    report = MineruDoctorReport(
        ok=False,
        cli_path=None,
        config_path="/tmp/magic-pdf.json",
        checks=[MineruCheck("cv2", False, "missing", "install")],
    )
    payload = report.to_dict()
    assert payload["ok"] is False
    assert payload["checks"][0]["name"] == "cv2"


def test_query_rewrite_factscore_variants():
    from paper_rag.rag.query_rewrite import _heuristic_variants

    variants = _heuristic_variants("What is FactScore and how is it used in Self-RAG?")

    joined = " ".join(variants).lower()
    assert "self-rag" in joined
    assert "factscore" in joined
    assert "factuality" in joined


def test_query_rewrite_chunk_size_variants():
    from paper_rag.rag.query_rewrite import _heuristic_variants

    variants = _heuristic_variants(
        "What is the typical chunk size used for embedding in production RAG systems?"
    )

    joined = " ".join(variants).lower()
    assert "chunking" in joined
    assert "100 256 512" in joined
    assert "embedding" in joined


def test_query_rewrite_latency_variants():
    from paper_rag.rag.query_rewrite import _heuristic_variants

    variants = _heuristic_variants(
        "What latency tradeoffs do retrieval and reranking introduce in RAG systems?"
    )

    joined = " ".join(variants).lower()
    assert "latency" in joined
    assert "reranking" in joined
