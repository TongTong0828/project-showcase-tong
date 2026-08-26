from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import metrics, paper_rag

PAPER_RAG_HOME = Path(__file__).resolve().parents[4]


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(paper_rag.router)
    app.include_router(metrics.router)
    return app


def _make_authenticated_app() -> FastAPI:
    app = _make_app()

    @app.middleware("http")
    async def _fake_user(request, call_next):
        request.state.user = SimpleNamespace(id="default")
        return await call_next(request)

    return app


def test_paper_rag_router_exposes_expected_routes(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    paths = {route.path for route in paper_rag.router.routes}

    assert "/api/paper_rag/qa" in paths
    assert "/api/paper_rag/qa/sync" in paths
    assert "/api/paper_rag/status" in paths
    assert "/api/paper_rag/papers" in paths
    assert "/api/paper_rag/discovery/run" in paths
    assert "/api/paper_rag/discovery/runs" in paths
    assert "/api/paper_rag/discovery/runs/{run_id}" in paths
    assert "/api/paper_rag/discovery/candidates/{candidate_id}/ingest" in paths
    assert "/api/paper_rag/wiki/{paper_id}/generate" in paths
    assert "/api/paper_rag/subscriptions" in paths
    assert "/api/paper_rag/inbox" in paths
    assert "/api/paper_rag/deliver" in paths


def test_metrics_endpoint_is_public(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    client = TestClient(_make_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_paper_rag_routes_require_authenticated_user(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    client = TestClient(_make_app())

    response = client.get("/api/paper_rag/papers")

    assert response.status_code == 401


def test_ensure_paper_rag_importable_finds_sibling_checkout(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    import paper_rag as imported

    assert Path(imported.__file__).resolve().is_relative_to(PAPER_RAG_HOME)


def test_qa_sync_translates_internal_failures_to_503(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.rag import qa_agentic

    def _boom(*args, **kwargs):
        raise RuntimeError("embedder unavailable")

    monkeypatch.setattr(qa_agentic, "answer", _boom)
    client = TestClient(_make_authenticated_app())

    response = client.post("/api/paper_rag/qa/sync", json={"question": "What is Self-RAG?"})

    assert response.status_code == 503
    assert "embedder unavailable" in response.json()["detail"]


def test_runtime_status_reports_readiness_without_secrets(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-test-value")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    paper_rag._ensure_paper_rag_importable()

    from paper_rag import config as cfg

    cfg.load.cache_clear()
    monkeypatch.setattr(paper_rag, "_count_sqlite_papers", lambda _path: 6)
    monkeypatch.setattr(paper_rag, "_count_qdrant_points", lambda _collection: (301, None))
    client = TestClient(_make_authenticated_app())
    try:
        response = client.get("/api/paper_rag/status")
    finally:
        cfg.load.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["importable"] is True
    assert body["llm_configured"] is True
    assert body["chat_model"] == "test-chat-model"
    assert body["api_key_configured"] is True
    assert body["evidence_only"] is False
    assert body["sqlite_papers"] == 6
    assert body["qdrant_points"] == 301
    assert "sk-secret-test-value" not in response.text


def test_wiki_missing_entry_returns_404(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    monkeypatch.setattr(paper_rag, "_lookup_wiki_for_paper", lambda _store, _paper_id: None)
    client = TestClient(_make_authenticated_app())

    response = client.get("/api/paper_rag/wiki/arxiv%3A2310.11511")

    assert response.status_code == 404
    assert "No wiki entry" in response.json()["detail"]


def test_generate_wiki_returns_generated_entry(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.wiki import triggers

    def _fake_generate(paper_id, *, force=False):
        return {"paper_id": paper_id, "created": 1, "patched": 0, "skipped": 0, "force": force}

    monkeypatch.setattr(triggers, "on_paper_indexed", _fake_generate)
    monkeypatch.setattr(
        paper_rag,
        "_lookup_wiki_for_paper",
        lambda _store, _paper_id: {"summary": "Generated wiki summary.", "last_updated": "now"},
    )
    client = TestClient(_make_authenticated_app())

    response = client.post("/api/paper_rag/wiki/arxiv%3A2401.01313/generate")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "generated"
    assert body["report"]["force"] is True
    assert body["wiki"]["word_count"] == 3


def test_generate_wiki_missing_paper_returns_404(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.wiki import triggers

    monkeypatch.setattr(
        triggers,
        "on_paper_indexed",
        lambda paper_id, *, force=False: {"error": f"paper not found: {paper_id}"},
    )
    client = TestClient(_make_authenticated_app())

    response = client.post("/api/paper_rag/wiki/arxiv%3Amissing/generate")

    assert response.status_code == 404
    assert "paper not found" in response.json()["detail"]


def test_ingest_response_preserves_pipeline_metadata(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.ingest.arxiv_source import ArxivSource
    from paper_rag.ingest.schema import FetchResult, PaperMeta
    from paper_rag.store import ingest_pipeline

    monkeypatch.setattr(
        ArxivSource,
        "fetch",
        lambda _self, _identifier: FetchResult(
            meta=PaperMeta(paper_id="arxiv:new", title="New Paper", arxiv_id="1234.56789"),
            pdf_path="/tmp/new.pdf",
        ),
    )
    monkeypatch.setattr(
        ingest_pipeline,
        "ingest",
        lambda _fetched, force=False: {
            "paper_id": "arxiv:new",
            "status": "skipped",
            "reason": "dedup",
            "merged_into": "arxiv:old",
            "wiki": {"queued": True},
        },
    )
    client = TestClient(_make_authenticated_app())

    response = client.post("/api/paper_rag/papers/ingest", json={"arxiv_id": "1234.56789"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "dedup"
    assert body["merged_into"] == "arxiv:old"
    assert body["wiki"] == {"queued": True}


def test_ingest_translates_runtime_failures_to_503(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.ingest.arxiv_source import ArxivSource

    def _boom(*args, **kwargs):
        raise RuntimeError("arxiv package not installed")

    monkeypatch.setattr(ArxivSource, "fetch", _boom)
    client = TestClient(_make_authenticated_app())

    response = client.post("/api/paper_rag/papers/ingest", json={"arxiv_id": "1234.56789"})

    assert response.status_code == 503
    assert "arxiv package not installed" in response.json()["detail"]


def test_discovery_run_delegates_to_paper_rag_runner(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.discovery import runner

    calls = []

    def _fake_run_discovery(topic, **kwargs):
        calls.append({"topic": topic, **kwargs})
        return {
            "run": {"id": 9, "topic": topic, "status": "completed", "stopped_by": "selected_limit"},
            "trace": {"trace_id": "disc-9", "loop": [{"stage": "search"}]},
            "candidates": [
                {
                    "id": 77,
                    "title": "Discovery Candidate",
                    "paper_id": "arxiv:2601.00009",
                    "score": 0.79,
                    "selected": True,
                    "rank_reason": "keyword_overlap=0.44",
                    "skip_reason": None,
                    "ingest_status": "pending",
                }
            ],
        }

    monkeypatch.setattr(runner, "run_discovery", _fake_run_discovery)
    client = TestClient(_make_authenticated_app())

    response = client.post(
        "/api/paper_rag/discovery/run",
        json={"topic": "agentic rag", "sources": ["arxiv"], "max_candidates": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trace"]["trace_id"] == "disc-9"
    assert body["candidates"][0]["rank_reason"] == "keyword_overlap=0.44"
    assert calls == [
        {
            "topic": "agentic rag",
            "user_id": "default",
            "source_names": ["arxiv"],
            "max_candidates": 3,
            "search_limit": 25,
        }
    ]


def test_discovery_candidate_ingest_is_user_scoped(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.discovery import runner

    calls = []
    monkeypatch.setattr(
        runner,
        "ingest_candidate",
        lambda candidate_id, *, user_id, force=False: calls.append(
            {"candidate_id": candidate_id, "user_id": user_id, "force": force}
        )
        or {"candidate_id": candidate_id, "paper_id": "arxiv:2601.00009", "status": "done", "n_chunks": 8},
    )
    client = TestClient(_make_authenticated_app())

    response = client.post("/api/paper_rag/discovery/candidates/77/ingest")

    assert response.status_code == 200
    assert response.json()["paper_id"] == "arxiv:2601.00009"
    assert calls == [{"candidate_id": 77, "user_id": "default", "force": False}]


def test_subscription_list_includes_paused_items(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.proactive import subscriptions

    calls = []

    def _fake_list(user_id, *, only_enabled=True, kind=None):
        calls.append({"user_id": user_id, "only_enabled": only_enabled, "kind": kind})
        return [{"id": 1, "kind": "keyword", "value": "RAG", "strength": "normal", "enabled": 0}]

    monkeypatch.setattr(subscriptions, "list_for_user", _fake_list)
    client = TestClient(_make_authenticated_app())

    response = client.get("/api/paper_rag/subscriptions")

    assert response.status_code == 200
    assert response.json()[0]["enabled"] == 0
    assert calls == [{"user_id": "default", "only_enabled": False, "kind": None}]


def test_subscription_toggle_and_delete_routes_are_user_scoped(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.proactive import subscriptions

    calls = []
    monkeypatch.setattr(
        subscriptions,
        "toggle",
        lambda sub_id, *, enabled, user_id=None: calls.append(
            {"action": "toggle", "sub_id": sub_id, "enabled": enabled, "user_id": user_id}
        )
        or True,
    )
    monkeypatch.setattr(
        subscriptions,
        "delete",
        lambda sub_id, *, user_id=None: calls.append(
            {"action": "delete", "sub_id": sub_id, "user_id": user_id}
        )
        or True,
    )
    client = TestClient(_make_authenticated_app())

    toggle_response = client.patch("/api/paper_rag/subscriptions/7", json={"enabled": False})
    delete_response = client.delete("/api/paper_rag/subscriptions/7")

    assert toggle_response.status_code == 200
    assert toggle_response.json() == {"id": 7, "enabled": False}
    assert delete_response.status_code == 200
    assert delete_response.json() == {"id": 7, "status": "deleted"}
    assert calls == [
        {"action": "toggle", "sub_id": 7, "enabled": False, "user_id": "default"},
        {"action": "delete", "sub_id": 7, "user_id": "default"},
    ]


def test_feedback_route_records_answer_feedback(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    import paper_rag.feedback as feedback

    calls = []

    def _fake_record_event(**kwargs):
        calls.append(kwargs)
        return 42

    monkeypatch.setattr(feedback, "record_event", _fake_record_event)
    client = TestClient(_make_authenticated_app())

    response = client.post(
        "/api/paper_rag/feedback",
        json={
            "event_type": "thumbs_up",
            "trace_id": "trace-123",
            "conversation_id": "conv-1",
            "payload": {"answer_chars": 120, "n_chunks": 8},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"id": 42, "status": "recorded", "user_id": "default"}
    assert calls == [
        {
            "user_id": "default",
            "event_type": "thumbs_up",
            "payload": {"answer_chars": 120, "n_chunks": 8},
            "trace_id": "trace-123",
            "conversation_id": "conv-1",
        }
    ]


def test_inbox_read_and_dismiss_routes_are_user_scoped(monkeypatch):
    monkeypatch.setenv("PAPER_RAG_HOME", str(PAPER_RAG_HOME))
    paper_rag._ensure_paper_rag_importable()

    from paper_rag.proactive import inbox

    calls = []
    monkeypatch.setattr(
        inbox,
        "mark_read",
        lambda item_id, *, user_id=None: calls.append(
            {"action": "read", "item_id": item_id, "user_id": user_id}
        )
        or True,
    )
    monkeypatch.setattr(
        inbox,
        "dismiss",
        lambda item_id, *, user_id=None: calls.append(
            {"action": "dismiss", "item_id": item_id, "user_id": user_id}
        )
        or True,
    )
    client = TestClient(_make_authenticated_app())

    read_response = client.post("/api/paper_rag/inbox/9/read")
    dismiss_response = client.post("/api/paper_rag/inbox/9/dismiss")

    assert read_response.status_code == 200
    assert read_response.json() == {"id": 9, "marked_read": True}
    assert dismiss_response.status_code == 200
    assert dismiss_response.json() == {"id": 9, "dismissed": True}
    assert calls == [
        {"action": "read", "item_id": 9, "user_id": "default"},
        {"action": "dismiss", "item_id": 9, "user_id": "default"},
    ]
