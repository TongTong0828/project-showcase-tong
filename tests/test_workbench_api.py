from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def _settings(tmp_path: Path):
    from paper_rag.workbench.settings import WorkbenchSettings

    return WorkbenchSettings(
        actor_id="workbench",
        toolset="research",
        dsh_url="http://127.0.0.1:3080",
        credentials_path=tmp_path / ".credentials.yaml",
        artifact_root=tmp_path / "artifacts",
        import_root=tmp_path / "imports",
        openai_base_url="https://api.deepseek.com",
        chat_model="deepseek-v4-flash",
        small_model="deepseek-v4-flash",
    )


def test_health_reports_workbench_model_and_dsh_url(tmp_path):
    from paper_rag.workbench.api import create_app

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=lambda *_args: {}))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "paper-rag-workbench",
        "dsh_url": "http://127.0.0.1:3080",
        "models": {
            "chat_model": "deepseek-v4-flash",
            "small_model": "deepseek-v4-flash",
        },
    }


def test_status_endpoint_returns_mcp_structured_content(tmp_path):
    from paper_rag.workbench.api import create_app

    seen: dict[str, Any] = {}

    def fake_call_tool(name, args, ctx):
        seen.update(
            name=name,
            args=args,
            actor_id=ctx.actor_id,
            toolset=ctx.config.toolset,
            conversation_id=ctx.conversation_id,
            tool_call_id=ctx.tool_call_id,
        )
        return {
            "structuredContent": {
                "ok": True,
                "tool": "paper_status",
                "evidence_role": "metadata",
                "warnings": [],
                "data": {
                    "sqlite": {"paper_count": 2, "chunk_count": 30, "available": True},
                    "llm": {"chat_model": "deepseek-v4-flash", "configured": True},
                },
            }
        }

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["tool"] == "paper_status"
    assert response.json()["data"]["sqlite"]["paper_count"] == 2
    assert seen == {
        "name": "paper_status",
        "args": {},
        "actor_id": "workbench",
        "toolset": "research",
        "conversation_id": "workbench",
        "tool_call_id": "workbench-paper_status",
    }


def test_status_reports_credential_source_without_secret(tmp_path, monkeypatch):
    from paper_rag.workbench.api import create_app

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret-value")

    def fake_call_tool(name, args, ctx):
        return {
            "structuredContent": {
                "ok": True,
                "tool": "paper_status",
                "evidence_role": "metadata",
                "warnings": [],
                "data": {"llm": {"chat_model": "deepseek-v4-flash", "configured": True}},
            }
        }

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    payload = client.get("/api/status").json()

    assert payload["data"]["workbench"]["credentials"] == {
        "configured": True,
        "source": "env",
        "writable": False,
    }
    assert "sk-test-secret-value" not in str(payload)


def test_candidate_ingest_rejects_missing_approval(tmp_path):
    from paper_rag.workbench.api import create_app

    calls = []

    def fake_call_tool(name, args, ctx):
        calls.append((name, args, ctx))
        return {"structuredContent": {"ok": True, "tool": name, "data": {}}}

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.post("/api/ingest/candidates", json={"candidate_ids": [11]})

    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "APPROVAL_REQUIRED"
    assert calls == []


def test_candidate_ingest_passes_request_boundary_after_approval(tmp_path):
    from paper_rag.workbench.api import create_app

    seen = {}

    def fake_call_tool(name, args, ctx):
        seen.update(
            name=name,
            args=args,
            request_boundary_id=ctx.request_boundary_id,
            conversation_id=ctx.conversation_id,
            tool_call_id=ctx.tool_call_id,
        )
        return {
            "structuredContent": {
                "ok": True,
                "tool": "discovery_candidate_ingest",
                "evidence_role": "metadata",
                "warnings": [],
                "data": {
                    "results": [
                        {"candidate_id": 11, "paper_id": "paper-11", "status": "ingested"}
                    ]
                },
            }
        }

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.post(
        "/api/ingest/candidates",
        json={
            "candidate_ids": [11],
            "force": False,
            "approval": {
                "approved": True,
                "operation": "discovery_candidate_ingest",
                "candidate_ids": [11],
                "destination": "real-library",
                "side_effects": ["write indexed paper and chunks"],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["results"][0]["paper_id"] == "paper-11"
    assert seen["name"] == "discovery_candidate_ingest"
    assert seen["args"] == {"candidate_ids": [11], "force": False}
    assert seen["request_boundary_id"].startswith("workbench-discovery_candidate_ingest-")
    assert seen["conversation_id"] == "workbench"
    assert seen["tool_call_id"] == "workbench-discovery_candidate_ingest"


def test_workbench_module_exports_app_factory():
    import paper_rag.workbench as workbench

    assert callable(workbench.create_app)
    assert workbench.WorkbenchSettings().chat_model == "deepseek-v4-flash"


def test_workbench_module_entrypoint_help_runs():
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [sys.executable, "-m", "paper_rag.workbench", "--help"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    assert "Run the local Paper RAG Workbench API" in result.stdout


def test_workbench_launcher_env_defaults(tmp_path):
    from scripts.start_workbench import build_launcher_env

    env = build_launcher_env(tmp_path, {"CHAT_MODEL": "legacy-model"})

    assert env["OPENAI_BASE_URL"] == "https://api.deepseek.com"
    assert env["CHAT_MODEL"] == "deepseek-v4-flash"
    assert env["SMALL_MODEL"] == "deepseek-v4-flash"
    assert env["PAPER_RAG_DSH_CREDENTIALS_PATH"] == str(
        tmp_path / "data/runtime/deepseek-harness/credentials/.credentials.yaml"
    )


def test_workbench_launcher_loads_dsh_credentials_for_core_llm(tmp_path):
    from scripts.start_workbench import build_launcher_env

    credentials = tmp_path / "data/runtime/deepseek-harness/credentials/.credentials.yaml"
    credentials.parent.mkdir(parents=True)
    credentials.write_text(
        "DEEPSEEK_API_KEY: test-deepseek-key\nOPENAI_API_KEY: test-openai-key\n",
        encoding="utf-8",
    )

    env = build_launcher_env(tmp_path, {})

    assert env["OPENAI_API_KEY"] == "test-openai-key"
    assert env["DEEPSEEK_API_KEY"] == "test-deepseek-key"


def test_index_health_endpoint_uses_read_only_builder(tmp_path):
    from paper_rag.workbench.api import create_app

    def fake_index_health(settings):
        assert settings.chat_model == "deepseek-v4-flash"
        return {
            "status": "degraded",
            "sqlite": {
                "available": True,
                "paper_count": 8,
                "chunk_count": 345,
                "fts_available": True,
            },
            "qdrant": {
                "configured": True,
                "mode": "server",
                "reachable": False,
                "degraded_reason": "connection refused",
            },
            "retrieval": {
                "dense_available": False,
                "sparse_available": True,
                "hybrid_available": True,
            },
            "llm": {
                "configured": True,
                "chat_model": "deepseek-v4-flash",
                "base_url_host": "api.deepseek.com",
                "credential_source": "file",
            },
            "corpus_quality": {
                "duplicate_chunk_count": 1,
                "parser_artifact_count": 1,
                "missing_section_count": 0,
                "samples": [],
            },
            "warnings": ["Dense retrieval is unavailable; sparse fallback is active."],
        }

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            index_health_fn=fake_index_health,
        )
    )

    response = client.get("/api/health/index")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["llm"]["chat_model"] == "deepseek-v4-flash"
    assert "sk-" not in str(payload)


def test_paper_detail_endpoint_returns_404_for_missing_paper(tmp_path):
    from paper_rag.workbench.api import create_app

    class FakeReadStore:
        def paper_detail(self, paper_id):
            assert paper_id == "arxiv:missing"
            return None

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            read_store=FakeReadStore(),
        )
    )

    response = client.get("/api/papers/arxiv:missing")

    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "NOT_FOUND"


def test_chunk_detail_endpoint_redacts_storage_paths(tmp_path):
    from paper_rag.workbench.api import create_app

    class FakeReadStore:
        def chunk_detail(self, chunk_id):
            assert chunk_id == "chunk-a"
            return {
                "chunk": {
                    "chunk_id": "chunk-a",
                    "paper_id": "arxiv:2310.11511",
                    "text": "Evidence text.",
                    "warnings": [],
                },
                "paper": {"paper_id": "arxiv:2310.11511", "title": "Self-RAG"},
                "neighbors": [],
            }

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            read_store=FakeReadStore(),
        )
    )

    payload = client.get("/api/chunks/chunk-a").json()

    assert payload["chunk"]["chunk_id"] == "chunk-a"
    assert "source_path" not in str(payload)
    assert "asset_path" not in str(payload)


def test_dsh_handoff_builds_prompt_without_calling_tools(tmp_path):
    from paper_rag.workbench.api import create_app

    calls = []

    def fake_call_tool(name, args, ctx):
        calls.append((name, args, ctx))
        return {"structuredContent": {"ok": True, "tool": name, "data": {}}}

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.post(
        "/api/dsh/handoff",
        json={
            "question": "Self-RAG 的核心理念是什么？",
            "paper_ids": ["arxiv:2310.11511"],
            "chunk_ids": ["chunk-a"],
            "source": "ask",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dsh_url"] == "http://127.0.0.1:3080"
    assert "arxiv:2310.11511" in payload["prompt"]
    assert "chunk-a" in payload["prompt"]
    assert "证据引用" in payload["prompt"]
    assert calls == []


def test_qa_stream_endpoint_frames_sse_events(tmp_path):
    from paper_rag.workbench.api import create_app

    async def fake_stream_answer(
        question,
        *,
        paper_ids=None,
        conversation_id=None,
        user_id="system",
        resolved_question=None,
    ):
        assert question == "What is Self-RAG?"
        assert paper_ids == ["arxiv:2310.11511"]
        assert conversation_id == "workbench"
        assert user_id == "workbench"
        yield {
            "event": "start",
            "data": {
                "trace_id": "trace1234567890",
                "stage": "start",
                "status": "completed",
                "summary": "Started Paper RAG QA",
            },
        }
        yield {
            "event": "answer_chunk",
            "data": {
                "trace_id": "trace1234567890",
                "stage": "answer",
                "text": "Self-RAG",
            },
        }
        yield {
            "event": "done",
            "data": {
                "trace_id": "trace1234567890",
                "stage": "done",
                "status": "completed",
                "summary": "Paper RAG QA complete",
                "answer": "Self-RAG",
                "citations": [],
                "chunks": [],
                "abstain": {},
                "n_chunks": 0,
                "paper_ids": ["arxiv:2310.11511"],
                "query_resolution": {"effective_question": "What is Self-RAG?"},
            },
        }

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            stream_answer_fn=fake_stream_answer,
        )
    )

    with client.stream(
        "POST",
        "/api/qa/stream",
        json={
            "question": "What is Self-RAG?",
            "paper_ids": ["arxiv:2310.11511"],
            "top_k": 8,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: start" in body
    assert '"stage": "answer"' in body
    assert "event: done" in body
    assert "trace1234567890" in body


def test_qa_without_project_context_preserves_previous_tool_args(tmp_path):
    from paper_rag.workbench.api import create_app

    seen: dict[str, Any] = {}

    def fake_call_tool(name, args, ctx):
        seen.update(name=name, args=args, conversation_id=ctx.conversation_id)
        return {
            "structuredContent": {
                "ok": True,
                "tool": "paper_qa",
                "evidence_role": "indexed_chunks",
                "data": {
                    "answer": "Self-RAG retrieves.",
                    "citations": ["chunk-self-rag-1"],
                    "chunks": [],
                    "abstain": {"decision": "answer"},
                },
            }
        }

    client = TestClient(create_app(_settings(tmp_path), call_tool_fn=fake_call_tool))

    response = client.post(
        "/api/qa",
        json={
            "question": "What is Self-RAG?",
            "paper_ids": ["arxiv:2310.11511"],
            "resolved_question": "What is Self-RAG?",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    assert seen == {
        "name": "paper_qa",
        "args": {
            "question": "What is Self-RAG?",
            "paper_ids": ["arxiv:2310.11511"],
            "resolved_question": "What is Self-RAG?",
            "top_k": 5,
        },
        "conversation_id": "workbench",
    }
    assert "context_policy" not in response.json()["data"]
    assert "note_refs" not in response.json()["data"]


def test_scoped_qa_adds_project_context_without_mixing_note_citations(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    seen: dict[str, Any] = {}
    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        quote_snapshot="SELF-RAG retrieves passages on demand.",
        source="ask",
    )
    note = store.upsert_note(
        project["project_id"],
        "chunk",
        "chunk-self-rag-1",
        "User note: compare the reflection token framing.",
    )

    def fake_call_tool(name, args, ctx):
        seen.update(name=name, args=args)
        return {
            "structuredContent": {
                "ok": True,
                "tool": "paper_qa",
                "evidence_role": "indexed_chunks",
                "data": {
                    "answer": "Self-RAG retrieves and critiques generations.",
                    "citations": ["chunk-self-rag-1"],
                    "chunks": [{"chunk_id": "chunk-self-rag-1"}],
                    "abstain": {"decision": "answer"},
                },
            }
        }

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=fake_call_tool,
            workspace_store=store,
        )
    )

    response = client.post(
        "/api/qa",
        json={
            "question": "What is the core idea?",
            "paper_ids": ["arxiv:external"],
            "project_id": project["project_id"],
            "context_policy": {
                "include_pinned_evidence": True,
                "include_notes": True,
                "restrict_to_project_papers": True,
            },
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert seen["name"] == "paper_qa"
    assert seen["args"]["paper_ids"] == ["arxiv:external", "arxiv:2310.11511"]
    assert "Pinned evidence" in seen["args"]["question"]
    assert "User notes" in seen["args"]["question"]
    assert "not paper evidence" in seen["args"]["question"]
    assert "chunk-self-rag-1" in seen["args"]["question"]
    assert payload["data"]["citations"] == ["chunk-self-rag-1"]
    assert payload["data"]["note_refs"] == [note["note_id"]]
    assert note["note_id"] not in payload["data"]["citations"]
    assert payload["data"]["context_policy"] == {
        "include_pinned_evidence": True,
        "include_notes": True,
        "restrict_to_project_papers": True,
    }


def test_scoped_qa_stream_enriches_done_event_and_restricts_papers(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    seen: dict[str, Any] = {}
    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.upsert_note(project["project_id"], "paper", "arxiv:2310.11511", "Local reading note.")

    async def fake_stream_answer(
        question,
        *,
        paper_ids=None,
        conversation_id=None,
        user_id="system",
        resolved_question=None,
    ):
        seen.update(
            question=question,
            paper_ids=paper_ids,
            conversation_id=conversation_id,
            user_id=user_id,
            resolved_question=resolved_question,
        )
        yield {
            "event": "done",
            "data": {
                "trace_id": "trace-scoped",
                "stage": "done",
                "status": "completed",
                "answer": "Self-RAG",
                "citations": [],
                "chunks": [],
                "abstain": {},
            },
        }

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            workspace_store=store,
            stream_answer_fn=fake_stream_answer,
        )
    )

    with client.stream(
        "POST",
        "/api/qa/stream",
        json={
            "question": "What is Self-RAG?",
            "project_id": project["project_id"],
            "context_policy": {
                "include_pinned_evidence": False,
                "include_notes": True,
                "restrict_to_project_papers": True,
            },
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert seen["paper_ids"] == ["arxiv:2310.11511"]
    assert "User notes" in seen["question"]
    assert "event: done" in body
    assert '"note_refs"' in body
    assert '"context_policy"' in body
    assert '"restrict_to_project_papers": true' in body


def test_project_api_creates_project_and_saves_research_objects(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            workspace_store=store,
        )
    )

    created = client.post(
        "/api/projects",
        json={"name": "Self-RAG 调研", "description": "project"},
    ).json()
    project_id = created["project"]["project_id"]

    paper = client.post(
        f"/api/projects/{project_id}/papers",
        json={
            "paper_id": "arxiv:2310.11511",
            "title_snapshot": "Self-RAG",
            "source": "library",
        },
    ).json()
    evidence = client.post(
        f"/api/projects/{project_id}/evidence",
        json={
            "chunk_id": "chunk-self-rag-1",
            "paper_id": "arxiv:2310.11511",
            "quote_snapshot": "SELF-RAG retrieves passages on demand.",
            "source": "search",
        },
    ).json()
    note = client.post(
        f"/api/projects/{project_id}/notes",
        json={
            "target_type": "chunk",
            "target_id": "chunk-self-rag-1",
            "body": "local interpretation",
        },
    ).json()
    saved = client.post(
        f"/api/projects/{project_id}/questions",
        json={
            "question": "What is Self-RAG?",
            "answer": "It retrieves and critiques.",
            "citations": ["chunk-self-rag-1"],
            "chunk_ids": ["chunk-self-rag-1"],
            "trace_id": "trace-workbench-fixture",
            "abstain": {"decision": "answer"},
        },
    ).json()
    detail = client.get(f"/api/projects/{project_id}").json()

    assert created["project"]["name"] == "Self-RAG 调研"
    assert paper["paper"]["paper_id"] == "arxiv:2310.11511"
    assert evidence["evidence"]["chunk_id"] == "chunk-self-rag-1"
    assert note["note"]["body"] == "local interpretation"
    assert saved["question"]["citations"] == ["chunk-self-rag-1"]
    assert detail["summary"]["paper_count"] == 1
    assert detail["summary"]["evidence_count"] == 1
    assert "sk-" not in str(detail)


def test_project_api_archives_and_excludes_archived_projects(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            workspace_store=WorkspaceStore(tmp_path / "state.sqlite"),
        )
    )

    project_id = client.post("/api/projects", json={"name": "Archive me"}).json()["project"][
        "project_id"
    ]
    archived = client.post(f"/api/projects/{project_id}/archive").json()
    active_list = client.get("/api/projects").json()
    full_list = client.get("/api/projects?include_archived=true").json()

    assert archived["project"]["status"] == "archived"
    assert active_list["projects"] == []
    assert full_list["projects"][0]["project_id"] == project_id


def test_project_dsh_handoff_uses_project_context_without_calling_tools(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    calls = []
    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        "evidence excerpt",
        "ask",
    )
    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *args: calls.append(args),
            workspace_store=store,
        )
    )

    response = client.post(
        f"/api/projects/{project['project_id']}/dsh-handoff",
        json={"instruction": "Compare methods."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dsh_url"] == "http://127.0.0.1:3080"
    assert "Compare methods." in payload["prompt"]
    assert "chunk-self-rag-1" in payload["prompt"]
    assert calls == []


def test_compare_api_creates_evidence_first_matrix_without_calling_tools(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    calls = []
    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("RAG Compare")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.add_project_paper(project["project_id"], "arxiv:2005.11401", "RAG", "library")
    store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        quote_snapshot="SELF-RAG retrieves passages on demand.",
        source="search",
    )
    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *args: calls.append(args),
            workspace_store=store,
        )
    )

    response = client.post(
        f"/api/projects/{project['project_id']}/compare",
        json={
            "paper_ids": ["arxiv:2310.11511", "arxiv:2005.11401"],
            "dimensions": ["method", "limitation"],
        },
    )
    payload = response.json()
    runs = client.get(f"/api/projects/{project['project_id']}/compare-runs").json()
    loaded = client.get(
        f"/api/projects/{project['project_id']}/compare-runs/{payload['run']['run_id']}"
    ).json()

    assert response.status_code == 200
    assert payload["run"]["status"] == "degraded"
    assert len(payload["run"]["cells"]) == 4
    assert any(
        cell["evidence_chunk_ids"] == ["chunk-self-rag-1"]
        for cell in payload["run"]["cells"]
    )
    assert any(cell["summary"] == "No pinned evidence" for cell in payload["run"]["cells"])
    assert runs["runs"][0]["run_id"] == payload["run"]["run_id"]
    assert loaded["run"]["run_id"] == payload["run"]["run_id"]
    assert calls == []


def test_compare_dsh_handoff_previews_prompt_without_calling_tools(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    calls = []
    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("RAG Compare")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        quote_snapshot="SELF-RAG retrieves passages on demand.",
        source="search",
    )
    run = store.create_compare_run(project["project_id"], ["arxiv:2310.11511"], ["method"])
    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *args: calls.append(args),
            workspace_store=store,
        )
    )

    response = client.post(
        f"/api/projects/{project['project_id']}/compare-runs/{run['run_id']}/dsh-handoff"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dsh_url"] == "http://127.0.0.1:3080"
    assert "Compare run" in payload["prompt"]
    assert "chunk-self-rag-1" in payload["prompt"]
    assert calls == []


def test_compare_api_rejects_out_of_project_papers(tmp_path):
    from paper_rag.workbench.api import create_app
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("RAG Compare")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    client = TestClient(
        create_app(
            _settings(tmp_path),
            call_tool_fn=lambda *_args: {},
            workspace_store=store,
        )
    )

    response = client.post(
        f"/api/projects/{project['project_id']}/compare",
        json={
            "paper_ids": ["arxiv:2310.11511", "arxiv:outside"],
            "dimensions": ["method"],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "BAD_REQUEST"
