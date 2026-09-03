import pytest


def test_paper_index_ingest_validates_source_before_io():
    from paper_rag.tools.paper_index import PaperIngestInput, ingest

    payload = PaperIngestInput()

    with pytest.raises(ValueError, match="Provide one of"):
        ingest(payload)


def test_tools_lazy_export_includes_paper_ingest():
    import paper_rag.tools as tools

    assert "paper_ingest" in tools.__all__
    assert callable(tools.paper_ingest)
