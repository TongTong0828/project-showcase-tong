"""Tests for the gateway service-ization layer (M8 / ADR-0015).

These tests exercise the auth middleware, paper_rag router, and metrics
endpoint without touching the rest of the DeerFlow gateway (which has hard
deps on Python 3.12 features). We build a minimal FastAPI app and use
TestClient for end-to-end HTTP coverage.

Run:
    PAPER_RAG_CONFIG=config/local.yaml python -m pytest tests/test_gateway_paper_rag.py -v

Or, for environments without pytest, the file's main() runs all tests.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DEERFLOW_ROOT = REPO_ROOT.parent
ROOT = Path(os.environ.get("DEER_FLOW_ROOT", _DEFAULT_DEERFLOW_ROOT))
_REAL_GATEWAY_ROOT = ROOT / "backend/app/gateway"
if _REAL_GATEWAY_ROOT.exists():
    AUTH_PATH = _REAL_GATEWAY_ROOT / "middleware/auth.py"
    PAPER_RAG_ROUTER_PATH = _REAL_GATEWAY_ROOT / "routers/paper_rag.py"
    METRICS_ROUTER_PATH = _REAL_GATEWAY_ROOT / "routers/metrics.py"
else:
    _INTEGRATION_ROOT = REPO_ROOT / "docs/integration"
    AUTH_PATH = _INTEGRATION_ROOT / "middleware/gateway/auth.py"
    PAPER_RAG_ROUTER_PATH = _INTEGRATION_ROOT / "router/paper_rag.py"
    METRICS_ROUTER_PATH = _INTEGRATION_ROOT / "router/metrics.py"


def _load(mod_name: str, path: Path):
    """Load a module by file path (avoids importing the whole backend pkg)."""
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_app():
    """Build a minimal FastAPI app with paper_rag router + auth middleware."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    auth = _load("auth_mod", AUTH_PATH)
    pr = _load("pr_mod", PAPER_RAG_ROUTER_PATH)
    sys.modules["app.gateway.routers.paper_rag"] = pr
    metrics = _load("metrics_mod", METRICS_ROUTER_PATH)

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(pr.router)
    app.include_router(metrics.router)
    app.add_middleware(auth.BetterAuthMiddleware)
    return app, auth


def _fake_flag_embedding_find_spec(name: str):
    return object() if name == "FlagEmbedding" else None


def test_routes_registered():
    """Verify core paper_rag endpoints + /metrics are registered."""
    _make_app()
    pr = sys.modules["pr_mod"]
    metrics = sys.modules["metrics_mod"]
    paths = {
        r.path
        for router in (pr.router, metrics.router)
        for r in router.routes
        if hasattr(r, "path")
    }
    assert "/metrics" in paths
    for p in (
        "/api/paper_rag/qa",
        "/api/paper_rag/qa/sync",
        "/api/paper_rag/papers",
        "/api/paper_rag/papers/ingest",
        "/api/paper_rag/discovery/run",
        "/api/paper_rag/discovery/runs",
        "/api/paper_rag/discovery/runs/{run_id}",
        "/api/paper_rag/discovery/candidates/{candidate_id}/ingest",
        "/api/paper_rag/knowledge/builds",
        "/api/paper_rag/wiki/{paper_id}",
    ):
        assert p in paths, f"missing route: {p}"


def test_metrics_endpoint_bypasses_auth():
    """/metrics must NOT require a session cookie (ops endpoint)."""
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = False
    c = TestClient(app)
    r = c.get("/metrics")
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:100]}"


def test_openapi_endpoint_bypasses_auth():
    """/openapi.json must be accessible (so /docs UI works pre-login)."""
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = False
    c = TestClient(app)
    r = c.get("/openapi.json")
    assert r.status_code == 200


def test_paper_rag_endpoints_require_auth():
    """All paper_rag endpoints return 401 without a session cookie."""
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = False
    c = TestClient(app)
    r = c.get("/api/paper_rag/papers")
    assert r.status_code == 401
    assert "Missing session" in r.text or "Authentication" in r.text


def test_paper_rag_papers_dev_mode():
    """In DEERFLOW_AUTH_DISABLED mode, /papers returns 200 with system user_id."""
    os.environ["PAPER_RAG_CONFIG"] = str(REPO_ROOT / "config" / "local.yaml")
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "system"
    c = TestClient(app)
    r = c.get("/api/paper_rag/papers")
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    if data:
        # If there are papers, verify schema
        sample = data[0]
        for required in ("paper_id", "title", "n_chunks"):
            assert required in sample, f"missing field in response: {required}"


def test_runtime_status_exposes_wiki_runtime_state(monkeypatch):
    """Runtime status should make wiki activation visible to the product."""
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    pr = sys.modules["pr_mod"]
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "system"

    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_cfg = _Obj(
        paths=_Obj(sqlite_path="missing.sqlite"),
        llm=_Obj(base_url="https://llm.example.test/v1", api_key="sk-test", chat_model="model"),
        wiki=_Obj(enabled=True),
        qdrant=_Obj(collection_chunks="paper_chunks"),
    )
    monkeypatch.setattr(pr, "_load_paper_rag_config", lambda: fake_cfg)
    monkeypatch.setattr(pr.importlib.util, "find_spec", _fake_flag_embedding_find_spec)
    monkeypatch.setattr(pr, "_count_sqlite_papers", lambda _path: 1)
    monkeypatch.setattr(pr, "_count_qdrant_points", lambda _collection: (42, None))

    r = TestClient(app).get("/api/paper_rag/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["wiki_enabled"] is True
    assert data["wiki_available"] is True
    assert data["wiki_status"] == "enabled"
    assert data["wiki_reason"] is None


def test_runtime_status_reports_wiki_disabled(monkeypatch):
    """wiki.enabled=false should be visible as an ops kill switch."""
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    pr = sys.modules["pr_mod"]
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "system"

    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_cfg = _Obj(
        paths=_Obj(sqlite_path="missing.sqlite"),
        llm=_Obj(base_url="https://llm.example.test/v1", api_key="sk-test", chat_model="model"),
        wiki=_Obj(enabled=False),
        qdrant=_Obj(collection_chunks="paper_chunks"),
    )
    monkeypatch.setattr(pr, "_load_paper_rag_config", lambda: fake_cfg)
    monkeypatch.setattr(pr.importlib.util, "find_spec", _fake_flag_embedding_find_spec)
    monkeypatch.setattr(pr, "_count_sqlite_papers", lambda _path: 1)
    monkeypatch.setattr(pr, "_count_qdrant_points", lambda _collection: (42, None))

    r = TestClient(app).get("/api/paper_rag/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["wiki_enabled"] is False
    assert data["wiki_available"] is False
    assert data["wiki_status"] == "disabled"
    assert "disabled" in data["wiki_reason"]


def test_runtime_status_reports_wiki_unavailable_without_llm(monkeypatch):
    """An enabled wiki without LLM credentials should surface as unavailable."""
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    pr = sys.modules["pr_mod"]
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "system"

    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_cfg = _Obj(
        paths=_Obj(sqlite_path="missing.sqlite"),
        llm=_Obj(base_url=None, api_key=None, chat_model=None),
        wiki=_Obj(enabled=True),
        qdrant=_Obj(collection_chunks="paper_chunks"),
    )
    monkeypatch.setattr(pr, "_load_paper_rag_config", lambda: fake_cfg)
    monkeypatch.setattr(pr.importlib.util, "find_spec", _fake_flag_embedding_find_spec)
    monkeypatch.setattr(pr, "_count_sqlite_papers", lambda _path: 1)
    monkeypatch.setattr(pr, "_count_qdrant_points", lambda _collection: (42, None))

    r = TestClient(app).get("/api/paper_rag/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["wiki_enabled"] is True
    assert data["wiki_available"] is False
    assert data["wiki_status"] == "unavailable"
    assert "LLM" in data["wiki_reason"]


def test_qa_sync_forwards_user_conversation_and_resolved_question(monkeypatch):
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "alice"
    captured = {}

    def fake_answer(
        question,
        *,
        paper_ids=None,
        conversation_id=None,
        user_id="system",
        resolved_question=None,
    ):
        captured.update(
            {
                "question": question,
                "paper_ids": paper_ids,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "resolved_question": resolved_question,
            }
        )
        return {
            "answer": "ok",
            "citations": [],
            "chunks": [],
            "trace": {
                "trace_id": "trace-1",
                "abstain": {},
                "query_resolution": {"effective_question": resolved_question},
            },
        }

    monkeypatch.setitem(sys.modules, "paper_rag.rag.qa_agentic", type("M", (), {"answer": fake_answer}))

    response = TestClient(app).post(
        "/api/paper_rag/qa/sync",
        json={
            "question": "raw",
            "paper_ids": ["p1"],
            "conversation_id": "thread-1",
            "resolved_question": "effective",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "question": "raw",
        "paper_ids": ["p1"],
        "conversation_id": "thread-1",
        "user_id": "alice",
        "resolved_question": "effective",
    }
    assert response.json()["trace"]["query_resolution"]["effective_question"] == "effective"


def test_qa_stream_forwards_user_conversation_and_resolved_question(monkeypatch):
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "alice"
    captured = {}

    def fake_stream(
        question,
        *,
        paper_ids=None,
        conversation_id=None,
        user_id="system",
        resolved_question=None,
    ):
        captured.update(
            {
                "question": question,
                "paper_ids": paper_ids,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "resolved_question": resolved_question,
            }
        )
        yield {
            "event": "done",
            "data": {
                "answer": "ok",
                "citations": [],
                "query_resolution": {"effective_question": resolved_question},
            },
        }

    monkeypatch.setitem(sys.modules, "paper_rag.rag.qa_stream", type("M", (), {"stream_answer": fake_stream}))

    with TestClient(app).stream(
        "POST",
        "/api/paper_rag/qa",
        json={
            "question": "raw",
            "paper_ids": ["p1"],
            "conversation_id": "thread-1",
            "resolved_question": "effective",
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert captured == {
        "question": "raw",
        "paper_ids": ["p1"],
        "conversation_id": "thread-1",
        "user_id": "alice",
        "resolved_question": "effective",
    }
    assert "effective" in body


def test_knowledge_builds_dev_mode_returns_stage_status(tmp_path):
    """Knowledge Builder should expose ingest/index/wiki status for the UI."""
    import json
    import sqlite3

    from fastapi.testclient import TestClient

    db = tmp_path / "knowledge.sqlite"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE paper (
            paper_id TEXT PRIMARY KEY,
            title TEXT,
            arxiv_id TEXT,
            status TEXT,
            error TEXT,
            user_id TEXT,
            created_at TEXT
        );
        CREATE TABLE chunk (
            chunk_id TEXT PRIMARY KEY,
            paper_id TEXT,
            text TEXT
        );
        CREATE TABLE ingest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT,
            step TEXT,
            status TEXT,
            started_at TEXT,
            finished_at TEXT,
            error TEXT
        );
        CREATE TABLE wiki_entries (
            entry_id TEXT PRIMARY KEY,
            name TEXT,
            key_papers_json TEXT,
            definition TEXT,
            updated_at TEXT
        );
        CREATE TABLE wiki_consumption_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT,
            paper_id TEXT,
            entry_id TEXT,
            entry_name TEXT,
            wiki_fingerprint TEXT,
            question TEXT,
            created_at TEXT
        );
        CREATE TABLE wiki_review_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            concept TEXT,
            concept_norm TEXT,
            paper_id TEXT,
            question TEXT,
            reason TEXT,
            status TEXT,
            payload_json TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO paper VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("arxiv:2310.11511", "Self-RAG", "2310.11511", "done", None, "system", "2026-01-01"),
    )
    con.executemany(
        "INSERT INTO chunk VALUES (?, ?, ?)",
        [("c1", "arxiv:2310.11511", "text"), ("c2", "arxiv:2310.11511", "text")],
    )
    con.executemany(
        "INSERT INTO ingest_runs "
        "(paper_id, step, status, finished_at, error) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("arxiv:2310.11511", "parse", "ok", "2026-01-01", None),
            ("arxiv:2310.11511", "chunk", "ok", "2026-01-01", None),
            ("arxiv:2310.11511", "embed", "ok", "2026-01-01", None),
            ("arxiv:2310.11511", "index", "ok", "2026-01-01", None),
        ],
    )
    con.execute(
        "INSERT INTO wiki_entries VALUES (?, ?, ?, ?, ?)",
        (
            "self-rag",
            "Self-RAG",
            json.dumps(["arxiv:2310.11511"]),
            "Self-RAG concept note.",
            "2026-01-01",
        ),
    )
    con.execute(
        "INSERT INTO wiki_consumption_events "
        "(trace_id, paper_id, entry_id, entry_name, wiki_fingerprint, question, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "trace-1",
            "arxiv:2310.11511",
            "self-rag",
            "Self-RAG",
            "self-rag:1",
            "What is it?",
            "2026-01-01",
        ),
    )
    con.execute(
        "INSERT INTO wiki_review_queue "
        "(event_type, concept, concept_norm, paper_id, question, reason, "
        "status, payload_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "qa_weak_evidence",
            "Self-RAG",
            "selfrag",
            "arxiv:2310.11511",
            "What is it?",
            "weak_evidence",
            "pending",
            "{}",
            "2026-01-01",
            "2026-01-01",
        ),
    )
    con.commit()
    con.close()

    app, auth = _make_app()
    pr = sys.modules["pr_mod"]
    pr._resolve_sqlite_path = lambda: str(db)
    pr._count_qdrant_points = lambda collection: (None, "qdrant offline")
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "system"

    r = TestClient(app).get("/api/paper_rag/knowledge/builds")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data[0]["paper_id"] == "arxiv:2310.11511"
    assert data[0]["n_chunks"] == 2
    assert data[0]["wiki_status"] == "ready"
    assert data[0]["wiki_consumed"] is True
    assert data[0]["wiki_review_needed"] is True
    assert data[0]["qdrant_status"] == "offline"
    stages = {stage["name"]: stage["status"] for stage in data[0]["stages"]}
    assert stages == {
        "fetch": "ok",
        "parse": "ok",
        "chunk": "ok",
        "embed": "ok",
        "index": "ok",
        "wiki": "ready",
    }


def test_knowledge_builds_reports_wiki_disabled_when_no_entry(tmp_path, monkeypatch):
    """A disabled wiki kill switch should not appear as an unexplained empty wiki."""
    import sqlite3

    from fastapi.testclient import TestClient

    db = tmp_path / "knowledge-disabled.sqlite"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE paper (
            paper_id TEXT PRIMARY KEY,
            title TEXT,
            arxiv_id TEXT,
            status TEXT,
            error TEXT,
            user_id TEXT,
            created_at TEXT
        );
        CREATE TABLE chunk (
            chunk_id TEXT PRIMARY KEY,
            paper_id TEXT,
            text TEXT
        );
        CREATE TABLE wiki_entries (
            entry_id TEXT PRIMARY KEY,
            name TEXT,
            key_papers_json TEXT,
            definition TEXT,
            updated_at TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO paper VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "arxiv:disabled",
            "Disabled Wiki Paper",
            "0000.00001",
            "done",
            None,
            "system",
            "2026-01-01",
        ),
    )
    con.execute("INSERT INTO chunk VALUES (?, ?, ?)", ("c1", "arxiv:disabled", "text"))
    con.commit()
    con.close()

    app, auth = _make_app()
    pr = sys.modules["pr_mod"]
    pr._resolve_sqlite_path = lambda: str(db)
    pr._count_qdrant_points = lambda collection: (1, None)
    monkeypatch.setattr(pr, "_wiki_runtime_state", lambda: {
        "wiki_enabled": False,
        "wiki_available": False,
        "wiki_status": "disabled",
        "wiki_reason": "wiki disabled by configuration",
    })
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "system"

    r = TestClient(app).get("/api/paper_rag/knowledge/builds")
    assert r.status_code == 200, r.text
    row = r.json()[0]
    assert row["wiki_status"] == "disabled"
    assert row["stages"][-1]["name"] == "wiki"
    assert row["stages"][-1]["status"] == "disabled"
    assert "disabled" in row["warnings"][0]


def test_knowledge_builds_reports_wiki_unavailable_without_llm(tmp_path, monkeypatch):
    """Missing LLM credentials should be visible in Knowledge Builder."""
    import sqlite3

    from fastapi.testclient import TestClient

    db = tmp_path / "knowledge-unavailable.sqlite"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE paper (
            paper_id TEXT PRIMARY KEY,
            title TEXT,
            arxiv_id TEXT,
            status TEXT,
            error TEXT,
            user_id TEXT,
            created_at TEXT
        );
        CREATE TABLE chunk (
            chunk_id TEXT PRIMARY KEY,
            paper_id TEXT,
            text TEXT
        );
        CREATE TABLE wiki_entries (
            entry_id TEXT PRIMARY KEY,
            name TEXT,
            key_papers_json TEXT,
            definition TEXT,
            updated_at TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO paper VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("arxiv:no-llm", "No LLM Paper", "0000.00002", "done", None, "system", "2026-01-01"),
    )
    con.execute("INSERT INTO chunk VALUES (?, ?, ?)", ("c1", "arxiv:no-llm", "text"))
    con.commit()
    con.close()

    app, auth = _make_app()
    pr = sys.modules["pr_mod"]
    pr._resolve_sqlite_path = lambda: str(db)
    pr._count_qdrant_points = lambda collection: (1, None)
    monkeypatch.setattr(pr, "_wiki_runtime_state", lambda: {
        "wiki_enabled": True,
        "wiki_available": False,
        "wiki_status": "unavailable",
        "wiki_reason": "LLM config missing: OPENAI_BASE_URL, OPENAI_API_KEY, CHAT_MODEL",
    })
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "system"

    r = TestClient(app).get("/api/paper_rag/knowledge/builds")
    assert r.status_code == 200, r.text
    row = r.json()[0]
    assert row["wiki_status"] == "unavailable"
    assert row["stages"][-1]["status"] == "unavailable"
    assert any("LLM config missing" in warning for warning in row["warnings"])


def test_touch_paper_access_extracts_unique_ids(tmp_path=None):
    """P0-1 / ADR-0018: _touch_paper_access dedups paper_ids and survives errors."""
    import tempfile

    # Isolate the SQLite file: paper_access._resolve_path delegates to
    # feedback.store._resolve_path, so we monkey-patch THAT one — and restore.
    from paper_rag.feedback import store as feedback_store
    from paper_rag.proactive import paper_access

    tmp_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp_db.close()
    original_resolve = feedback_store._resolve_path
    feedback_store._resolve_path = lambda: Path(tmp_db.name)
    try:
        _, _ = _make_app()
        pr = sys.modules["pr_mod"]
        chunks = [
            {"paper_id": "arxiv:1111", "chunk_id": "c1"},
            {"paper_id": "arxiv:1111", "chunk_id": "c2"},  # dup paper, kept once
            {"paper_id": "arxiv:2222", "chunk_id": "c3"},
            {"paper_id": None, "chunk_id": "c4"},          # None tolerated
            {},                                             # missing key tolerated
        ]
        pr._touch_paper_access("alice", chunks)

        rows = paper_access.stale_for_user("alice", older_than_days=-1)  # all
        pids = sorted(r.get("paper_id") for r in rows)
        assert pids == ["arxiv:1111", "arxiv:2222"], pids
    finally:
        feedback_store._resolve_path = original_resolve
        os.unlink(tmp_db.name)


def test_touch_paper_access_noop_on_missing_inputs():
    """Empty user_id or empty chunks must not raise and must not write."""
    _, _ = _make_app()
    pr = sys.modules["pr_mod"]
    pr._touch_paper_access("", [{"paper_id": "x"}])  # no user_id
    pr._touch_paper_access("alice", [])              # no chunks
    pr._touch_paper_access("alice", None)            # type-tolerant
    # If we got here, no exception was raised. Pass.


def test_proactive_endpoints_require_auth():
    """P0-3: every /subscriptions /inbox /proactive endpoint must 401 unauthed."""
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = False
    c = TestClient(app)
    cases = [
        ("GET",    "/api/paper_rag/subscriptions"),
        ("POST",   "/api/paper_rag/subscriptions"),
        ("DELETE", "/api/paper_rag/subscriptions/1"),
        ("PATCH",  "/api/paper_rag/subscriptions/1"),
        ("GET",    "/api/paper_rag/inbox"),
        ("GET",    "/api/paper_rag/inbox/stream"),
        ("POST",   "/api/paper_rag/inbox/1/read"),
        ("POST",   "/api/paper_rag/inbox/1/dismiss"),
        ("POST",   "/api/paper_rag/proactive/digest/run"),
        ("POST",   "/api/paper_rag/proactive/stale/run"),
    ]
    for method, path in cases:
        r = c.request(method, path, json={})
        assert r.status_code == 401, f"{method} {path} got {r.status_code}: {r.text[:80]}"


def test_proactive_user_isolation_in_dev_mode():
    """P0-3: in dev mode, two distinct user_ids never see each other's subs."""
    import tempfile

    from paper_rag.feedback import store as feedback_store

    tmp_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp_db.close()
    original = feedback_store._resolve_path
    feedback_store._resolve_path = lambda: Path(tmp_db.name)
    try:
        from fastapi.testclient import TestClient

        app, auth = _make_app()
        auth._AUTH_DISABLED = True

        # Round 1: alice adds a subscription
        auth._DEV_USER_ID = "alice"
        c = TestClient(app)
        r = c.post(
            "/api/paper_rag/subscriptions",
            json={"kind": "keyword", "value": "retrieval", "strength": "high"},
        )
        assert r.status_code in (200, 201), f"add: {r.status_code} {r.text[:120]}"
        r = c.get("/api/paper_rag/subscriptions")
        assert r.status_code == 200
        alice_subs = r.json()
        assert len(alice_subs) == 1
        assert alice_subs[0]["value"] == "retrieval"

        # Round 2: bob lists -> should be empty
        auth._DEV_USER_ID = "bob"
        c2 = TestClient(app)
        r = c2.get("/api/paper_rag/subscriptions")
        assert r.status_code == 200
        bob_subs = r.json()
        assert bob_subs == [], f"user_id leak! bob saw: {bob_subs}"
    finally:
        feedback_store._resolve_path = original
        os.unlink(tmp_db.name)


def main():
    """Run all tests without pytest."""
    tests = [
        test_routes_registered,
        test_metrics_endpoint_bypasses_auth,
        test_openapi_endpoint_bypasses_auth,
        test_paper_rag_endpoints_require_auth,
        test_paper_rag_papers_dev_mode,
        test_touch_paper_access_extracts_unique_ids,
        test_touch_paper_access_noop_on_missing_inputs,
        test_proactive_endpoints_require_auth,
        test_proactive_user_isolation_in_dev_mode,
    ]
    ok = 0
    fail = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: AssertionError: {e}")
            fail += 1
        except Exception as e:
            import traceback
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            fail += 1
    print(f"\n{ok}/{ok+fail} passed")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
