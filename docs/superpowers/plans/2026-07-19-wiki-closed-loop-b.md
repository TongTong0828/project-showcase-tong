# Wiki Closed Loop B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build full B-scope wiki consumption: wiki background enters QA and retrieval, remains non-evidence, produces closed-loop review events, and is visible in traces and UI.

**Architecture:** Add read-only wiki context resolution plus a lightweight wiki review queue under `paper_rag.wiki`. Thread `wiki_context` through query rewrite, retrieval, QA prompt, cache keys, and trace output. Extend DeerFlow gateway/frontend surfaces to display consumed wiki concepts and review-needed status without changing the evidence-only citation contract.

**Tech Stack:** Python 3.10+, SQLModel/SQLite, existing paper_rag config/logger/metrics helpers, pytest, FastAPI/Pydantic gateway, Next.js/React/TypeScript DeerFlow frontend.

## Global Constraints

- Wiki context role is exactly `background_not_evidence`.
- Final answers must cite only indexed paper chunks with `[chunk:<id>]`.
- Wiki entries must not be treated as final answer evidence.
- Wiki failures must be non-fatal for QA.
- QA cache keys must account for wiki context fingerprint.
- Weak/no-evidence QA paths must create non-blocking wiki review events.
- Keep existing wiki generation and manual wiki viewing behavior intact.

---

## File Structure

- Create `src/paper_rag/wiki/context.py`: read-only wiki matching, compaction, fingerprinting, prompt formatting, and rewrite hint extraction.
- Create `src/paper_rag/wiki/review_queue.py`: SQLite-backed review queue and dedupe.
- Create `src/paper_rag/wiki/usage.py`: SQLite-backed wiki consumption events for Knowledge Builder status.
- Modify `src/paper_rag/rag/query_rewrite.py`: accept optional wiki context and add aliases/definition keywords to rewrite output.
- Modify `src/paper_rag/retrieve/pipeline.py`: pass wiki context into rewrite.
- Modify `src/paper_rag/rag/qa_agentic.py`: resolve wiki context, add prompt background, protect cache with fingerprint, enqueue review events, expose trace.
- Modify `src/paper_rag/feedback/collector.py`: mirror selected negative feedback into wiki review queue.
- Modify `integrations/deer-flow/backend/app/gateway/routers/paper_rag.py`: expose wiki consumed/review-needed Knowledge Builder fields.
- Modify `integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx`: render wiki context chips and Knowledge Builder wiki state.
- Add tests in `tests/test_wiki_context.py`, `tests/test_wiki_review_queue.py`, `tests/test_wiki_closed_loop_qa.py`, and update gateway/frontend tests where practical.

---

### Task 1: Wiki Context Resolver

**Files:**
- Create: `src/paper_rag/wiki/context.py`
- Test: `tests/test_wiki_context.py`

**Interfaces:**
- Produces: `resolve_wiki_context(question: str, paper_ids: list[str] | None = None, max_entries: int = 3) -> dict`
- Produces: `format_wiki_background(context: dict) -> str`
- Produces: `wiki_rewrite_hints(context: dict) -> dict[str, list[str] | str]`

- [ ] **Step 1: Write failing tests**

```python
def test_resolve_wiki_context_matches_alias(monkeypatch):
    from paper_rag.wiki.schema import WikiEntry
    from paper_rag.wiki import context

    entry = WikiEntry(
        entry_id="contrastive-learning",
        name="Contrastive Learning",
        aliases=["对比学习", "CL"],
        definition="Learns representations by pulling positives together [chunk:c1].",
        key_papers=["paper-1"],
        evidence_chunks=["c1"],
        version=3,
    )
    monkeypatch.setattr(context.wstore, "list_all", lambda: [entry])

    out = context.resolve_wiki_context("对比学习怎么评估？", paper_ids=None)

    assert out["role"] == "background_not_evidence"
    assert out["fingerprint"] == "contrastive-learning:3"
    assert out["entries"][0]["entry_id"] == "contrastive-learning"
    assert out["entries"][0]["aliases"] == ["对比学习", "CL"]


def test_format_wiki_background_marks_not_evidence():
    from paper_rag.wiki.context import format_wiki_background

    block = format_wiki_background({
        "role": "background_not_evidence",
        "entries": [{
            "name": "RAG",
            "definition": "Retrieval augmented generation.",
            "aliases": ["Retrieval-Augmented Generation"],
            "key_papers": ["paper-1"],
            "version": 2,
        }],
    })

    assert "Wiki background (not evidence)" in block
    assert "Do not cite this background" in block
    assert "RAG" in block
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src pytest -q tests/test_wiki_context.py`

Expected: FAIL because `paper_rag.wiki.context` does not exist.

- [ ] **Step 3: Implement resolver**

Implement `context.py` with exact functions above. Matching order: token/name substring, alias substring, paper overlap, semantic `find_match` fallback. Return empty context with `entries: []` and `fingerprint: ""` on failure.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=src pytest -q tests/test_wiki_context.py`

Expected: PASS.

---

### Task 2: Wiki Review Queue

**Files:**
- Create: `src/paper_rag/wiki/review_queue.py`
- Test: `tests/test_wiki_review_queue.py`

**Interfaces:**
- Produces: `enqueue(event_type: str, *, concept: str | None = None, paper_id: str | None = None, question: str | None = None, reason: str = "", payload: dict | None = None) -> int | None`
- Produces: `count_pending() -> int`
- Produces: `recent(limit: int = 20) -> list[dict]`

- [ ] **Step 1: Write failing tests**

```python
def test_review_queue_dedupes_recent_events(tmp_path, monkeypatch):
    from paper_rag.store import sqlite_store
    monkeypatch.setenv("PAPER_RAG_SQLITE_PATH", str(tmp_path / "papers.sqlite"))
    sqlite_store.reset_engine_for_tests()

    from paper_rag.wiki import review_queue

    first = review_queue.enqueue(
        "qa_weak_evidence",
        concept="RAG",
        paper_id="paper-1",
        question="What is RAG?",
        reason="weak_evidence",
    )
    second = review_queue.enqueue(
        "qa_weak_evidence",
        concept="RAG",
        paper_id="paper-1",
        question="What is RAG again?",
        reason="weak_evidence",
    )

    assert first == second
    assert review_queue.count_pending() == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src pytest -q tests/test_wiki_review_queue.py`

Expected: FAIL because `review_queue` does not exist.

- [ ] **Step 3: Implement queue**

Use `get_engine().begin()` and `exec_driver_sql` to create `wiki_review_queue`. Dedupe by same `event_type`, normalized `concept`, `paper_id`, `reason`, and `created_at >= now - 24h`.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=src pytest -q tests/test_wiki_review_queue.py`

Expected: PASS.

---

### Task 3: Retrieval, Prompt, Cache, And QA Review Events

**Files:**
- Modify: `src/paper_rag/rag/query_rewrite.py`
- Modify: `src/paper_rag/retrieve/pipeline.py`
- Modify: `src/paper_rag/rag/qa_agentic.py`
- Test: `tests/test_wiki_closed_loop_qa.py`

**Interfaces:**
- Consumes: `resolve_wiki_context`, `format_wiki_background`, `wiki_rewrite_hints`, `review_queue.enqueue`
- Produces: `trace["wiki_context"]`
- Produces: retrieval rewrite payload with `raw["wiki_context_used"]`

- [ ] **Step 1: Write failing tests**

```python
def test_query_rewrite_uses_wiki_aliases(monkeypatch):
    from paper_rag.rag import query_rewrite

    monkeypatch.setattr(query_rewrite.cfg, "load", lambda: type("C", (), {
        "rag": type("R", (), {"enable_hyde": False})(),
        "llm": type("L", (), {"chat_model": None, "api_key": None, "base_url": None})(),
    })())

    out = query_rewrite.rewrite("什么是对比学习？", wiki_context={
        "entries": [{
            "name": "Contrastive Learning",
            "aliases": ["对比学习", "CL"],
            "definition": "Learns representations from positive and negative pairs.",
            "key_papers": ["paper-1"],
        }]
    })

    assert "Contrastive Learning" in out["dense_queries"]
    assert any("positive negative pairs" in q for q in out["dense_queries"])
    assert "contrastive learning" in out["bm25_query"].lower()


def test_qa_trace_includes_wiki_context(monkeypatch):
    from paper_rag.rag import qa_agentic

    wiki_context = {
        "role": "background_not_evidence",
        "fingerprint": "rag:1",
        "entries": [{"entry_id": "rag", "name": "RAG", "aliases": [], "key_papers": [], "version": 1}],
    }
    monkeypatch.setattr(qa_agentic, "_resolve_wiki_context_safe", lambda question, paper_ids: wiki_context)
    monkeypatch.setattr(qa_agentic, "_check_cache", lambda question, paper_ids, trace_id: None)
    monkeypatch.setattr(qa_agentic, "_retrieve_loop", lambda *args, **kwargs: ({
        "c1": {"chunk_id": "c1", "paper_id": "p1", "text": "RAG retrieves docs.", "score_dense": 0.9}
    }, [{"query": "q", "n_retrieved": 1, "reflect": None}], "answered"))
    monkeypatch.setattr(qa_agentic, "_decide_abstain", lambda chunks, cfg: {"decision": "confident", "evidence_score": 0.9})
    monkeypatch.setattr(qa_agentic, "select_evidence", lambda question, chunks, intent=None: (chunks, {}))
    monkeypatch.setattr(qa_agentic, "chat", lambda *args, **kwargs: "RAG retrieves docs [chunk:c1].")

    out = qa_agentic._answer_impl("What is RAG?", paper_ids=None, trace_id="t")

    assert out["trace"]["wiki_context"]["fingerprint"] == "rag:1"
    assert out["citations"] == ["c1"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src pytest -q tests/test_wiki_closed_loop_qa.py`

Expected: FAIL because signatures and helper functions do not exist.

- [ ] **Step 3: Implement query/retrieval changes**

Change `rewrite(question: str, wiki_context: dict | None = None) -> dict` and `retrieve_round_with_rewrite(..., wiki_context: dict | None = None)`. Add wiki aliases/name/definition keywords to dense queries and BM25 query. Keep old callers compatible.

- [ ] **Step 4: Implement QA changes**

Add safe wiki context resolution after history rewrite. Use `question_for_cache = f"{question}\\n\\nwiki_context_fingerprint:{fingerprint}"` for cache get/put. Pass wiki context into `_retrieve_loop` and `_build_user_prompt`. Add wiki background block to prompt only when entries exist. Add review queue enqueue for no chunks, no evidence, and weak evidence.

- [ ] **Step 5: Run tests to verify pass**

Run: `PYTHONPATH=src pytest -q tests/test_wiki_closed_loop_qa.py tests/test_wiki_context.py tests/test_wiki_review_queue.py`

Expected: PASS.

---

### Task 4: Feedback And Gateway Status

**Files:**
- Create: `src/paper_rag/wiki/usage.py`
- Modify: `src/paper_rag/feedback/collector.py`
- Modify: `integrations/deer-flow/backend/app/gateway/routers/paper_rag.py`
- Test: `tests/test_wiki_usage.py`
- Test: `tests/test_feedback_wiki_loop.py`
- Test: `integrations/deer-flow/backend/tests/test_paper_rag_integration.py`

**Interfaces:**
- Consumes: `review_queue.enqueue`
- Produces: `usage.record_consumption(question, paper_ids, wiki_context, trace_id) -> None`
- Produces: `usage.consumed_paper_ids() -> set[str]`
- Produces: Knowledge Builder fields `wiki_consumed: bool` and `wiki_review_needed: bool`

- [ ] **Step 1: Write failing feedback test**

```python
def test_thumbs_down_enqueues_wiki_review(monkeypatch):
    from paper_rag.feedback import collector

    recorded = []
    monkeypatch.setattr(collector, "_check_rate_limit", lambda user_id: None)
    monkeypatch.setattr(collector.store, "write", lambda ev: 123)
    monkeypatch.setattr(collector, "_enqueue_wiki_review_from_feedback", lambda event_type, payload, trace_id: recorded.append((event_type, payload, trace_id)))

    rid = collector.record_event("u1", "thumbs_down", {"reason": "incomplete", "question": "What is RAG?"}, trace_id="t1")

    assert rid == 123
    assert recorded == [("thumbs_down", {"reason": "incomplete", "question": "What is RAG?"}, "t1")]
```

- [ ] **Step 2: Write failing gateway test or extend existing integration test**

Add assertions that Knowledge Builder rows include `wiki_consumed` and `wiki_review_needed` with boolean values.

- [ ] **Step 3: Implement feedback hook**

In `record_event`, after `store.write`, call a private best-effort helper. Enqueue for configured `thumbs_down` reasons and `judge_score` values below 3.0.

- [ ] **Step 4: Implement wiki usage and gateway status fields**

Add `wiki_consumption_events` with trace id, paper id, entry id/name, fingerprint, question, and created_at. Record consumption from `qa_agentic` immediately after wiki context resolution when entries are present. Extend `KnowledgeBuildStatus` with `wiki_consumed: bool = False` and `wiki_review_needed: bool = False`. Compute consumed by scanning `wiki_consumption_events`; when the table is missing, return `False`. Compute review-needed by scanning pending `wiki_review_queue`; when the table is missing, return `False`.

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src pytest -q tests/test_wiki_usage.py tests/test_feedback_wiki_loop.py tests/test_gateway_paper_rag.py integrations/deer-flow/backend/tests/test_paper_rag_integration.py`

Expected: PASS or skip integration tests that require unavailable DeerFlow deps with the existing test behavior.

---

### Task 5: Frontend Wiki Consumption Display

**Files:**
- Modify: `integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx`

**Interfaces:**
- Consumes: `answer.trace.wiki_context.entries`
- Consumes: `KnowledgeBuild.wiki_consumed`, `KnowledgeBuild.wiki_review_needed`

- [ ] **Step 1: Update types**

Add:

```ts
type WikiTraceEntry = {
  entry_id?: string;
  name?: string;
  version?: number;
  aliases?: string[];
  key_papers?: string[];
};

type WikiTraceContext = {
  role?: string;
  fingerprint?: string;
  entries?: WikiTraceEntry[];
};
```

Extend `KnowledgeBuild` with `wiki_consumed?: boolean` and `wiki_review_needed?: boolean`.

- [ ] **Step 2: Render Ask wiki context**

In the Answer section, add a compact `Wiki Context` panel before Loop Trace when `answer.trace?.wiki_context?.entries?.length` is truthy. Render concept chips and the role text.

- [ ] **Step 3: Render Knowledge Builder badges**

Add badges beside wiki stage/status:

```tsx
{build.wiki_consumed && <Badge variant="default">wiki consumed</Badge>}
{build.wiki_review_needed && <Badge variant="destructive">wiki review</Badge>}
```

- [ ] **Step 4: Validate frontend**

Run: `cd integrations/deer-flow/frontend && pnpm lint`

Expected: PASS, or report existing unrelated lint failures separately.

---

### Task 6: Final Verification

**Files:**
- Review all changed files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_wiki_context.py \
  tests/test_wiki_review_queue.py \
  tests/test_wiki_closed_loop_qa.py \
  tests/test_feedback_wiki_loop.py \
  tests/test_wiki_pure.py \
  tests/test_gateway_paper_rag.py
```

Expected: PASS.

- [ ] **Step 2: Run frontend lint**

Run: `cd integrations/deer-flow/frontend && pnpm lint`

Expected: PASS.

- [ ] **Step 3: Run status check**

Run: `git status --short`

Expected: only intentional files are modified.

- [ ] **Step 4: Commit implementation**

Run:

```bash
git add src/paper_rag tests integrations/deer-flow/backend/app/gateway/routers/paper_rag.py integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx docs/superpowers/plans/2026-07-19-wiki-closed-loop-b.md
git commit -m "Implement wiki closed loop background context"
```

Expected: commit succeeds.
