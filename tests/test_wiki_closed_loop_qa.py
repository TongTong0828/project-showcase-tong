from __future__ import annotations

from types import SimpleNamespace


def test_query_rewrite_uses_wiki_aliases(monkeypatch):
    from paper_rag.rag import query_rewrite

    monkeypatch.setattr(
        query_rewrite.cfg,
        "load",
        lambda: SimpleNamespace(
            rag=SimpleNamespace(enable_hyde=False),
            llm=SimpleNamespace(chat_model=None, api_key=None, base_url=None),
        ),
    )

    out = query_rewrite.rewrite("什么是对比学习?", wiki_context={
        "entries": [{
            "name": "Contrastive Learning",
            "aliases": ["对比学习", "CL"],
            "definition": "Learns representations from positive and negative pairs.",
            "key_papers": ["paper-1"],
        }]
    })

    assert "Contrastive Learning" in out["dense_queries"]
    assert any("positive negative pairs" in q for q in out["dense_queries"])
    assert "contrastive learning" in out["bm25_query"].lower()
    assert out["raw"]["wiki_context_used"] is True


def test_qa_trace_and_prompt_include_wiki_context(monkeypatch):
    from paper_rag.rag import qa_agentic

    prompts = []
    wiki_context = {
        "role": "background_not_evidence",
        "fingerprint": "concept:rag:1",
        "entries": [{
            "entry_id": "concept:rag",
            "name": "RAG",
            "definition": "Retrieval augmented generation background.",
            "aliases": ["Retrieval-Augmented Generation"],
            "key_papers": ["p1"],
            "version": 1,
        }],
    }
    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: wiki_context)
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda question, paper_ids, trace_id: None)
    monkeypatch.setattr(qa_agentic, "_retrieve_loop", lambda *args, **kwargs: ({
        "abc123": {"chunk_id": "abc123", "paper_id": "p1", "text": "RAG retrieves docs.", "score_dense": 0.9}
    }, [{"query": "q", "n_retrieved": 1, "reflect": None}], "answered"))
    monkeypatch.setattr(qa_agentic, "_decide_abstain", lambda chunks, cfg: {"decision": "confident", "evidence_score": 0.9})
    monkeypatch.setattr(qa_agentic, "classify", lambda question: {"intent": "factual", "top_k": 5, "max_iter": 1})
    monkeypatch.setattr(qa_agentic, "select_evidence", lambda question, chunks, intent=None: (chunks, {}))
    monkeypatch.setattr(qa_agentic, "_store_in_cache", lambda question, paper_ids, out: None)

    def fake_chat(messages, **kwargs):
        prompts.append(messages[-1]["content"])
        return "RAG retrieves docs [chunk:abc123]. Wiki says background [chunk:wiki]."

    monkeypatch.setattr(qa_agentic, "chat", fake_chat)

    out = qa_agentic._answer_impl("What is RAG?", paper_ids=None, trace_id="t")

    assert out["trace"]["wiki_context"]["fingerprint"] == "concept:rag:1"
    assert out["citations"] == ["abc123"]
    assert "[chunk:wiki]" not in out["answer"]
    assert "Wiki background (not evidence)" in prompts[0]
    assert "Do not cite this background" in prompts[0]


def test_weak_evidence_enqueues_wiki_review(monkeypatch):
    from paper_rag.rag import abstain as abstain_mod
    from paper_rag.rag import qa_agentic

    recorded = []
    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: {
        "role": "background_not_evidence",
        "fingerprint": "concept:rag:2",
        "entries": [{"entry_id": "concept:rag", "name": "RAG", "version": 2}],
    })
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda question, paper_ids, trace_id: None)
    monkeypatch.setattr(qa_agentic, "_retrieve_loop", lambda *args, **kwargs: ({
        "abc123": {"chunk_id": "abc123", "paper_id": "p1", "text": "thin evidence", "score_dense": 0.25}
    }, [{"query": "q", "n_retrieved": 1, "reflect": None}], "answered"))
    monkeypatch.setattr(
        qa_agentic,
        "_decide_abstain",
        lambda chunks, cfg: {"decision": abstain_mod.DECISION_WEAK, "evidence_score": 0.25},
    )
    monkeypatch.setattr(qa_agentic, "classify", lambda question: {"intent": "factual", "top_k": 5, "max_iter": 1})
    monkeypatch.setattr(qa_agentic, "select_evidence", lambda question, chunks, intent=None: (chunks, {}))
    monkeypatch.setattr(qa_agentic, "chat", lambda messages, **kwargs: "Thin answer [chunk:abc123].")
    monkeypatch.setattr(qa_agentic, "_store_in_cache", lambda question, paper_ids, out: None)
    monkeypatch.setattr(qa_agentic, "_enqueue_wiki_review_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    qa_agentic._answer_impl("What is RAG?", paper_ids=["p1"], trace_id="t")

    assert recorded
    assert recorded[0][0][0] == "qa_weak_evidence"
    assert recorded[0][1]["concept"] == "RAG"
    assert recorded[0][1]["paper_id"] == "p1"


def test_qa_records_wiki_consumption(monkeypatch):
    from paper_rag.rag import qa_agentic

    recorded = []
    wiki_context = {
        "role": "background_not_evidence",
        "fingerprint": "concept:rag:1",
        "entries": [{"entry_id": "concept:rag", "name": "RAG", "version": 1}],
    }
    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: wiki_context)
    monkeypatch.setattr(qa_agentic, "_record_wiki_consumption_safe", lambda **kwargs: recorded.append(kwargs))
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda question, paper_ids, trace_id: None)
    monkeypatch.setattr(qa_agentic, "_retrieve_loop", lambda *args, **kwargs: ({
        "abc123": {"chunk_id": "abc123", "paper_id": "p1", "text": "RAG retrieves docs.", "score_dense": 0.9}
    }, [{"query": "q", "n_retrieved": 1, "reflect": None}], "answered"))
    monkeypatch.setattr(qa_agentic, "_decide_abstain", lambda chunks, cfg: {"decision": "confident", "evidence_score": 0.9})
    monkeypatch.setattr(qa_agentic, "classify", lambda question: {"intent": "factual", "top_k": 5, "max_iter": 1})
    monkeypatch.setattr(qa_agentic, "select_evidence", lambda question, chunks, intent=None: (chunks, {}))
    monkeypatch.setattr(qa_agentic, "chat", lambda messages, **kwargs: "Answer [chunk:abc123].")
    monkeypatch.setattr(qa_agentic, "_store_in_cache", lambda question, paper_ids, out: None)

    qa_agentic._answer_impl("What is RAG?", paper_ids=["p1"], trace_id="t")

    assert recorded == [{
        "question": "What is RAG?",
        "paper_ids": ["p1"],
        "wiki_context": wiki_context,
        "trace_id": "t",
    }]
