from __future__ import annotations

import json
from pathlib import Path

import yaml


def _isolated_config(tmp_path: Path, monkeypatch) -> None:
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "default.yaml").read_text())
    raw["paths"] = {
        "data_root": str(tmp_path / "data"),
        "papers_dir": str(tmp_path / "data" / "papers"),
        "parsed_dir": str(tmp_path / "data" / "parsed"),
        "index_dir": str(tmp_path / "data" / "index"),
        "sqlite_path": str(tmp_path / "data" / "index" / "papers.sqlite"),
        "bm25_path": str(tmp_path / "data" / "index" / "bm25.pkl"),
        "models_dir": str(tmp_path / "data" / "index" / "models"),
    }
    config_path = tmp_path / "paper-rag.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv("PAPER_RAG_CONFIG", str(config_path))

    from paper_rag import config as cfg
    from paper_rag.store import sqlite_store

    cfg.load.cache_clear()
    sqlite_store._ENGINE = None


def test_ranker_marks_duplicate_candidates_and_explains_scores():
    from paper_rag.discovery.ranker import rank_candidates

    candidates = [
        {
            "source": "arxiv",
            "title": "Self-RAG: Learning to Retrieve and Generate",
            "abstract": "Self-RAG uses reflection tokens for adaptive retrieval.",
            "arxiv_id": "2310.11511",
            "year": 2023,
            "urls": ["https://arxiv.org/abs/2310.11511"],
        },
        {
            "source": "semantic_scholar",
            "title": "Loop-Engineered Paper Discovery for Agentic RAG",
            "abstract": "A paper discovery loop ranks retrieval augmented generation papers before ingest.",
            "doi": "10.0000/discovery-demo",
            "year": 2026,
            "urls": ["https://example.test/discovery.pdf"],
        },
    ]

    ranked = rank_candidates(
        "paper discovery loop retrieval augmented generation",
        candidates,
        existing_keys={"arxiv:2310.11511", "2310.11511"},
        max_selected=2,
    )

    duplicate = next(item for item in ranked if item["arxiv_id"] == "2310.11511")
    selected = next(item for item in ranked if item["doi"] == "10.0000/discovery-demo")

    assert duplicate["selected"] is False
    assert duplicate["skip_reason"] == "already_indexed"
    assert selected["selected"] is True
    assert selected["score"] > duplicate["score"]
    assert "keyword_overlap" in selected["rank_reason"]
    assert "source_confidence" in selected["rank_reason"]


def test_runner_records_discovery_run_candidates_and_trace(tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)
    from paper_rag.discovery import runner, store

    def _fake_search_sources(topic, source_names, limit):
        assert topic == "agentic rag loop"
        assert source_names == ["arxiv"]
        assert limit == 8
        return (
            [
                {
                    "source": "arxiv",
                    "title": "Agentic RAG Loop",
                    "abstract": "Loop engineering for retrieval augmented generation.",
                    "arxiv_id": "2601.00001",
                    "year": 2026,
                    "urls": ["https://arxiv.org/abs/2601.00001"],
                },
                {
                    "source": "arxiv",
                    "title": "Unrelated Vision Model",
                    "abstract": "Image classification and segmentation.",
                    "arxiv_id": "2601.00002",
                    "year": 2026,
                    "urls": ["https://arxiv.org/abs/2601.00002"],
                },
            ],
            [],
        )

    monkeypatch.setattr(runner, "_search_sources", _fake_search_sources)

    out = runner.run_discovery(
        "agentic rag loop",
        user_id="alice",
        source_names=["arxiv"],
        max_candidates=1,
        search_limit=8,
    )

    assert out["run"]["status"] == "completed"
    assert out["run"]["stopped_by"] == "selected_limit"
    assert out["trace"]["loop"][0]["stage"] == "search"
    assert out["trace"]["loop"][-1]["stage"] == "store"
    assert out["candidates"][0]["selected"] is True
    assert out["candidates"][0]["rank"] == 1
    assert len(out["candidates"]) == 2

    runs = store.list_runs("alice")
    assert runs[0]["topic"] == "agentic rag loop"
    loaded = store.get_run(out["run"]["id"], user_id="alice")
    assert loaded["trace"]["trace_id"] == out["trace"]["trace_id"]
    assert {item["arxiv_id"] for item in loaded["candidates"]} == {"2601.00001", "2601.00002"}


def test_runner_records_source_failures_without_crashing(tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)
    from paper_rag.discovery import runner

    def _fake_search_sources(topic, source_names, limit):
        return [], [{"source": "arxiv", "error": "arxiv 429 rate limited"}]

    monkeypatch.setattr(runner, "_search_sources", _fake_search_sources)

    out = runner.run_discovery("self rag", user_id="alice", source_names=["arxiv"])

    assert out["run"]["status"] == "degraded"
    assert out["run"]["stopped_by"] == "source_errors"
    assert out["candidates"] == []
    assert out["trace"]["source_errors"] == [{"source": "arxiv", "error": "arxiv 429 rate limited"}]


def test_ingest_candidate_uses_existing_ingest_pipeline(tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)
    from paper_rag.discovery import store
    from paper_rag.discovery.runner import ingest_candidate
    from paper_rag.ingest.arxiv_source import ArxivSource
    from paper_rag.ingest.schema import FetchResult, PaperMeta
    from paper_rag.store import ingest_pipeline

    run_id = store.create_run("alice", "rag survey", ["arxiv"], 3)
    [candidate_id] = store.save_candidates(
        run_id,
        [
            {
                "source": "arxiv",
                "paper_id": "arxiv:2601.00003",
                "title": "RAG Survey Candidate",
                "abstract": "Survey paper.",
                "arxiv_id": "2601.00003",
                "doi": None,
                "year": 2026,
                "urls": ["https://arxiv.org/abs/2601.00003"],
                "score": 0.8,
                "rank": 1,
                "selected": True,
                "rank_reason": "keyword_overlap=0.5",
                "skip_reason": None,
                "ingest_status": "pending",
            }
        ],
    )

    monkeypatch.setattr(
        ArxivSource,
        "fetch",
        lambda _self, arxiv_id: FetchResult(
            meta=PaperMeta(
                paper_id=f"arxiv:{arxiv_id}",
                title="RAG Survey Candidate",
                arxiv_id=arxiv_id,
                source="arxiv",
            ),
            pdf_path=str(tmp_path / "raw.pdf"),
        ),
    )
    calls = []
    monkeypatch.setattr(
        ingest_pipeline,
        "ingest",
        lambda fetched, force=False: calls.append({"paper_id": fetched.meta.paper_id, "force": force})
        or {"paper_id": fetched.meta.paper_id, "status": "done", "chunks": 7, "wiki": {"queued": True}},
    )

    out = ingest_candidate(candidate_id, user_id="alice")

    assert out["status"] == "done"
    assert out["n_chunks"] == 7
    assert calls == [{"paper_id": "arxiv:2601.00003", "force": False}]

    loaded = store.get_run(run_id, user_id="alice")
    [candidate] = loaded["candidates"]
    assert candidate["ingest_status"] == "done"
    assert json.loads(candidate["ingest_result_json"])["wiki"] == {"queued": True}


def test_attach_user_id_creates_missing_extra():
    from types import SimpleNamespace

    from paper_rag.discovery import runner

    fetched = SimpleNamespace(meta=SimpleNamespace(extra=None))

    runner._attach_user_id_to_fetch_meta(fetched, "alice")

    assert fetched.meta.extra == {"user_id": "alice"}
