from __future__ import annotations


def test_outer_resolved_question_is_authoritative(monkeypatch):
    from paper_rag.rag import context_resolver as resolver

    called = {"rewrite": 0}

    def fail_rewrite(*args, **kwargs):
        called["rewrite"] += 1
        raise AssertionError("inner rewrite must not run")

    monkeypatch.setattr(resolver, "_rewrite_with_memory", fail_rewrite)
    monkeypatch.setattr(resolver, "_load_memory_scope_hint", lambda *a, **kw: ["arxiv:memory"])

    ctx = resolver.QARequestContext(
        raw_question="What about the second one?",
        outer_resolved_question="How does FLARE retrieve?",
        explicit_paper_ids=("arxiv:flare",),
        conversation_id="thread-1",
        user_id="alice",
        caller="host",
    )

    out = resolver.resolve_query(ctx)

    assert out.effective_question == "How does FLARE retrieve?"
    assert out.source == "outer_checkpoint"
    assert out.policy == "authoritative_outer"
    assert out.rewrite_applied is False
    assert out.outer_resolution_used is True
    assert out.effective_paper_ids == ("arxiv:flare",)
    assert called["rewrite"] == 0
    assert out.conflicts == ("memory_scope_ignored_due_to_explicit_paper_ids",)


def test_inner_fallback_runs_one_rewrite(monkeypatch):
    from paper_rag.rag import context_resolver as resolver

    calls = []

    def fake_rewrite(question, *, user_id, conversation_id):
        calls.append((question, user_id, conversation_id))
        return "How does FLARE retrieve?", "paper_rag_recent_turns"

    monkeypatch.setattr(resolver, "_rewrite_with_memory", fake_rewrite)
    monkeypatch.setattr(resolver, "_load_memory_scope_hint", lambda *a, **kw: ["arxiv:flare"])

    ctx = resolver.QARequestContext(
        raw_question="What about the second one?",
        outer_resolved_question=None,
        explicit_paper_ids=(),
        conversation_id="thread-1",
        user_id="alice",
        caller="python",
    )

    out = resolver.resolve_query(ctx)

    assert calls == [("What about the second one?", "alice", "thread-1")]
    assert out.effective_question == "How does FLARE retrieve?"
    assert out.source == "paper_rag_recent_turns"
    assert out.policy == "inner_fallback"
    assert out.rewrite_applied is True
    assert out.memory_paper_scope_hint == ("arxiv:flare",)
    assert out.effective_paper_ids == ()


def test_resolution_trace_is_serializable():
    from paper_rag.rag import context_resolver as resolver

    res = resolver.QueryResolution(
        raw_question="raw",
        effective_question="effective",
        source="api_resolved",
        policy="authoritative_outer",
        rewrite_applied=False,
        outer_resolution_used=True,
        explicit_paper_ids=("p1",),
        memory_paper_scope_hint=(),
        effective_paper_ids=("p1",),
        conflicts=(),
    )

    assert resolver.resolution_to_trace(res) == {
        "raw_question": "raw",
        "effective_question": "effective",
        "source": "api_resolved",
        "policy": "authoritative_outer",
        "rewrite_applied": False,
        "outer_resolution_used": True,
        "explicit_paper_ids": ["p1"],
        "memory_paper_scope_hint": [],
        "effective_paper_ids": ["p1"],
        "conflicts": [],
        "memory_used_as_evidence": False,
        "context_source": "api_resolved",
        "memory_mode": "scope_only",
    }
