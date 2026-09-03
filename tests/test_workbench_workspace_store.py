from __future__ import annotations

from pathlib import Path


def test_workspace_store_creates_updates_archives_project(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")

    project = store.create_project("Self-RAG 调研", "evidence-first project")
    updated = store.update_project(
        project["project_id"],
        name="Self-RAG 深入调研",
        description="updated",
    )
    archived = store.archive_project(project["project_id"])

    assert project["status"] == "active"
    assert updated["name"] == "Self-RAG 深入调研"
    assert updated["description"] == "updated"
    assert archived["status"] == "archived"
    assert store.list_projects() == []
    assert store.list_projects(include_archived=True)[0]["project_id"] == project["project_id"]


def test_workspace_store_saves_papers_evidence_notes_and_questions(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研")

    paper = store.add_project_paper(
        project["project_id"],
        "arxiv:2310.11511",
        title_snapshot="Self-RAG",
        source="library",
    )
    duplicate = store.add_project_paper(
        project["project_id"],
        "arxiv:2310.11511",
        title_snapshot="Self-RAG duplicate",
        source="search",
    )
    pin = store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        quote_snapshot="SELF-RAG retrieves passages on demand.",
        source="search",
        score_snapshot=0.92,
        label="method",
    )
    note = store.upsert_note(
        project["project_id"],
        "chunk",
        "chunk-self-rag-1",
        "This is my reading note, not paper evidence.",
    )
    saved = store.save_question(
        project["project_id"],
        "What is Self-RAG?",
        "Self-RAG decides when to retrieve.",
        ["chunk-self-rag-1"],
        ["chunk-self-rag-1"],
        trace_id="trace-workbench-fixture",
        abstain={"decision": "answer"},
        context_policy={
            "include_pinned_evidence": True,
            "include_notes": True,
            "restrict_to_project_papers": True,
        },
    )
    snapshot = store.build_project_snapshot(project["project_id"])

    assert paper["paper_id"] == duplicate["paper_id"]
    assert pin["chunk_id"] == "chunk-self-rag-1"
    assert note["target_type"] == "chunk"
    assert saved["citations"] == ["chunk-self-rag-1"]
    assert saved["context_policy"] == {
        "include_pinned_evidence": True,
        "include_notes": True,
        "restrict_to_project_papers": True,
    }
    assert snapshot["summary"] == {
        "paper_count": 1,
        "evidence_count": 1,
        "note_count": 1,
        "saved_question_count": 1,
        "compare_run_count": 0,
    }


def test_workspace_store_dsh_handoff_prompt_is_secret_safe(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("Self-RAG 调研", "project description")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.pin_evidence(
        project["project_id"],
        "chunk-self-rag-1",
        "arxiv:2310.11511",
        quote_snapshot="evidence excerpt",
        source="ask",
    )
    store.upsert_note(project["project_id"], "project", project["project_id"], "local note")

    handoff = store.create_dsh_handoff(project["project_id"], "Compare methods.")

    assert "Self-RAG 调研" in handoff["prompt"]
    assert "chunk-self-rag-1" in handoff["prompt"]
    assert "local note" in handoff["prompt"]
    assert "sk-" not in handoff["prompt"]
    assert ".credentials" not in handoff["prompt"]


def test_workspace_store_creates_evidence_first_compare_run(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

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
    store.upsert_note(
        project["project_id"],
        "paper",
        "arxiv:2310.11511",
        "User note for interpretation.",
    )

    run = store.create_compare_run(
        project["project_id"],
        paper_ids=["arxiv:2310.11511", "arxiv:2005.11401"],
        dimensions=["method", "limitation"],
    )
    listed = store.list_compare_runs(project["project_id"])
    loaded = store.get_compare_run(project["project_id"], run["run_id"])

    assert run["status"] == "degraded"
    assert len(run["cells"]) == 4
    backed = [
        cell
        for cell in run["cells"]
        if cell["paper_id"] == "arxiv:2310.11511" and cell["dimension"] == "method"
    ][0]
    missing = [
        cell
        for cell in run["cells"]
        if cell["paper_id"] == "arxiv:2005.11401" and cell["dimension"] == "method"
    ][0]
    assert backed["evidence_chunk_ids"] == ["chunk-self-rag-1"]
    assert backed["note_ids"]
    assert backed["confidence"] == "evidence_backed"
    assert missing["summary"] == "No pinned evidence"
    assert missing["confidence"] == "missing"
    assert listed[0]["run_id"] == run["run_id"]
    assert loaded == run


def test_workspace_store_compare_handoff_prompt_includes_dimensions(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

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
    run = store.create_compare_run(
        project["project_id"],
        paper_ids=["arxiv:2310.11511"],
        dimensions=["method"],
    )

    handoff = store.create_compare_dsh_handoff(project["project_id"], run["run_id"])

    assert "Compare run" in handoff["prompt"]
    assert "method" in handoff["prompt"]
    assert "chunk-self-rag-1" in handoff["prompt"]
    assert "sk-" not in handoff["prompt"]


def test_workspace_store_rejects_cross_project_note_update(tmp_path: Path):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    project_a = store.create_project("Project A")
    project_b = store.create_project("Project B")
    note = store.upsert_note(project_a["project_id"], "project", project_a["project_id"], "A")

    try:
        store.upsert_note(
            project_b["project_id"],
            "project",
            project_b["project_id"],
            "B",
            note_id=note["note_id"],
        )
    except ValueError as exc:
        assert "does not belong" in str(exc)
    else:
        raise AssertionError("cross-project note update should fail")

    assert store.build_project_snapshot(project_a["project_id"])["notes"][0]["body"] == "A"
    assert store.build_project_snapshot(project_b["project_id"])["notes"] == []


def test_workspace_store_compare_requires_project_papers_and_uses_saved_qa_citations(
    tmp_path: Path,
):
    from paper_rag.workbench.workspace_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "state.sqlite")
    project = store.create_project("RAG Compare")
    store.add_project_paper(project["project_id"], "arxiv:2310.11511", "Self-RAG", "library")
    store.save_question(
        project["project_id"],
        "What is Self-RAG?",
        "It retrieves.",
        citations=["chunk-from-saved-qa"],
        chunk_ids=["chunk-from-saved-qa"],
        citation_papers={"chunk-from-saved-qa": "arxiv:2310.11511"},
    )

    try:
        store.create_compare_run(
            project["project_id"],
            paper_ids=["arxiv:2310.11511", "arxiv:outside"],
            dimensions=["method"],
        )
    except ValueError as exc:
        assert "not in project" in str(exc)
    else:
        raise AssertionError("out-of-project compare paper should fail")

    run = store.create_compare_run(
        project["project_id"],
        paper_ids=["arxiv:2310.11511"],
        dimensions=["method"],
    )

    assert run["cells"][0]["evidence_chunk_ids"] == ["chunk-from-saved-qa"]
    assert run["cells"][0]["confidence"] == "partial"
