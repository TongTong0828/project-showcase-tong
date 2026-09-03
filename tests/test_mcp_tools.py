from __future__ import annotations

from types import SimpleNamespace


def _point_sqlite_to_tmp(monkeypatch, tmp_path):
    from paper_rag.store import sqlite_store

    sqlite_store._ENGINE = None
    monkeypatch.setattr(
        sqlite_store.cfg,
        "load",
        lambda: SimpleNamespace(
            paths=SimpleNamespace(sqlite_path=str(tmp_path / "papers.sqlite")),
            qdrant=SimpleNamespace(
                url="file://local-qdrant",
                local_path=str(tmp_path / "qdrant"),
                collection_chunks="paper_chunks",
                collection_wiki="wiki_entries",
            ),
            llm=SimpleNamespace(base_url="https://api.deepseek.com", api_key=None, chat_model="deepseek-v4-flash"),
            wiki=SimpleNamespace(enabled=True),
        ),
    )


def _ctx():
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig

    return McpRequestContext(
        config=McpServerConfig(toolset="readonly", actor_id="system"),
        conversation_id="dsh-session-1",
        tool_call_id="call-1",
    )


def test_paper_status_and_list_read_isolated_sqlite(tmp_path, monkeypatch):
    _point_sqlite_to_tmp(monkeypatch, tmp_path)
    from sqlmodel import Session

    from paper_rag.mcp.registry import call_tool
    from paper_rag.store.sqlite_store import Chunk, Paper, get_engine

    engine = get_engine()
    with Session(engine) as session:
        session.add(Paper(paper_id="paper-1", title="Agentic RAG", arxiv_id="2601.00001", status="done"))
        session.add(Chunk(chunk_id="chunk-1", paper_id="paper-1", text="retrieval loop"))
        session.commit()

    status = call_tool("paper_status", {}, _ctx())["structuredContent"]
    listed = call_tool("paper_list", {"limit": 5}, _ctx())["structuredContent"]

    assert status["ok"] is True
    assert status["data"]["sqlite"]["paper_count"] == 1
    assert status["data"]["llm"]["chat_model"] == "deepseek-v4-flash"
    assert "api_key" not in str(status).lower()
    assert listed["data"]["papers"] == [
        {
            "paper_id": "paper-1",
            "title": "Agentic RAG",
            "arxiv_id": "2601.00001",
            "chunk_count": 1,
            "ingested_at": listed["data"]["papers"][0]["ingested_at"],
        }
    ]


def test_paper_section_returns_bounded_chunks(tmp_path, monkeypatch):
    _point_sqlite_to_tmp(monkeypatch, tmp_path)
    from sqlmodel import Session

    from paper_rag.mcp.registry import call_tool
    from paper_rag.store.sqlite_store import Chunk, Paper, Section, get_engine

    with Session(get_engine()) as session:
        session.add(Paper(paper_id="paper-1", title="Agentic RAG", status="done"))
        session.add(Section(section_id="sec-1", paper_id="paper-1", idx=1, name="Limitations"))
        session.add(
            Chunk(
                chunk_id="chunk-1",
                paper_id="paper-1",
                section_id="sec-1",
                modality="text",
                page=7,
                text="This limitations section is intentionally long. " * 80,
            )
        )
        session.commit()

    result = call_tool(
        "paper_section",
        {"paper_id": "paper-1", "section_name": "limit"},
        _ctx(),
    )

    assert result["structuredContent"]["ok"] is True
    assert result["structuredContent"]["data"]["section"]["name"] == "Limitations"
    assert result["structuredContent"]["data"]["chunks"][0]["chunk_id"] == "chunk-1"
    assert result["structuredContent"]["data"]["truncated"] is True
    assert len(result["content"][0]["text"]) < 1600


def test_paper_qa_uses_outer_resolution_and_trusted_identity(monkeypatch):
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import paper_qa as paper_qa_module

    seen = {}

    def fake_paper_qa(payload):
        seen.update(payload.model_dump())
        return {
            "answer": "Uses hybrid retrieval. [chunk:c1]",
            "citations": ["c1"],
            "chunks": [{"chunk_id": "c1", "paper_id": "p1", "text": "hybrid retrieval"}],
            "trace": {
                "trace_id": "trace-qa",
                "abstain": {"decision": "answer"},
                "query_resolution": {"effective_question": payload.resolved_question},
            },
        }

    monkeypatch.setattr(paper_qa_module, "paper_qa", fake_paper_qa)

    result = call_tool(
        "paper_qa",
        {
            "question": "How about the second one?",
            "paper_ids": ["p1"],
            "resolved_question": "How does paper p1 retrieve evidence?",
        },
        _ctx(),
    )

    structured = result["structuredContent"]
    assert structured["ok"] is True
    assert seen["conversation_id"] == "dsh-session-1"
    assert seen["user_id"] == "system"
    assert seen["resolved_question"] == "How does paper p1 retrieve evidence?"
    assert structured["trace_id"] == "trace-qa"
    assert structured["data"]["citations"] == ["c1"]
    assert structured["evidence_role"] == "indexed_chunks"


def test_paper_search_and_wiki_lookup_delegate_to_existing_facades(monkeypatch):
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import paper_search as paper_search_module
    from paper_rag.tools import wiki_lookup as wiki_lookup_module

    monkeypatch.setattr(
        paper_search_module,
        "paper_search",
        lambda payload: [
            {
                "paper_id": "p1",
                "title": "Agentic RAG",
                "section": "Methods",
                "snippet": "x" * 900,
                "score": 0.91,
            }
        ],
    )
    monkeypatch.setattr(
        wiki_lookup_module,
        "wiki_lookup",
        lambda payload: {"hit": True, "entry": {"entry_id": "concept:rag", "name": payload.concept}},
    )

    search = call_tool("paper_search", {"query": "agentic rag", "top_k": 3}, _ctx())
    wiki = call_tool("wiki_lookup", {"concept": "RAG"}, _ctx())

    assert search["structuredContent"]["data"]["results"][0]["snippet"].endswith("...")
    assert search["structuredContent"]["data"]["truncated"] is True
    assert wiki["structuredContent"]["evidence_role"] == "metadata"
    assert wiki["structuredContent"]["data"]["entry"]["name"] == "RAG"


def test_paper_compare_enforces_limits_and_maps_actor_to_each_inner_qa(monkeypatch):
    from paper_rag.mcp.registry import call_tool
    from paper_rag.rag import qa_agentic

    calls = []

    def fake_answer(question, paper_ids=None, conversation_id=None, user_id="system", resolved_question=None):
        calls.append(
            {
                "question": question,
                "paper_ids": paper_ids,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "resolved_question": resolved_question,
            }
        )
        return {"answer": "ok [chunk:c1]", "citations": ["c1"], "chunks": [{"chunk_id": "c1"}]}

    monkeypatch.setattr(qa_agentic, "answer", fake_answer)

    result = call_tool(
        "paper_compare",
        {"paper_ids": ["p1", "p2"], "dimensions": ["method", "limits"]},
        _ctx(),
    )
    too_many = call_tool(
        "paper_compare",
        {"paper_ids": ["p1", "p2", "p3", "p4", "p5"], "dimensions": ["method"]},
        _ctx(),
    )

    assert result["structuredContent"]["ok"] is True
    assert len(calls) == 4
    assert {call["user_id"] for call in calls} == {"system"}
    assert {call["conversation_id"] for call in calls} == {"dsh-session-1"}
    assert too_many["structuredContent"]["ok"] is False
    assert too_many["structuredContent"]["error"]["code"] == "VALIDATION"
