from __future__ import annotations


def test_thumbs_down_enqueues_wiki_review(monkeypatch):
    from paper_rag.feedback import collector

    recorded = []
    monkeypatch.setattr(collector, "_check_rate_limit", lambda user_id: None)
    monkeypatch.setattr(collector.store, "write", lambda ev: 123)
    monkeypatch.setattr(
        collector,
        "_enqueue_wiki_review_from_feedback",
        lambda event_type, payload, trace_id: recorded.append((event_type, payload, trace_id)),
    )

    rid = collector.record_event(
        "u1",
        "thumbs_down",
        {"reason": "incomplete", "question": "What is RAG?"},
        trace_id="t1",
    )

    assert rid == 123
    assert recorded == [("thumbs_down", {"reason": "incomplete", "question": "What is RAG?"}, "t1")]


def test_positive_feedback_does_not_enqueue_wiki_review(monkeypatch):
    from paper_rag.feedback import collector

    recorded = []
    monkeypatch.setattr(collector, "_check_rate_limit", lambda user_id: None)
    monkeypatch.setattr(collector.store, "write", lambda ev: 124)
    monkeypatch.setattr(
        collector,
        "_enqueue_wiki_review_from_feedback",
        lambda event_type, payload, trace_id: recorded.append((event_type, payload, trace_id)),
    )

    rid = collector.record_event("u1", "thumbs_up", {"question": "What is RAG?"}, trace_id="t2")

    assert rid == 124
    assert recorded == []
