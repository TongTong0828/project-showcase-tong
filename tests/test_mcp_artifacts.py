from __future__ import annotations

import importlib
import json
import os
import time
from pathlib import Path


def _ctx(tmp_path: Path, *, boundary: str | None = "boundary-1"):
    from paper_rag.mcp.context import McpRequestContext, McpServerConfig

    return McpRequestContext(
        config=McpServerConfig(
            toolset="research",
            actor_id="system",
            artifact_root=tmp_path / "artifacts",
            import_root=tmp_path / "imports",
        ),
        conversation_id="dsh-session-1",
        tool_call_id="call-1",
        request_boundary_id=boundary,
    )


def test_discovery_results_are_candidate_only_not_answer_evidence(monkeypatch, tmp_path):
    from paper_rag.discovery import runner
    from paper_rag.mcp.registry import call_tool

    monkeypatch.setattr(
        runner,
        "run_discovery",
        lambda topic, user_id, source_names, max_candidates: {
            "run": {"id": 7, "topic": topic, "user_id": user_id},
            "candidates": [
                {
                    "id": 11,
                    "title": "Candidate Paper",
                    "rank": 1,
                    "score": 0.94,
                    "rank_reason": "close semantic match",
                }
            ],
        },
    )

    result = call_tool(
        "paper_discover",
        {"topic": "retrieval augmented generation", "max_candidates": 3},
        _ctx(tmp_path, boundary=None),
    )["structuredContent"]

    assert result["ok"] is True
    assert result["evidence_role"] == "discovery_only"
    assert result["data"]["candidates"][0]["evidence_role"] == "discovery_only_not_answer_evidence"


def test_paper_ingest_requires_boundary_exactly_one_source_and_sandbox(monkeypatch, tmp_path):
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import paper_index

    calls = []
    monkeypatch.setattr(
        paper_index,
        "ingest",
        lambda payload: calls.append(payload.model_dump()) or {
            "paper_id": "arxiv:2601.00001",
            "status": "ingested",
            "n_chunks": 3,
        },
    )
    import_root = tmp_path / "imports"
    import_root.mkdir()
    allowed_pdf = import_root / "paper.pdf"
    allowed_pdf.write_bytes(b"%PDF-1.4\n")
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4\n")
    symlink = import_root / "linked.pdf"
    try:
        symlink.symlink_to(outside_pdf)
    except OSError:
        symlink = None

    no_boundary = call_tool(
        "paper_ingest",
        {"arxiv_id": "2601.00001"},
        _ctx(tmp_path, boundary=None),
    )["structuredContent"]
    no_source = call_tool("paper_ingest", {}, _ctx(tmp_path))["structuredContent"]
    many_sources = call_tool(
        "paper_ingest",
        {"arxiv_id": "2601.00001", "pdf_url": "https://example.test/p.pdf"},
        _ctx(tmp_path),
    )["structuredContent"]
    traversal = call_tool(
        "paper_ingest",
        {"pdf_path": "../outside.pdf"},
        _ctx(tmp_path),
    )["structuredContent"]
    bad_suffix = call_tool(
        "paper_ingest",
        {"pdf_path": "note.txt"},
        _ctx(tmp_path),
    )["structuredContent"]
    if symlink is not None:
        symlink_result = call_tool(
            "paper_ingest",
            {"pdf_path": "linked.pdf"},
            _ctx(tmp_path),
        )["structuredContent"]
        assert symlink_result["ok"] is False
    accepted = call_tool(
        "paper_ingest",
        {"pdf_path": "paper.pdf", "title_hint": "Safe"},
        _ctx(tmp_path),
    )["structuredContent"]

    assert no_boundary["error"]["code"] == "UNAVAILABLE"
    assert no_source["error"]["code"] == "VALIDATION"
    assert many_sources["error"]["code"] == "VALIDATION"
    assert traversal["error"]["code"] == "VALIDATION"
    assert bad_suffix["error"]["code"] in {"NOT_FOUND", "VALIDATION"}
    assert accepted["ok"] is True
    assert accepted["data"]["status"] == "ingested"
    assert calls == [
        {
            "arxiv_id": None,
            "pdf_url": None,
            "pdf_path": str(allowed_pdf.resolve()),
            "title_hint": "Safe",
            "user_id": "system",
            "force": False,
        }
    ]


def test_discovery_candidate_ingest_enforces_batch_limit_and_returns_results(monkeypatch, tmp_path):
    from paper_rag.discovery import runner
    from paper_rag.mcp.registry import call_tool

    monkeypatch.setattr(
        runner,
        "ingest_candidate",
        lambda candidate_id, user_id, force=False: {
            "candidate_id": candidate_id,
            "paper_id": f"paper-{candidate_id}",
            "status": "skipped" if not force else "ingested",
            "reason": "already_indexed" if not force else None,
            "n_chunks": 0 if not force else 4,
        },
    )

    too_many = call_tool(
        "discovery_candidate_ingest",
        {"candidate_ids": [1, 2, 3, 4, 5, 6]},
        _ctx(tmp_path),
    )["structuredContent"]
    accepted = call_tool(
        "discovery_candidate_ingest",
        {"candidate_ids": [1, 2], "force": True},
        _ctx(tmp_path),
    )["structuredContent"]

    assert too_many["ok"] is False
    assert too_many["error"]["code"] == "VALIDATION"
    assert accepted["ok"] is True
    assert [item["paper_id"] for item in accepted["data"]["results"]] == ["paper-1", "paper-2"]


def test_paper_deliver_requires_boundary_writes_manifest_and_omits_base64(monkeypatch, tmp_path):
    deliver_dispatch = importlib.import_module("paper_rag.deliver.dispatch")
    from paper_rag.mcp.registry import call_tool

    calls = []

    def fake_dispatch(format, paper_ids, *, title=None, options=None, user_id="system"):
        calls.append(
            {
                "format": format,
                "paper_ids": paper_ids,
                "title": title,
                "options": options,
                "user_id": user_id,
            }
        )
        return deliver_dispatch.DeliverableResult(
            format=format,
            filename="../unsafe\x00title.md",
            content_bytes=b"# Survey\n\nNo base64 here.\n",
            content_type="text/markdown; charset=utf-8",
            metadata={"n_papers": len(paper_ids)},
        )

    monkeypatch.setattr(deliver_dispatch, "dispatch", fake_dispatch)

    denied = call_tool(
        "paper_deliver",
        {"format": "markdown_survey", "paper_ids": ["p1"], "title": "Denied"},
        _ctx(tmp_path, boundary=None),
    )["structuredContent"]
    delivered = call_tool(
        "paper_deliver",
        {
            "format": "markdown_survey",
            "paper_ids": ["p1", "p2"],
            "title": "../unsafe\x00title",
        },
        _ctx(tmp_path),
    )
    structured = delivered["structuredContent"]
    artifact_dir = Path(structured["data"]["artifact"]["path"])
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_file = artifact_dir / manifest["files"][0]["filename"]

    assert denied["ok"] is False
    assert calls == [
        {
            "format": "markdown_survey",
            "paper_ids": ["p1", "p2"],
            "title": "../unsafe\x00title",
            "options": {},
            "user_id": "system",
        }
    ]
    assert structured["ok"] is True
    assert artifact_dir.parent == (tmp_path / "artifacts").resolve()
    assert artifact_file.read_bytes() == b"# Survey\n\nNo base64 here.\n"
    assert ".." not in manifest["files"][0]["filename"]
    assert manifest["files"][0]["size_bytes"] == len(b"# Survey\n\nNo base64 here.\n")
    assert len(manifest["files"][0]["sha256"]) == 64
    assert manifest["files"][0]["content_type"] == "text/markdown; charset=utf-8"
    assert "content_base64" not in json.dumps(delivered)
    assert len(delivered["content"][0]["text"]) < 1600


def test_artifact_cleanup_removes_only_expired_artifacts(tmp_path):
    from paper_rag.mcp.artifacts import cleanup_artifacts

    root = tmp_path / "artifacts"
    old = root / "old"
    new = root / "new"
    old.mkdir(parents=True)
    new.mkdir()
    (old / "manifest.json").write_text("{}", encoding="utf-8")
    (new / "manifest.json").write_text("{}", encoding="utf-8")
    expired = time.time() - 31 * 24 * 3600
    fresh = time.time()
    os.utime(old, (expired, expired))
    os.utime(new, (fresh, fresh))
    data_root = tmp_path / "data/index"
    data_root.mkdir(parents=True)
    (data_root / "papers.sqlite").write_text("keep", encoding="utf-8")

    result = cleanup_artifacts(root, older_than_days=30, protected_roots=[data_root])

    assert result == {"deleted": [str(old.resolve())], "kept": [str(new.resolve())]}
    assert not old.exists()
    assert new.exists()
    assert (data_root / "papers.sqlite").exists()


def test_export_bibtex_and_wiki_generate_delegate_without_artifact_base64(monkeypatch, tmp_path):
    from paper_rag.mcp.registry import call_tool
    from paper_rag.tools import bibtex_export
    from paper_rag.wiki import triggers

    monkeypatch.setattr(
        bibtex_export,
        "export_bibtex",
        lambda payload: {
            "bibtex": "@misc{p1,\n  title={Paper}\n}",
            "n_exported": 1,
            "missing": [],
        },
    )
    monkeypatch.setattr(
        triggers,
        "on_paper_indexed",
        lambda paper_id, force=False: {"paper_id": paper_id, "created": 1, "patched": 0},
    )

    bib = call_tool("export_bibtex", {"paper_ids": ["p1"]}, _ctx(tmp_path))["structuredContent"]
    wiki = call_tool(
        "wiki_generate",
        {"paper_id": "p1", "force": True},
        _ctx(tmp_path),
    )["structuredContent"]

    assert bib["ok"] is True
    assert bib["data"]["n_exported"] == 1
    assert "content_base64" not in json.dumps(bib)
    assert wiki["ok"] is True
    assert wiki["data"] == {"paper_id": "p1", "created": 1, "patched": 0}
