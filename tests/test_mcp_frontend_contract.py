from __future__ import annotations

import importlib
from pathlib import Path


def _ctx(tmp_path: Path, *, boundary: str | None = "boundary-1"):
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig

    return McpRequestContext(
        config=McpServerConfig(
            toolset="research",
            actor_id="system",
            artifact_root=tmp_path / "artifacts",
            import_root=tmp_path / "imports",
        ),
        conversation_id="dsh-session-frontend",
        tool_call_id="call-frontend",
        request_boundary_id=boundary,
    )


def test_discovery_contract_has_candidate_card_fields(monkeypatch, tmp_path):
    from paper_rag.discovery import runner
    from paper_rag.mcp.registry import call_tool

    monkeypatch.setattr(
        runner,
        "run_discovery",
        lambda topic, user_id, source_names, max_candidates: {
            "run": {"id": 7, "topic": topic},
            "trace": {"provider": "fixture"},
            "candidates": [
                {
                    "id": 11,
                    "title": "Candidate",
                    "source": "arxiv",
                    "rank": 1,
                    "rank_reason": "close match",
                }
            ],
        },
    )

    structured = call_tool(
        "paper_discover",
        {"topic": "agentic rag"},
        _ctx(tmp_path),
    )["structuredContent"]

    assert structured["ok"] is True
    assert structured["tool"] == "paper_discover"
    assert structured["evidence_role"] == "discovery_only"
    assert structured["data"]["run"]["id"] == 7
    assert structured["data"]["candidates"][0]["id"] == 11
    assert structured["data"]["candidates"][0]["evidence_role"] == "discovery_only_not_answer_evidence"


def test_answer_contract_has_citations_chunks_and_abstain(monkeypatch, tmp_path):
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import paper_qa as paper_qa_module

    monkeypatch.setattr(
        paper_qa_module,
        "paper_qa",
        lambda payload: {
            "answer": "Uses iterative retrieval. [chunk:c1]",
            "citations": ["c1"],
            "chunks": [{"chunk_id": "c1", "paper_id": "p1", "text": "iterative retrieval"}],
            "trace": {"trace_id": "trace-front", "abstain": {"decision": "answer"}},
        },
    )

    structured = call_tool(
        "paper_qa",
        {"question": "method?", "paper_ids": ["p1"]},
        _ctx(tmp_path),
    )["structuredContent"]

    assert structured["ok"] is True
    assert structured["evidence_role"] == "indexed_chunks"
    assert structured["trace_id"] == "trace-front"
    assert structured["data"]["citations"] == ["c1"]
    assert structured["data"]["chunks"][0]["chunk_id"] == "c1"
    assert structured["data"]["abstain"]["decision"] == "answer"


def test_write_contracts_include_receipt_and_artifact_metadata(monkeypatch, tmp_path):
    deliver_dispatch = importlib.import_module("paper_rag.deliver.dispatch")
    from paper_rag.discovery import runner
    from paper_rag.mcp.registry import call_tool

    monkeypatch.setattr(
        runner,
        "ingest_candidate",
        lambda candidate_id, user_id, force=False: {
            "candidate_id": candidate_id,
            "paper_id": f"paper-{candidate_id}",
            "status": "ingested",
            "n_chunks": 4,
        },
    )
    monkeypatch.setattr(
        deliver_dispatch,
        "dispatch",
        lambda format, paper_ids, title=None, options=None, user_id="system": deliver_dispatch.DeliverableResult(
            format=format,
            filename="front.md",
            content_bytes=b"# Frontend Contract\n",
            content_type="text/markdown; charset=utf-8",
            metadata={"n_citations": 1},
        ),
    )

    ingest = call_tool(
        "discovery_candidate_ingest",
        {"candidate_ids": [11]},
        _ctx(tmp_path),
    )["structuredContent"]
    deliver = call_tool(
        "paper_deliver",
        {"format": "markdown_survey", "paper_ids": ["paper-11"], "title": "Frontend Contract"},
        _ctx(tmp_path),
    )["structuredContent"]

    assert ingest["ok"] is True
    assert ingest["data"]["results"][0]["paper_id"] == "paper-11"
    assert ingest["data"]["results"][0]["status"] == "ingested"
    assert deliver["ok"] is True
    assert deliver["evidence_role"] == "artifact"
    assert deliver["data"]["artifact"]["manifest_path"].endswith("manifest.json")
    assert "content_base64" not in str(deliver)
