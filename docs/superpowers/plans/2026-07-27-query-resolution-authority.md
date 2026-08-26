# Query Resolution Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Paper RAG resolve each QA question exactly once, obey caller-supplied resolved questions, keep direct multi-turn fallback, and expose query-resolution trace consistently across sync, streaming, REST, and DeerFlow tool calls.

**Architecture:** Add tenant-scoped conversation storage and a shared `context_resolver` before QA retrieval. Thread the resolver output through sync QA, streaming QA, cache keys, persistence, REST routers, and DeerFlow tool adapters while preserving existing single-turn callers. Keep retrieval, reranking, abstain, citation validation, and wiki behavior unchanged except for using the resolver's effective question.

**Tech Stack:** Python 3.10+, Pydantic, SQLAlchemy/SQLModel with SQLite, pytest, FastAPI, SSE, LangChain tools, existing paper_rag config/logger/observability helpers.

## Global Constraints

- Do not change dense retrieval, BM25, RRF, reranking, reflection, citation validation, abstain policy, or wiki generation behavior.
- Do not let DeerFlow internals leak into the standalone `paper_rag` package.
- Do not use memory summaries, history rows, wiki background, or cached answer metadata as final-answer evidence.
- Do not remove old history tables in the first release. Migration must be non-destructive.
- Do not require existing REST or Python callers to send new fields.
- Explicit `paper_ids` are always a hard retrieval constraint.
- Paper scope from research memory is a soft hint only and cannot expand, override, or narrow explicit caller-supplied `paper_ids`.
- `context_source`, `memory_mode`, `user_id`, and `conversation_id` are server/runtime-derived policy values, not model-visible DeerFlow tool arguments.
- All memory reads and writes must filter by both `user_id` and `conversation_id`.
- Sync and streaming QA must expose the same `trace.query_resolution` shape.
- Accepted final-answer citations must correspond to selected chunk ids.

---

## File Structure

- Create `src/paper_rag/rag/conversation_turn_store.py`: canonical tenant-scoped QA turn and summary storage, lazy legacy migration, and chunk-style dict helpers for recent turns.
- Create `src/paper_rag/rag/context_resolver.py`: `QARequestContext`, `QueryResolution`, trace serialization, paper-scope hint extraction, and exactly-one rewrite policy.
- Create `tests/test_conversation_turn_store.py`: storage isolation, ordering, legacy migration, and history facade coverage.
- Create `tests/test_context_resolver.py`: resolver authority, fallback, conflicts, and trace coverage.
- Create `tests/test_query_resolution_qa.py`: sync QA resolver integration, cache safety, evidence prompt exclusion, and persistence coverage.
- Modify `src/paper_rag/rag/history.py`: compatibility facade over `conversation_turn_store`.
- Modify `src/paper_rag/rag/research_memory.py`: read recent turns and summaries through canonical tenant-scoped storage while keeping current public defaults.
- Modify `src/paper_rag/rag/qa_agentic.py`: remove double rewrite, call shared resolver, attach query trace, key cache by effective inputs, rehydrate cached chunks, and persist one canonical turn.
- Modify `src/paper_rag/rag/qa_stream.py`: accept the same contextual parameters as sync, call shared resolver once, and expose query trace in `done`.
- Modify `src/paper_rag/rag/async_api.py`: forward `user_id`, `conversation_id`, and `resolved_question`.
- Modify `src/paper_rag/rag/qa_cache.py`: include functional context in cache keys and rehydrate selected chunks on hit.
- Modify `src/paper_rag/tools/_schema.py` and `src/paper_rag/tools/paper_qa.py`: add optional resolved question and runtime fields needed by non-DeerFlow callers.
- Modify `integrations/deer-flow/backend/packages/harness/deerflow/community/paper_rag/tools.py`: expose `resolved_question`, derive runtime context, and return `query_resolution`.
- Modify `integrations/deer-flow/backend/app/gateway/routers/paper_rag.py` and `docs/integration/router/paper_rag.py`: pass contextual fields in sync and streaming REST routes.
- Modify existing tests in `tests/test_research_memory.py`, `tests/test_finalization.py`, `tests/test_coverage_boost.py`, `tests/test_m5_p2.py`, `tests/test_gateway_paper_rag.py`, and `integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py` as each task requires.

---

### Task 1: Canonical Conversation Turn Store

**Files:**
- Create: `src/paper_rag/rag/conversation_turn_store.py`
- Modify: `src/paper_rag/rag/history.py`
- Test: `tests/test_conversation_turn_store.py`
- Test: `tests/test_coverage_boost.py`

**Interfaces:**
- Produces: `ConversationTurn`
- Produces: `append_turn(*, user_id: str, conversation_id: str, raw_question: str, effective_question: str, answer: str, citations: list[str], paper_ids: list[str], trace: dict, resolution_source: str) -> None`
- Produces: `recent_turns(*, user_id: str = "system", conversation_id: str, limit: int = 3) -> list[ConversationTurn]`
- Produces: `append_summary(*, user_id: str, conversation_id: str, session_summary: str, research_memory: dict[str, list[str]], n_turns: int) -> None`
- Produces: `load_summary(*, user_id: str = "system", conversation_id: str) -> dict | None`
- Produces: `history.append(conversation_id: str, question: str, answer: str, citations: list[str]) -> None`
- Produces: `history.recent(conversation_id: str, limit: int = 3) -> list[tuple[str, str]]`

- [ ] **Step 1: Write failing storage isolation tests**

```python
from __future__ import annotations

from sqlalchemy import create_engine


def _patch_engine(monkeypatch, tmp_path):
    from paper_rag.store import sqlite_store
    engine = create_engine(f"sqlite:///{tmp_path / 'turns.sqlite'}")
    monkeypatch.setattr(sqlite_store, "get_engine", lambda: engine)
    return engine


def test_recent_turns_are_user_and_conversation_scoped(monkeypatch, tmp_path):
    _patch_engine(monkeypatch, tmp_path)

    from paper_rag.rag import conversation_turn_store as store

    store._TABLE_READY = False
    store.append_turn(
        user_id="alice",
        conversation_id="same",
        raw_question="raw a",
        effective_question="effective a",
        answer="answer a",
        citations=["c1"],
        paper_ids=["p1"],
        trace={"trace_id": "t-a"},
        resolution_source="outer_checkpoint",
    )
    store.append_turn(
        user_id="bob",
        conversation_id="same",
        raw_question="raw b",
        effective_question="effective b",
        answer="answer b",
        citations=["c2"],
        paper_ids=["p2"],
        trace={"trace_id": "t-b"},
        resolution_source="paper_rag_recent_turns",
    )

    alice = store.recent_turns(user_id="alice", conversation_id="same")
    bob = store.recent_turns(user_id="bob", conversation_id="same")

    assert [turn.raw_question for turn in alice] == ["raw a"]
    assert [turn.raw_question for turn in bob] == ["raw b"]
    assert alice[0].effective_question == "effective a"
    assert bob[0].paper_ids == ["p2"]
```

- [ ] **Step 2: Write failing history facade test**

```python
def test_history_facade_reads_canonical_turns(monkeypatch, tmp_path):
    _patch_engine(monkeypatch, tmp_path)

    from paper_rag.rag import conversation_turn_store as store
    from paper_rag.rag import history

    store._TABLE_READY = False
    history._TABLE_READY = False
    history.append("conv-h", "Q1", "A1", ["c1"])
    history.append("conv-h", "Q2", "A2", ["c2"])

    assert history.recent("conv-h", limit=2) == [("Q1", "A1"), ("Q2", "A2")]
```

- [ ] **Step 3: Write failing legacy migration test**

```python
def test_legacy_research_memory_rows_migrate_under_system_user(monkeypatch, tmp_path):
    engine = _patch_engine(monkeypatch, tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE research_memory_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                paper_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO research_memory_turns
            (conversation_id, question, answer, citations_json, trace_json, paper_ids_json, created_at)
            VALUES ('legacy', 'Legacy Q', 'Legacy A', '["c1"]', '{"trace_id":"old"}', '["p1"]', '2026-07-27T00:00:00')
            """
        )

    from paper_rag.rag import conversation_turn_store as store

    store._TABLE_READY = False
    turns = store.recent_turns(user_id="system", conversation_id="legacy")

    assert len(turns) == 1
    assert turns[0].raw_question == "Legacy Q"
    assert turns[0].resolution_source == "legacy_research_memory"
```

- [ ] **Step 4: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/test_conversation_turn_store.py::test_recent_turns_are_user_and_conversation_scoped tests/test_conversation_turn_store.py::test_history_facade_reads_canonical_turns tests/test_conversation_turn_store.py::test_legacy_research_memory_rows_migrate_under_system_user`

Expected: FAIL because `paper_rag.rag.conversation_turn_store` does not exist.

- [ ] **Step 5: Implement `conversation_turn_store.py`**

Create the module with this shape:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

_TABLE_READY = False


@dataclass(frozen=True)
class ConversationTurn:
    raw_question: str
    effective_question: str
    answer: str
    citations: list[str]
    paper_ids: list[str]
    trace: dict[str, Any]
    resolution_source: str
    created_at: str


def _json_loads(value: str | None, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _ensure_tables() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    from ..store.sqlite_store import get_engine

    with get_engine().begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                raw_question TEXT NOT NULL,
                effective_question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations_json TEXT NOT NULL,
                paper_ids_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                resolution_source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS conversation_turns_user_conv_id_idx "
            "ON conversation_turns(user_id, conversation_id, id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS conversation_turns_user_conv_created_idx "
            "ON conversation_turns(user_id, conversation_id, created_at)"
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                session_summary TEXT NOT NULL,
                research_memory_json TEXT NOT NULL,
                n_turns INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, conversation_id)
            )
            """
        )
    _TABLE_READY = True
```

Add `_legacy_table_exists(conn, name)`, `_canonical_count(conn, user_id, conversation_id)`, `_migrate_legacy_if_empty(user_id, conversation_id)`, `append_turn()`, `recent_turns()`, `append_summary()`, and `load_summary()` in the same module. Legacy migration copies from `research_memory_turns` first with `resolution_source="legacy_research_memory"`, then from `qa_history` with `resolution_source="legacy_qa_history"`, only when canonical count is zero.

- [ ] **Step 6: Implement `history.py` facade**

Replace direct `qa_history` writes and reads with canonical store calls:

```python
def append(conversation_id: str, question: str, answer: str, citations: list[str]) -> None:
    if not conversation_id:
        return
    from . import conversation_turn_store as store

    store.append_turn(
        user_id="system",
        conversation_id=conversation_id,
        raw_question=question,
        effective_question=question,
        answer=answer[:2000],
        citations=citations,
        paper_ids=[],
        trace={},
        resolution_source="history_facade",
    )


def recent(conversation_id: str, limit: int = 3) -> list[tuple[str, str]]:
    if not conversation_id:
        return []
    from . import conversation_turn_store as store

    turns = store.recent_turns(user_id="system", conversation_id=conversation_id, limit=limit)
    return [(turn.raw_question, turn.answer) for turn in turns]
```

Keep `rewrite_with_history()` public for compatibility, but it must call this facade and will be removed from the QA hot path in Task 3.

- [ ] **Step 7: Run focused tests to verify pass**

Run: `./.venv/bin/python -m pytest -q tests/test_conversation_turn_store.py tests/test_coverage_boost.py::test_history_append_and_recent_roundtrip`

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/paper_rag/rag/conversation_turn_store.py src/paper_rag/rag/history.py tests/test_conversation_turn_store.py tests/test_coverage_boost.py
git commit -m "Add tenant scoped conversation turn store"
```

---

### Task 2: Shared Context Resolver And Research Memory Scope

**Files:**
- Create: `src/paper_rag/rag/context_resolver.py`
- Modify: `src/paper_rag/rag/research_memory.py`
- Test: `tests/test_context_resolver.py`
- Test: `tests/test_research_memory.py`

**Interfaces:**
- Consumes: `conversation_turn_store.recent_turns`, `conversation_turn_store.append_summary`, `conversation_turn_store.load_summary`
- Produces: `QARequestContext`
- Produces: `QueryResolution`
- Produces: `resolve_query(ctx: QARequestContext) -> QueryResolution`
- Produces: `resolution_to_trace(resolution: QueryResolution) -> dict`
- Produces: `research_memory.load_for_question(conversation_id: str | None, *, user_id: str = "system") -> dict`
- Produces: `research_memory.append(conversation_id: str | None, question: str, answer: str, citations: list[str], *, trace: dict | None = None, user_id: str = "system", effective_question: str | None = None, resolution_source: str = "paper_rag") -> dict`

- [ ] **Step 1: Write failing resolver authority tests**

```python
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
        caller="deerflow",
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
```

- [ ] **Step 2: Write failing fallback and trace tests**

```python
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
```

- [ ] **Step 3: Write failing tenant-scoped research memory test**

```python
def test_research_memory_is_user_scoped(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from paper_rag.store import sqlite_store
    from paper_rag.rag import conversation_turn_store as store
    from paper_rag.rag import research_memory

    engine = create_engine(f"sqlite:///{tmp_path / 'memory.sqlite'}")
    monkeypatch.setattr(sqlite_store, "get_engine", lambda: engine)
    store._TABLE_READY = False
    research_memory._TABLE_READY = False

    research_memory.append(
        "conv",
        "Alice question",
        "Alice answer",
        ["c1"],
        trace={"chunks": [{"paper_id": "paper-a"}]},
        user_id="alice",
    )
    research_memory.append(
        "conv",
        "Bob question",
        "Bob answer",
        ["c2"],
        trace={"chunks": [{"paper_id": "paper-b"}]},
        user_id="bob",
    )

    alice = research_memory.load_for_question("conv", user_id="alice")
    bob = research_memory.load_for_question("conv", user_id="bob")

    assert [t["question"] for t in alice["recent_turns"]] == ["Alice question"]
    assert [t["question"] for t in bob["recent_turns"]] == ["Bob question"]
```

- [ ] **Step 4: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/test_context_resolver.py tests/test_research_memory.py::test_research_memory_is_user_scoped`

Expected: FAIL because `context_resolver` does not exist and `research_memory.append()` does not accept `user_id`.

- [ ] **Step 5: Implement `context_resolver.py`**

Create dataclasses and policy functions:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Source = Literal[
    "outer_checkpoint",
    "api_resolved",
    "paper_rag_recent_turns",
    "paper_rag_research_memory",
    "none",
]
Policy = Literal["authoritative_outer", "inner_fallback", "single_turn"]
Caller = Literal["deerflow", "rest", "python"]


@dataclass(frozen=True)
class QARequestContext:
    raw_question: str
    outer_resolved_question: str | None
    explicit_paper_ids: tuple[str, ...]
    conversation_id: str | None
    user_id: str
    caller: Caller


@dataclass(frozen=True)
class QueryResolution:
    raw_question: str
    effective_question: str
    source: Source
    policy: Policy
    rewrite_applied: bool
    outer_resolution_used: bool
    explicit_paper_ids: tuple[str, ...]
    memory_paper_scope_hint: tuple[str, ...]
    effective_paper_ids: tuple[str, ...]
    conflicts: tuple[str, ...]
    memory_used_as_evidence: bool = False
```

Implement `resolve_query()` with this branch order:

```python
def resolve_query(ctx: QARequestContext) -> QueryResolution:
    raw = (ctx.raw_question or "").strip()
    outer = (ctx.outer_resolved_question or "").strip()
    scope_hint = tuple(_load_memory_scope_hint(ctx.user_id, ctx.conversation_id))
    conflicts = _scope_conflicts(ctx.explicit_paper_ids, scope_hint)

    if outer:
        return QueryResolution(
            raw_question=raw,
            effective_question=outer,
            source="outer_checkpoint" if ctx.caller == "deerflow" else "api_resolved",
            policy="authoritative_outer",
            rewrite_applied=False,
            outer_resolution_used=True,
            explicit_paper_ids=ctx.explicit_paper_ids,
            memory_paper_scope_hint=scope_hint,
            effective_paper_ids=ctx.explicit_paper_ids,
            conflicts=conflicts,
        )

    if ctx.conversation_id:
        rewritten, source = _rewrite_with_memory(
            raw,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
        )
        effective = rewritten.strip() or raw
        return QueryResolution(
            raw_question=raw,
            effective_question=effective,
            source=source if effective != raw else "none",
            policy="inner_fallback",
            rewrite_applied=effective != raw,
            outer_resolution_used=False,
            explicit_paper_ids=ctx.explicit_paper_ids,
            memory_paper_scope_hint=scope_hint,
            effective_paper_ids=ctx.explicit_paper_ids,
            conflicts=conflicts,
        )

    return QueryResolution(
        raw_question=raw,
        effective_question=raw,
        source="none",
        policy="single_turn",
        rewrite_applied=False,
        outer_resolution_used=False,
        explicit_paper_ids=ctx.explicit_paper_ids,
        memory_paper_scope_hint=scope_hint,
        effective_paper_ids=ctx.explicit_paper_ids,
        conflicts=conflicts,
    )
```

Add `_rewrite_with_memory()` that loads `research_memory.load_for_question(conversation_id, user_id=user_id)`, builds one rewrite prompt from `recent_turns`, `session_summary`, and `research_memory`, calls `chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=160)`, and returns `(rewritten_question, source)`. Source is `paper_rag_research_memory` when compressed memory exists, otherwise `paper_rag_recent_turns`.

- [ ] **Step 6: Modify `research_memory.py` to use canonical storage**

Keep old defaults so existing callers still work:

```python
def append(
    conversation_id: str | None,
    question: str,
    answer: str,
    citations: list[str],
    *,
    trace: dict[str, Any] | None = None,
    user_id: str = "system",
    effective_question: str | None = None,
    resolution_source: str = "paper_rag",
) -> dict[str, Any]:
    if not conversation_id:
        return {"enabled": False, **_default_memory(conversation_id)}
    from . import conversation_turn_store as turns

    paper_ids = _extract_paper_ids(trace)
    turns.append_turn(
        user_id=user_id,
        conversation_id=conversation_id,
        raw_question=question,
        effective_question=effective_question or question,
        answer=answer[:4000],
        citations=citations,
        paper_ids=paper_ids,
        trace=trace or {},
        resolution_source=resolution_source,
    )
    stats = _stats(conversation_id, user_id=user_id)
    compressed = False
    if stats["turn_count"] > _COMPRESS_AFTER_TURNS or stats["answer_chars"] > _COMPRESS_AFTER_ANSWER_CHARS:
        summarize(conversation_id, user_id=user_id)
        compressed = True
    return {**load_for_question(conversation_id, user_id=user_id), "compressed": compressed}
```

Update `_stats()`, `_recent_rows()`, `_summary_row()`, `load_for_question()`, and `summarize()` to accept `user_id="system"` and use `conversation_turn_store` and `conversation_summaries`. Keep `rewrite_with_memory(question, conversation_id)` as a compatibility wrapper that calls the new resolver or loads memory with `user_id="system"`; the QA hot path will stop calling it in Task 3.

- [ ] **Step 7: Run focused tests to verify pass**

Run: `./.venv/bin/python -m pytest -q tests/test_context_resolver.py tests/test_research_memory.py`

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/paper_rag/rag/context_resolver.py src/paper_rag/rag/research_memory.py tests/test_context_resolver.py tests/test_research_memory.py
git commit -m "Add shared query context resolver"
```

---

### Task 3: Sync QA Integration And Cache Safety

**Files:**
- Modify: `src/paper_rag/rag/qa_agentic.py`
- Modify: `src/paper_rag/rag/qa_cache.py`
- Modify: `src/paper_rag/tools/_schema.py`
- Modify: `src/paper_rag/tools/paper_qa.py`
- Test: `tests/test_query_resolution_qa.py`
- Test: `tests/test_coverage_boost.py`
- Test: `tests/test_m5_p2.py`

**Interfaces:**
- Consumes: `context_resolver.QARequestContext`
- Consumes: `context_resolver.resolve_query`
- Consumes: `context_resolver.resolution_to_trace`
- Produces: `answer(question: str, *, paper_ids: list[str] | None = None, conversation_id: str | None = None, user_id: str = "system", resolved_question: str | None = None) -> dict`
- Produces: `_cache_question(resolution: QueryResolution, wiki_context: dict | None, *, user_id: str) -> str`
- Produces: `qa_cache.get(cache_question: str, paper_ids: list[str] | None, *, user_id: str = "system") -> dict | None`
- Produces: `qa_cache.put(cache_question: str, paper_ids: list[str] | None, answer: dict, *, user_id: str = "system") -> None`
- Produces: `PaperQAInput.resolved_question`, `PaperQAInput.conversation_id`, `PaperQAInput.user_id`

- [ ] **Step 1: Write failing sync QA authority test**

```python
def test_answer_uses_resolved_question_and_skips_legacy_rewriters(monkeypatch):
    from paper_rag.rag import qa_agentic

    seen = {}

    def fail_rewrite(*args, **kwargs):
        raise AssertionError("legacy rewrite must not run")

    monkeypatch.setattr(qa_agentic, "_maybe_rewrite_with_research_memory", fail_rewrite)
    monkeypatch.setattr(qa_agentic, "_maybe_rewrite_with_history", fail_rewrite)
    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: {"role": "background_not_evidence", "fingerprint": "", "entries": []})
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(qa_agentic, "classify", lambda q: {"intent": "factual", "top_k": 2, "max_iter": 1, "rrf_k": 60})

    def fake_retrieve(question, paper_ids, top_k, max_iter, enable_reflect, wiki_context=None):
        seen["question"] = question
        seen["paper_ids"] = paper_ids
        return (
            {"c1": {"chunk_id": "c1", "paper_id": "p1", "text": "FLARE retrieves proactively.", "score_rerank": 0.9}},
            [{"query": question, "n_retrieved": 1, "reflect": None}],
            "answered",
        )

    monkeypatch.setattr(qa_agentic, "_retrieve_loop", fake_retrieve)
    monkeypatch.setattr(qa_agentic, "_decide_abstain", lambda chunks, cfg: {"decision": "confident", "evidence_score": 0.9, "n_chunks": len(chunks)})
    monkeypatch.setattr(qa_agentic, "select_evidence", lambda question, chunks, intent=None: (chunks, {"selected_chunk_ids": ["c1"]}))
    monkeypatch.setattr(qa_agentic, "chat", lambda *a, **kw: "FLARE retrieves proactively. [chunk:c1]")
    monkeypatch.setattr(qa_agentic, "_store_in_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(qa_agentic, "_persist_research_memory", lambda *args, **kwargs: {"memory_role": "query_context_only_not_evidence"})

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
```

- [ ] **Step 2: Write failing prompt evidence exclusion test**

```python
def test_final_prompt_excludes_research_memory_answer_previews(monkeypatch):
    from paper_rag.rag import qa_agentic

    captured = {"user": ""}

    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: {"role": "background_not_evidence", "fingerprint": "", "entries": []})
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(qa_agentic, "classify", lambda q: {"intent": "factual", "top_k": 2, "max_iter": 1, "rrf_k": 60})
    monkeypatch.setattr(qa_agentic, "_retrieve_loop", lambda *a, **kw: (
        {"c1": {"chunk_id": "c1", "paper_id": "p1", "text": "Only retrieved evidence.", "score_rerank": 0.9}},
        [{"query": "q", "n_retrieved": 1, "reflect": None}],
        "answered",
    ))
    monkeypatch.setattr(qa_agentic, "_decide_abstain", lambda chunks, cfg: {"decision": "confident", "evidence_score": 0.9, "n_chunks": len(chunks)})
    monkeypatch.setattr(qa_agentic, "select_evidence", lambda question, chunks, intent=None: (chunks, {"selected_chunk_ids": ["c1"]}))

    def fake_chat(messages, **kwargs):
        captured["user"] = messages[-1]["content"]
        return "Answer from retrieved evidence. [chunk:c1]"

    monkeypatch.setattr(qa_agentic, "chat", fake_chat)
    monkeypatch.setattr(qa_agentic, "_store_in_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(qa_agentic, "_persist_research_memory", lambda *args, **kwargs: {
        "research_memory": {"confirmed_findings": ["Memory-only finding must stay out."]}
    })

    qa_agentic.answer("What is supported?", conversation_id="conv", user_id="alice")

    assert "Only retrieved evidence." in captured["user"]
    assert "Memory-only finding must stay out." not in captured["user"]
    assert "Evidence:" in captured["user"]
```

- [ ] **Step 3: Write failing cache key and rehydrate tests**

```python
def test_qa_cache_key_includes_user_and_effective_context():
    from paper_rag.rag.qa_cache import _make_key

    a = _make_key("How does FLARE retrieve?\n\nwiki_context_fingerprint:w1\npipeline:qra-v1", ["p1"], user_id="alice")
    b = _make_key("How does FLARE retrieve?\n\nwiki_context_fingerprint:w1\npipeline:qra-v1", ["p1"], user_id="bob")
    c = _make_key("How does Self-RAG retrieve?\n\nwiki_context_fingerprint:w1\npipeline:qra-v1", ["p1"], user_id="alice")

    assert a != b
    assert a != c


def test_cache_hit_returns_rehydrated_chunks(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from paper_rag.store import sqlite_store
    from paper_rag.rag import qa_cache

    engine = create_engine(f"sqlite:///{tmp_path / 'cache.sqlite'}")
    monkeypatch.setattr(sqlite_store, "get_engine", lambda: engine)
    sqlite_store.SQLModel.metadata.create_all(engine)
    sqlite_store.upsert_sections_and_chunks(
        "p1",
        [],
        [{"chunk_id": "c1", "paper_id": "p1", "text": "cached evidence", "context_text": "cached evidence"}],
    )
    qa_cache._TABLE_READY = False

    answer = {"answer": "cached [chunk:c1]", "citations": ["c1"], "chunks": [{"chunk_id": "c1", "paper_id": "p1", "text": "cached evidence"}], "trace": {"trace_id": "old"}}
    qa_cache.put("effective\n\npipeline:qra-v1", ["p1"], answer, user_id="alice")
    cached = qa_cache.get("effective\n\npipeline:qra-v1", ["p1"], user_id="alice")

    assert cached is not None
    assert cached["chunks"][0]["chunk_id"] == "c1"
    assert cached["chunks"][0]["text"] == "cached evidence"
```

- [ ] **Step 4: Write failing tool delegation test**

```python
def test_paper_qa_delegates_contextual_fields(monkeypatch):
    from paper_rag.tools import paper_qa as t
    from paper_rag.tools._schema import PaperQAInput

    captured = {}

    def fake_answer(q, *, paper_ids=None, conversation_id=None, user_id="system", resolved_question=None):
        captured.update({
            "q": q,
            "paper_ids": paper_ids,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "resolved_question": resolved_question,
        })
        return {"answer": "ok", "citations": [], "chunks": []}

    monkeypatch.setattr(t, "answer", fake_answer)

    t.paper_qa(PaperQAInput(
        question="raw",
        paper_ids=["p1"],
        conversation_id="thread-1",
        user_id="alice",
        resolved_question="effective",
    ))

    assert captured == {
        "q": "raw",
        "paper_ids": ["p1"],
        "conversation_id": "thread-1",
        "user_id": "alice",
        "resolved_question": "effective",
    }
```

- [ ] **Step 5: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/test_query_resolution_qa.py tests/test_m5_p2.py::test_qa_cache_key_includes_user_and_effective_context tests/test_m5_p2.py::test_cache_hit_returns_rehydrated_chunks tests/test_coverage_boost.py::test_paper_qa_delegates_contextual_fields`

Expected: FAIL because sync QA, cache, and tool schema do not support the new contextual fields.

- [ ] **Step 6: Update `qa_agentic.answer()`**

Change the public signature:

```python
def answer(
    question: str,
    *,
    paper_ids: list[str] | None = None,
    conversation_id: str | None = None,
    user_id: str = "system",
    resolved_question: str | None = None,
) -> dict:
```

Inside `answer()`, build `QARequestContext`, call `resolve_query()`, then pass `resolution.effective_question` and `list(resolution.effective_paper_ids)` into `_answer_impl()`. Remove calls to `_maybe_rewrite_with_research_memory()` and `_maybe_rewrite_with_history()` from the active path. Keep the old helper functions only if tests or external imports still need them.

Attach trace after `_answer_impl()` returns:

```python
resolution_trace = resolution_to_trace(resolution)
out.setdefault("trace", {})["query_resolution"] = resolution_trace
out["query_resolution"] = resolution_trace
```

Persist memory once:

```python
memory_after = _persist_research_memory(
    conversation_id,
    resolution.raw_question,
    out,
    user_id=user_id,
    effective_question=resolution.effective_question,
    resolution_source=resolution.source,
)
```

Do not call `_persist_history()` from `answer()`.

- [ ] **Step 7: Update `_answer_impl()` cache and wiki usage**

Change `_answer_impl()` to accept `query_resolution: QueryResolution` and `user_id: str`. Use:

```python
question = query_resolution.effective_question
effective_paper_ids = list(query_resolution.effective_paper_ids) or None
wiki_context = _resolve_wiki_context_safe(question, effective_paper_ids)
question_for_cache = _cache_question(query_resolution, wiki_context, user_id=user_id)
cached = _check_cache(question_for_cache, effective_paper_ids, trace_id, user_id=user_id)
```

All retrieval, evidence selection, and prompt construction use `question` and `effective_paper_ids`.

- [ ] **Step 8: Update `qa_cache.py`**

Change `_make_key()`:

```python
def _make_key(question: str, paper_ids: list[str] | None, *, user_id: str = "system") -> str:
    base = "|".join([
        f"user:{user_id or 'system'}",
        f"question:{_norm_question(question)}",
        f"papers:{','.join(sorted(paper_ids or []))}",
    ])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()
```

Change `get()` and `put()` to accept `user_id`. `put()` stores `chunk_fingerprint` using:

```python
def _fingerprint_chunks(chunks: list[dict]) -> str:
    parts = [
        f"{c.get('chunk_id')}:{c.get('paper_id')}:{c.get('text') or ''}"
        for c in chunks
        if c.get("chunk_id")
    ]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
```

On `get()`, rehydrate chunks with `sqlite_store.get_chunk(chunk_id)`, convert each `Chunk` to a dict with `model_dump()` when available, and compare the current fingerprint with the stored fingerprint. Return `None` on missing or stale chunks.

- [ ] **Step 9: Update tool schema and standalone tool**

In `PaperQAInput`, add:

```python
conversation_id: str | None = None
user_id: str = "system"
resolved_question: str | None = None
```

In `paper_qa()`, delegate all fields to `answer()`.

- [ ] **Step 10: Run focused tests to verify pass**

Run: `./.venv/bin/python -m pytest -q tests/test_query_resolution_qa.py tests/test_m5_p2.py tests/test_coverage_boost.py::test_paper_qa_delegates_contextual_fields`

Expected: PASS.

- [ ] **Step 11: Commit Task 3**

```bash
git add src/paper_rag/rag/qa_agentic.py src/paper_rag/rag/qa_cache.py src/paper_rag/tools/_schema.py src/paper_rag/tools/paper_qa.py tests/test_query_resolution_qa.py tests/test_m5_p2.py tests/test_coverage_boost.py
git commit -m "Thread query resolution through sync QA"
```

---

### Task 4: Streaming And REST Context Parity

**Files:**
- Modify: `src/paper_rag/rag/qa_stream.py`
- Modify: `src/paper_rag/rag/async_api.py`
- Modify: `integrations/deer-flow/backend/app/gateway/routers/paper_rag.py`
- Modify: `docs/integration/router/paper_rag.py`
- Test: `tests/test_finalization.py`
- Test: `tests/test_coverage_boost.py`
- Test: `tests/test_gateway_paper_rag.py`

**Interfaces:**
- Produces: `stream_answer(question: str, *, paper_ids: list[str] | None = None, conversation_id: str | None = None, user_id: str = "system", resolved_question: str | None = None) -> Generator[dict, None, None]`
- Produces: `stream_answer_async(question: str, *, paper_ids: list[str] | None = None, conversation_id: str | None = None, user_id: str = "system", resolved_question: str | None = None) -> AsyncGenerator[dict, None]`
- Produces: REST `QARequest.resolved_question`

- [ ] **Step 1: Write failing streaming resolver test**

```python
def test_stream_answer_uses_resolved_question_in_retrieval_and_done_trace():
    from paper_rag.rag import qa_stream

    seen = {}

    def fake_retrieve(q, p, k):
        seen["query"] = q
        return (
            [{"chunk_id": "c1", "paper_id": "p1", "text": "FLARE retrieves proactively.", "score_rerank": 0.9}],
            {"dense_queries": [q], "bm25_query": q},
        )

    def fake_stream(system, user):
        yield "FLARE retrieves proactively. [chunk:c1]"

    saved = (qa_stream._retrieve_round, qa_stream.classify, qa_stream._stream_chat)
    qa_stream._retrieve_round = fake_retrieve
    qa_stream.classify = lambda q: {"intent": "factual", "top_k": 2, "max_iter": 1, "rrf_k": 60}
    qa_stream._stream_chat = fake_stream
    try:
        events = list(qa_stream.stream_answer(
            "What about the second one?",
            paper_ids=["p1"],
            conversation_id="thread-1",
            user_id="alice",
            resolved_question="How does FLARE retrieve?",
        ))
    finally:
        qa_stream._retrieve_round, qa_stream.classify, qa_stream._stream_chat = saved

    done = events[-1]["data"]
    assert seen["query"] == "How does FLARE retrieve?"
    assert done["query_resolution"]["effective_question"] == "How does FLARE retrieve?"
    assert done["query_resolution"]["outer_resolution_used"] is True
```

- [ ] **Step 2: Write failing async forwarding test**

```python
def test_async_stream_forwards_contextual_fields(monkeypatch):
    import asyncio
    import sys
    import types

    from paper_rag.rag import async_api

    captured = {}

    def fake_stream(q, *, paper_ids=None, conversation_id=None, user_id="system", resolved_question=None):
        captured.update({
            "q": q,
            "paper_ids": paper_ids,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "resolved_question": resolved_question,
        })
        yield {"event": "done", "data": {}}

    monkeypatch.setitem(sys.modules, "paper_rag.rag.qa_stream", types.SimpleNamespace(stream_answer=fake_stream))

    async def _drive():
        async for _ in async_api.stream_answer_async(
            "raw",
            paper_ids=["p1"],
            conversation_id="thread-1",
            user_id="alice",
            resolved_question="effective",
        ):
            pass

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drive())
    finally:
        loop.close()

    assert captured == {
        "q": "raw",
        "paper_ids": ["p1"],
        "conversation_id": "thread-1",
        "user_id": "alice",
        "resolved_question": "effective",
    }
```

- [ ] **Step 3: Write failing REST forwarding tests**

```python
def test_qa_sync_forwards_user_conversation_and_resolved_question(monkeypatch):
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    pr = sys.modules["pr_mod"]
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "alice"
    captured = {}

    def fake_answer(question, *, paper_ids=None, conversation_id=None, user_id="system", resolved_question=None):
        captured.update({
            "question": question,
            "paper_ids": paper_ids,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "resolved_question": resolved_question,
        })
        return {
            "answer": "ok",
            "citations": [],
            "chunks": [],
            "trace": {"trace_id": "trace-1", "abstain": {}, "query_resolution": {"effective_question": resolved_question}},
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
```

Add this streaming REST test in the same file:

```python
def test_qa_stream_forwards_user_conversation_and_resolved_question(monkeypatch):
    from fastapi.testclient import TestClient

    app, auth = _make_app()
    auth._AUTH_DISABLED = True
    auth._DEV_USER_ID = "alice"
    captured = {}

    def fake_stream(question, *, paper_ids=None, conversation_id=None, user_id="system", resolved_question=None):
        captured.update({
            "question": question,
            "paper_ids": paper_ids,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "resolved_question": resolved_question,
        })
        yield {"event": "done", "data": {
            "answer": "ok",
            "citations": [],
            "query_resolution": {"effective_question": resolved_question},
        }}

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
```

- [ ] **Step 4: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/test_finalization.py::test_stream_answer_uses_resolved_question_in_retrieval_and_done_trace tests/test_coverage_boost.py::test_async_stream_forwards_contextual_fields tests/test_gateway_paper_rag.py::test_qa_sync_forwards_user_conversation_and_resolved_question`

Expected: FAIL because streaming and REST routes do not accept or forward the new contextual fields.

- [ ] **Step 5: Update `qa_stream.py`**

Change the public signature and call resolver before intent classification:

```python
def stream_answer(
    question: str,
    *,
    paper_ids: list[str] | None = None,
    conversation_id: str | None = None,
    user_id: str = "system",
    resolved_question: str | None = None,
) -> Generator[dict, None, None]:
    from .context_resolver import QARequestContext, resolve_query, resolution_to_trace

    resolution = resolve_query(QARequestContext(
        raw_question=question,
        outer_resolved_question=resolved_question,
        explicit_paper_ids=tuple(paper_ids or ()),
        conversation_id=conversation_id,
        user_id=user_id or "system",
        caller="python",
    ))
    query_resolution = resolution_to_trace(resolution)
    question = resolution.effective_question
    paper_ids = list(resolution.effective_paper_ids) or None
```

Include `query_resolution` in every `done` payload, including no-chunks and no-evidence exits. Use the effective question in `classify()`, `_retrieve_round()`, `reflect()`, `select_evidence()`, and the final prompt.

After final `done` data is prepared, persist the turn when `conversation_id` exists:

```python
try:
    from . import research_memory

    research_memory.append(
        conversation_id,
        resolution.raw_question,
        done_data.get("answer", ""),
        done_data.get("citations", []),
        trace={"chunks": final_chunks, "query_resolution": query_resolution},
        user_id=user_id,
        effective_question=resolution.effective_question,
        resolution_source=resolution.source,
    )
except Exception as exc:
    log.warning(f"stream research memory append failed (non-fatal): {exc}")
```

- [ ] **Step 6: Update `async_api.py`**

Add contextual parameters to `answer_async()` and `stream_answer_async()` and forward them to sync functions. Update existing async tests whose fake functions do not accept the new fields by adding `**kwargs` or exact parameters.

- [ ] **Step 7: Update REST routers**

In both router files, add `resolved_question: str | None = None` to `QARequest`. In sync route, call:

```python
lambda: answer(
    body.question,
    paper_ids=body.paper_ids,
    conversation_id=body.conversation_id,
    user_id=user_id,
    resolved_question=body.resolved_question,
)
```

In streaming route, call:

```python
gen = stream_answer(
    body.question,
    paper_ids=body.paper_ids,
    conversation_id=body.conversation_id,
    user_id=user_id,
    resolved_question=body.resolved_question,
)
```

- [ ] **Step 8: Run focused tests to verify pass**

Run: `./.venv/bin/python -m pytest -q tests/test_finalization.py tests/test_coverage_boost.py::test_async_answer_offloads_to_thread tests/test_coverage_boost.py::test_async_stream_drains_sync_generator tests/test_gateway_paper_rag.py`

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add src/paper_rag/rag/qa_stream.py src/paper_rag/rag/async_api.py integrations/deer-flow/backend/app/gateway/routers/paper_rag.py docs/integration/router/paper_rag.py tests/test_finalization.py tests/test_coverage_boost.py tests/test_gateway_paper_rag.py
git commit -m "Align streaming QA with query resolution context"
```

---

### Task 5: DeerFlow Tool Adapter Contract

**Files:**
- Modify: `integrations/deer-flow/backend/packages/harness/deerflow/community/paper_rag/tools.py`
- Test: `integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py`

**Interfaces:**
- Consumes: `PaperQAInput`
- Produces: `paper_qa_tool(question: str, paper_ids: str | None = None, resolved_question: str | None = None, config: Annotated[RunnableConfig | None, InjectedToolArg()] = None) -> str`
- Produces: `_runtime_context_from_config(config) -> tuple[str | None, str]`
- Produces: JSON result containing `query_resolution`

- [ ] **Step 1: Write failing DeerFlow schema and delegation tests**

```python
def test_paper_qa_tool_schema_exposes_only_model_fields():
    from deerflow.community.paper_rag import tools

    schema = tools.paper_qa_tool.args

    assert set(schema) == {"question", "paper_ids", "resolved_question"}


def test_paper_qa_tool_passes_resolved_question_and_runtime_context(monkeypatch):
    import json

    from deerflow.community.paper_rag import tools
    from paper_rag.tools import paper_qa as paper_qa_mod

    captured = {}

    def fake_paper_qa(input):
        captured.update(input.model_dump())
        return {
            "answer": "ok",
            "citations": [],
            "chunks": [],
            "trace": {
                "trace_id": "trace-1",
                "query_resolution": {"effective_question": input.resolved_question},
            },
        }

    monkeypatch.setattr(paper_qa_mod, "paper_qa", fake_paper_qa)
    monkeypatch.setattr(tools, "_runtime_context_from_config", lambda config=None: ("thread-1", "alice"))

    payload = tools.paper_qa_tool.invoke({
        "question": "raw",
        "paper_ids": "p1",
        "resolved_question": "effective",
    })
    data = json.loads(payload)

    assert captured["question"] == "raw"
    assert captured["paper_ids"] == ["p1"]
    assert captured["conversation_id"] == "thread-1"
    assert captured["user_id"] == "alice"
    assert captured["resolved_question"] == "effective"
    assert data["query_resolution"]["effective_question"] == "effective"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src:integrations/deer-flow/backend/packages/harness ./.venv/bin/python -m pytest -q integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py::test_paper_qa_tool_schema_exposes_only_model_fields integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py::test_paper_qa_tool_passes_resolved_question_and_runtime_context`

Expected: FAIL because the tool schema lacks `resolved_question` and does not derive runtime context.

- [ ] **Step 3: Update DeerFlow tool wrapper**

Use LangChain injected config support:

```python
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
```

Add helper:

```python
def _runtime_context_from_config(config: RunnableConfig | None = None) -> tuple[str | None, str]:
    thread_id = None
    if isinstance(config, dict):
        configurable = config.get("configurable") or {}
        thread_id = configurable.get("thread_id")
    try:
        from deerflow.runtime.user_context import get_effective_user_id

        user_id = get_effective_user_id()
    except Exception:
        user_id = "system"
    return (str(thread_id) if thread_id else None, str(user_id or "system"))
```

Update tool signature:

```python
@tool("paper_qa", parse_docstring=True)
def paper_qa_tool(
    question: str,
    paper_ids: str | None = None,
    resolved_question: str | None = None,
    config: Annotated[RunnableConfig | None, InjectedToolArg()] = None,
) -> str:
```

Build `PaperQAInput` with `conversation_id=thread_id`, `user_id=user_id`, and `resolved_question=resolved_question or None`. Add `query_resolution` to the returned JSON from `out.get("query_resolution") or out.get("trace", {}).get("query_resolution")`.

- [ ] **Step 4: Run focused tests to verify pass**

Run: `PYTHONPATH=src:integrations/deer-flow/backend/packages/harness ./.venv/bin/python -m pytest -q integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add integrations/deer-flow/backend/packages/harness/deerflow/community/paper_rag/tools.py integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py
git commit -m "Expose resolved paper QA context in DeerFlow adapter"
```

---

### Task 6: Regression Suite And Final Integration Check

**Files:**
- Modify only files touched by Tasks 1-5 if verification exposes a real regression.

**Interfaces:**
- Consumes all interfaces from Tasks 1-5.
- Produces a verified implementation branch with focused and broad tests passing.

- [ ] **Step 1: Run focused query-resolution suite**

Run:

```bash
./.venv/bin/python -m pytest -q \
  tests/test_conversation_turn_store.py \
  tests/test_context_resolver.py \
  tests/test_query_resolution_qa.py \
  tests/test_research_memory.py \
  tests/test_finalization.py \
  tests/test_m5_p2.py \
  tests/test_coverage_boost.py::test_paper_qa_delegates_contextual_fields \
  tests/test_coverage_boost.py::test_async_answer_offloads_to_thread \
  tests/test_coverage_boost.py::test_async_stream_drains_sync_generator \
  tests/test_gateway_paper_rag.py \
  integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py
```

Expected: PASS.

- [ ] **Step 2: Run broad Paper RAG regression suite**

Run:

```bash
./.venv/bin/python -m pytest -q tests
```

Expected: PASS. If unrelated long-running external-dependency tests fail, rerun the focused suite and record the exact failing test names and dependency error in the handoff.

- [ ] **Step 3: Inspect git diff for contract drift**

Run:

```bash
git diff --stat
git diff -- src/paper_rag/rag/qa_agentic.py src/paper_rag/rag/qa_stream.py src/paper_rag/rag/context_resolver.py
```

Expected: changed files match this plan, and the active QA path has no call chain where both legacy history and research memory rewrite the same request.

- [ ] **Step 4: Commit verification fixes if any were required**

If Step 1 or Step 2 required code changes after Task 5, commit only those fixes:

```bash
git add \
  src/paper_rag/rag/conversation_turn_store.py \
  src/paper_rag/rag/context_resolver.py \
  src/paper_rag/rag/history.py \
  src/paper_rag/rag/research_memory.py \
  src/paper_rag/rag/qa_agentic.py \
  src/paper_rag/rag/qa_cache.py \
  src/paper_rag/rag/qa_stream.py \
  src/paper_rag/rag/async_api.py \
  src/paper_rag/tools/_schema.py \
  src/paper_rag/tools/paper_qa.py \
  integrations/deer-flow/backend/packages/harness/deerflow/community/paper_rag/tools.py \
  integrations/deer-flow/backend/app/gateway/routers/paper_rag.py \
  docs/integration/router/paper_rag.py \
  tests/test_conversation_turn_store.py \
  tests/test_context_resolver.py \
  tests/test_query_resolution_qa.py \
  tests/test_research_memory.py \
  tests/test_finalization.py \
  tests/test_coverage_boost.py \
  tests/test_m5_p2.py \
  tests/test_gateway_paper_rag.py \
  integrations/deer-flow/backend/tests/test_paper_rag_harness_adapter.py
git commit -m "Stabilize query resolution integration"
```

If no changes were required, skip this commit.

- [ ] **Step 5: Final status check**

Run:

```bash
git status --short --branch
```

Expected: clean working tree on the feature branch, with implementation commits present.

---

## Self-Review Checklist

- Spec coverage: Task 1 covers canonical tenant storage and legacy migration. Task 2 covers resolver authority and memory scope. Task 3 covers sync QA, evidence prompt rules, cache, and standalone tool schema. Task 4 covers streaming and REST parity. Task 5 covers DeerFlow adapter boundaries. Task 6 covers final verification.
- Placeholder scan: this plan contains concrete file paths, function signatures, test bodies, commands, and expected outcomes for every task.
- Type consistency: `QARequestContext`, `QueryResolution`, `resolve_query`, `resolution_to_trace`, `append_turn`, `recent_turns`, `answer`, and `stream_answer` signatures match across producer and consumer tasks.
- Scope check: retrieval/rerank/abstain/citation logic stays unchanged except for receiving the resolver's effective question and hard paper ids.
