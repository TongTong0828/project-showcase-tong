from __future__ import annotations


def test_paper_qa_mcp_matches_direct_python_facade_for_citations_and_resolution(monkeypatch):
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import paper_qa as paper_qa_module
    from paper_rag.tools._schema import PaperQAInput

    def fake_paper_qa(payload: PaperQAInput):
        effective = payload.resolved_question or payload.question
        return {
            "answer": f"{effective} [chunk:c1]",
            "citations": ["c1"],
            "chunks": [{"chunk_id": "c1", "paper_id": "p1", "text": "evidence"}],
            "trace": {
                "trace_id": "trace-parity",
                "abstain": {"decision": "answer"},
                "query_resolution": {"effective_question": effective},
            },
        }

    monkeypatch.setattr(paper_qa_module, "paper_qa", fake_paper_qa)

    direct = paper_qa_module.paper_qa(
        PaperQAInput(
            question="How does it retrieve evidence?",
            paper_ids=["p1"],
            conversation_id="session-parity",
            user_id="system",
            resolved_question="How does paper p1 retrieve evidence?",
        )
    )
    mcp = call_tool(
        "paper_qa",
        {
            "question": "How does it retrieve evidence?",
            "paper_ids": ["p1"],
            "resolved_question": "How does paper p1 retrieve evidence?",
        },
        McpRequestContext(
            config=McpServerConfig(actor_id="system", toolset="readonly"),
            conversation_id="session-parity",
        ),
    )["structuredContent"]["data"]

    assert mcp["citations"] == direct["citations"]
    assert mcp["abstain"] == direct["trace"]["abstain"]
    assert mcp["query_resolution"]["effective_question"] == direct["trace"]["query_resolution"]["effective_question"]


def test_paper_qa_mcp_preserves_no_evidence_abstain(monkeypatch):
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import paper_qa as paper_qa_module

    monkeypatch.setattr(
        paper_qa_module,
        "paper_qa",
        lambda _payload: {
            "answer": "No evidence.",
            "citations": [],
            "chunks": [],
            "trace": {
                "trace_id": "trace-no-evidence",
                "abstain": {"decision": "no_evidence"},
                "query_resolution": {"effective_question": "unsupported question"},
            },
        },
    )

    result = call_tool(
        "paper_qa",
        {"question": "unsupported question"},
        McpRequestContext(config=McpServerConfig(actor_id="system", toolset="readonly")),
    )["structuredContent"]

    assert result["ok"] is True
    assert result["data"]["citations"] == []
    assert result["data"]["abstain"]["decision"] == "no_evidence"
    assert result["evidence_role"] == "indexed_chunks"
