from __future__ import annotations


def _empty_wiki_context() -> dict:
    return {"role": "background_not_evidence", "fingerprint": "", "entries": []}


def _confident_abstain(chunks, cfg):
    return {
        "decision": "confident",
        "evidence_score": 0.9,
        "n_chunks": len(chunks),
    }


def test_answer_uses_resolved_question_and_skips_legacy_rewriters(monkeypatch):
    from paper_rag.rag import context_resolver, qa_agentic

    seen = {}

    def fail_rewrite(*args, **kwargs):
        raise AssertionError("legacy rewrite must not run")

    monkeypatch.setattr(qa_agentic, "_maybe_rewrite_with_research_memory", fail_rewrite)
    monkeypatch.setattr(qa_agentic, "_maybe_rewrite_with_history", fail_rewrite)
    monkeypatch.setattr(context_resolver, "_load_memory_scope_hint", lambda *a, **kw: [])
    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: _empty_wiki_context())
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        qa_agentic,
        "classify",
        lambda q: {"intent": "factual", "top_k": 2, "max_iter": 1, "rrf_k": 60},
    )

    def fake_retrieve(question, paper_ids, top_k, max_iter, enable_reflect, wiki_context=None):
        seen["question"] = question
        seen["paper_ids"] = paper_ids
        return (
            {
                "c1": {
                    "chunk_id": "c1",
                    "paper_id": "p1",
                    "text": "FLARE retrieves proactively.",
                    "score_rerank": 0.9,
                }
            },
            [{"query": question, "n_retrieved": 1, "reflect": None}],
            "answered",
        )

    monkeypatch.setattr(qa_agentic, "_retrieve_loop", fake_retrieve)
    monkeypatch.setattr(qa_agentic, "_decide_abstain", _confident_abstain)
    monkeypatch.setattr(
        qa_agentic,
        "select_evidence",
        lambda question, chunks, intent=None: (chunks, {"selected_chunk_ids": ["c1"]}),
    )
    monkeypatch.setattr(qa_agentic, "chat", lambda *a, **kw: "FLARE retrieves proactively. [chunk:c1]")
    monkeypatch.setattr(qa_agentic, "_store_in_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        qa_agentic,
        "_persist_research_memory",
        lambda *args, **kwargs: {"memory_role": "query_context_only_not_evidence"},
    )

    out = qa_agentic.answer(
        "What about the second one?",
        paper_ids=["p1"],
        conversation_id="thread-1",
        user_id="alice",
        resolved_question="How does FLARE retrieve?",
    )

    assert seen["question"] == "How does FLARE retrieve?"
    assert seen["paper_ids"] == ["p1"]
    assert out["trace"]["query_resolution"]["source"] == "api_resolved"
    assert out["trace"]["query_resolution"]["rewrite_applied"] is False
    assert out["trace"]["query_resolution"]["memory_used_as_evidence"] is False
    assert out["query_resolution"] == out["trace"]["query_resolution"]


def test_final_prompt_excludes_research_memory_scope_hints(monkeypatch):
    from paper_rag.rag import context_resolver, qa_agentic

    captured = {"user": ""}

    monkeypatch.setattr(
        context_resolver,
        "_load_memory_scope_hint",
        lambda *a, **kw: ["Memory-only finding must stay out."],
    )
    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: _empty_wiki_context())
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        qa_agentic,
        "classify",
        lambda q: {"intent": "factual", "top_k": 2, "max_iter": 1, "rrf_k": 60},
    )
    monkeypatch.setattr(
        qa_agentic,
        "_retrieve_loop",
        lambda *a, **kw: (
            {
                "c1": {
                    "chunk_id": "c1",
                    "paper_id": "p1",
                    "text": "Only retrieved evidence.",
                    "score_rerank": 0.9,
                }
            },
            [{"query": "q", "n_retrieved": 1, "reflect": None}],
            "answered",
        ),
    )
    monkeypatch.setattr(qa_agentic, "_decide_abstain", _confident_abstain)
    monkeypatch.setattr(
        qa_agentic,
        "select_evidence",
        lambda question, chunks, intent=None: (chunks, {"selected_chunk_ids": ["c1"]}),
    )

    def fake_chat(messages, **kwargs):
        captured["user"] = messages[-1]["content"]
        return "Answer from retrieved evidence. [chunk:c1]"

    monkeypatch.setattr(qa_agentic, "chat", fake_chat)
    monkeypatch.setattr(qa_agentic, "_store_in_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        qa_agentic,
        "_persist_research_memory",
        lambda *args, **kwargs: {
            "research_memory": {"confirmed_findings": ["Memory-only finding must stay out."]}
        },
    )

    qa_agentic.answer(
        "What is supported?",
        conversation_id="conv",
        user_id="alice",
        resolved_question="What is supported?",
    )

    assert "Only retrieved evidence." in captured["user"]
    assert "Memory-only finding must stay out." not in captured["user"]
    assert "Evidence:" in captured["user"]
