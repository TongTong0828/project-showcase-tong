from __future__ import annotations

import json
from pathlib import Path

import yaml

DEERFLOW_ROOT = Path(__file__).resolve().parents[2]


def test_paper_rag_harness_tools_are_importable():
    from deerflow.community.paper_rag import tools

    exposed = {
        tools.paper_ingest_tool.name,
        tools.paper_qa_tool.name,
        tools.paper_search_tool.name,
        tools.paper_section_tool.name,
        tools.paper_compare_tool.name,
        tools.paper_discover_tool.name,
        tools.wiki_lookup_tool.name,
        tools.export_bibtex_tool.name,
        tools.paper_deliver_tool.name,
    }

    assert exposed == {
        "paper_ingest",
        "paper_qa",
        "paper_search",
        "paper_section",
        "paper_compare",
        "paper_discover",
        "wiki_lookup",
        "export_bibtex",
        "paper_deliver",
    }


def test_paper_research_subagent_is_registered():
    from deerflow.subagents.builtins import BUILTIN_SUBAGENTS

    config = BUILTIN_SUBAGENTS["paper-research"]

    assert config.name == "paper-research"
    assert "paper_rag" in config.description
    assert config.tools is not None
    assert "paper_qa" in config.tools
    assert "paper_search" in config.tools
    assert "paper_ingest" in config.tools
    assert "paper_discover" in config.tools
    assert "paper_deliver" in config.tools
    assert "wiki_lookup" in config.tools


def test_paper_discover_tool_returns_ranked_candidates(monkeypatch):
    from paper_rag.discovery import runner

    from deerflow.community.paper_rag import tools

    def _fake_run_discovery(topic, *, user_id, source_names=None, max_candidates=10, search_limit=25):
        assert topic == "agentic rag"
        assert user_id == "harness"
        assert max_candidates == 3
        return {
            "run": {"id": 12, "status": "completed", "stopped_by": "selected_limit"},
            "trace": {"trace_id": "disc-123", "loop": [{"stage": "rank", "selected": 1}]},
            "candidates": [
                {
                    "title": "Agentic RAG",
                    "paper_id": "arxiv:2601.00001",
                    "score": 0.81,
                    "selected": True,
                    "rank_reason": "keyword_overlap=0.42; source_confidence=0.15",
                    "skip_reason": None,
                }
            ],
        }

    monkeypatch.setattr(runner, "run_discovery", _fake_run_discovery)

    payload = tools.paper_discover_tool.invoke({"topic": "agentic rag", "max_candidates": 3})

    assert '"trace_id": "disc-123"' in payload
    assert '"paper_id": "arxiv:2601.00001"' in payload
    assert "keyword_overlap" in payload


def test_paper_ingest_tool_delegates_to_paper_index(monkeypatch):
    from paper_rag.tools import paper_index

    from deerflow.community.paper_rag import tools

    calls = []

    def _fake_ingest(payload):
        calls.append(payload)
        return {
            "status": "ingested",
            "paper_id": "arxiv:1234.56789",
            "title": "Test Paper",
            "n_chunks": 9,
        }

    monkeypatch.setattr(paper_index, "ingest", _fake_ingest)

    payload = tools.paper_ingest_tool.invoke(
        {
            "arxiv_id": "1234.56789",
            "title_hint": "Test Paper",
        }
    )

    assert calls == [{"arxiv_id": "1234.56789", "pdf_url": None, "pdf_path": None, "title_hint": "Test Paper"}]
    assert '"status": "ingested"' in payload
    assert '"n_chunks": 9' in payload


def test_paper_qa_tool_schema_exposes_only_model_fields():
    from deerflow.community.paper_rag import tools

    schema = tools.paper_qa_tool.args

    assert set(schema) == {"question", "paper_ids", "resolved_question"}


def test_paper_qa_tool_passes_resolved_question_and_runtime_context(monkeypatch):
    from paper_rag.tools import paper_qa as paper_qa_mod

    from deerflow.community.paper_rag import tools

    captured = {}

    def fake_paper_qa(input):
        captured.update(input.model_dump())
        return {
            "answer": "ok",
            "citations": [],
            "chunks": [],
            "trace": {
                "trace_id": "trace-1",
                "query_resolution": {"effective_question": input.resolved_question},
            },
        }

    monkeypatch.setattr(paper_qa_mod, "paper_qa", fake_paper_qa)
    monkeypatch.setattr(tools, "_runtime_context_from_config", lambda config=None: ("thread-1", "alice"))

    payload = tools.paper_qa_tool.invoke(
        {
            "question": "raw",
            "paper_ids": "p1",
            "resolved_question": "effective",
        }
    )
    data = json.loads(payload)

    assert captured["question"] == "raw"
    assert captured["paper_ids"] == ["p1"]
    assert captured["conversation_id"] == "thread-1"
    assert captured["user_id"] == "alice"
    assert captured["resolved_question"] == "effective"
    assert data["query_resolution"]["effective_question"] == "effective"


def test_paper_deliver_tool_returns_base64_payload(monkeypatch):
    import paper_rag.deliver as deliver
    from paper_rag.deliver.dispatch import DeliverableResult

    from deerflow.community.paper_rag import tools

    calls = []

    def _fake_dispatch(format, paper_ids, *, title=None, options=None, user_id="system"):
        calls.append(
            {
                "format": format,
                "paper_ids": paper_ids,
                "title": title,
                "options": options,
                "user_id": user_id,
            }
        )
        return DeliverableResult(
            format=format,
            filename="survey.md",
            content_bytes=b"# Survey\n",
            content_type="text/markdown",
            metadata={"n_papers": len(paper_ids)},
        )

    monkeypatch.setattr(deliver, "dispatch", _fake_dispatch)

    payload = tools.paper_deliver_tool.invoke(
        {
            "format": "markdown_survey",
            "paper_ids": "arxiv:1, arxiv:2",
            "title": "RAG Survey",
            "options_json": '{"max_words": 1000}',
        }
    )

    assert calls == [
        {
            "format": "markdown_survey",
            "paper_ids": ["arxiv:1", "arxiv:2"],
            "title": "RAG Survey",
            "options": {"max_words": 1000},
            "user_id": "harness",
        }
    ]
    assert '"filename": "survey.md"' in payload
    assert '"content_base64": "IyBTdXJ2ZXkK"' in payload
    assert '"n_papers": 2' in payload


def test_paper_rag_tools_are_in_example_config():
    data = yaml.safe_load((DEERFLOW_ROOT / "config.example.yaml").read_text())
    tool_names = {tool["name"] for tool in data["tools"]}

    assert {
        "paper_ingest",
        "paper_qa",
        "paper_search",
        "paper_section",
        "paper_compare",
        "paper_discover",
        "wiki_lookup",
        "export_bibtex",
        "paper_deliver",
    }.issubset(tool_names)


def test_public_paper_research_skill_allows_all_paper_tools():
    skill_text = (DEERFLOW_ROOT / "skills/public/paper-research/SKILL.md").read_text()

    for tool_name in (
        "paper_ingest",
        "paper_qa",
        "paper_search",
        "paper_section",
        "paper_compare",
        "paper_discover",
        "wiki_lookup",
        "export_bibtex",
        "paper_deliver",
    ):
        assert f"  - {tool_name}" in skill_text
