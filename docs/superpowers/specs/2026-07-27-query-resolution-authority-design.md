# Query Resolution Authority Design

## Goal

Make `paper_qa` follow one authoritative query-resolution decision per turn.
The DeerFlow outer agent owns general conversation references such as
"it", "this paper", "the second one", and topic switches when it has already
resolved them. Paper RAG owns paper-domain fallback resolution only when the
caller has not supplied an outer resolution. Final answer evidence remains the
retrieved paper chunks from the current QA run.

## Non-Goals

- Do not change dense retrieval, BM25, RRF, reranking, reflection, citation
  validation, abstain policy, or wiki generation behavior.
- Do not let DeerFlow internals leak into the standalone `paper_rag` package.
- Do not use memory summaries, history rows, wiki background, or cached answer
  metadata as final-answer evidence.
- Do not remove old history tables in the first release. Migration must be
  non-destructive.
- Do not require existing REST or Python callers to send new fields.

## Current Problems

`qa_agentic.answer()` currently rewrites the same question twice:

- `_maybe_rewrite_with_research_memory()` runs before `_answer_impl()`.
- `_maybe_rewrite_with_history()` runs inside `_answer_impl()`.

The two rewriters can disagree about pronouns or ordinal references. They also
persist overlapping turn data in `qa_history` and `research_memory_turns`.

The DeerFlow tool wrapper exposes only `question` and `paper_ids`, so the
outer agent cannot pass its resolved interpretation to Paper RAG. The REST
sync endpoint forwards `conversation_id`, but streaming ignores it. Cache hits
also return answer metadata without rehydrated evidence chunks, which weakens
the "current chunks are the evidence" debugging contract.

## Product Behavior

When the user asks a follow-up after comparing papers, the caller behavior is:

```json
{
  "question": "How does the second one do retrieval?",
  "resolved_question": "How does FLARE do retrieval?",
  "paper_ids": ["arxiv:2305.06983"]
}
```

Paper RAG must retrieve with `resolved_question`. It may load research memory
only for paper-scope hints and turn persistence. It must not run an additional
history or memory rewrite that can replace the outer decision.

When direct REST or Python callers send only:

```json
{
  "question": "How does the second one do retrieval?",
  "conversation_id": "conv-123"
}
```

Paper RAG may run exactly one internal fallback resolver using recent turns and
compressed research memory. If there is no `conversation_id`, QA stays
single-turn and uses the raw question.

Explicit `paper_ids` are always a hard retrieval constraint. Paper scope from
research memory is a soft hint only and cannot expand, override, or narrow an
explicit caller-supplied `paper_ids` list.

## Architecture

Add a focused resolver layer under `paper_rag.rag`:

- `context_resolver.py` owns query-resolution policy and trace metadata.
- `conversation_turn_store.py` owns turn storage and tenant-scoped reads.
- `history.py` becomes a compatibility facade over `conversation_turn_store`.
- `research_memory.py` reads recent turns through `conversation_turn_store` and
  writes summaries through tenant-scoped summary storage.
- `qa_agentic.py` and `qa_stream.py` both call the same resolver before
  retrieval, cache lookup, wiki resolution, generation, and persistence.

The standalone `paper_rag` package remains independent. DeerFlow and REST
derive runtime context at their adapter boundaries and pass plain values into
`paper_rag`.

## Public Contracts

Model-visible DeerFlow tool arguments:

```python
class PaperQAToolInput(BaseModel):
    question: str
    paper_ids: list[str] | None = None
    resolved_question: str | None = None
```

The model may supply `resolved_question` only when it has made the question
self-contained from DeerFlow checkpoint or thread state. The model must not
supply `user_id`, `conversation_id`, `memory_mode`, or `context_source`.

REST request body:

```python
class QARequest(BaseModel):
    question: str
    paper_ids: list[str] | None = None
    conversation_id: str | None = None
    resolved_question: str | None = None
```

REST derives `user_id` from authentication. Direct REST clients may supply
`resolved_question`; the trace source for that case is `api_resolved`.

Python API:

```python
def answer(
    question: str,
    *,
    paper_ids: list[str] | None = None,
    conversation_id: str | None = None,
    user_id: str = "system",
    resolved_question: str | None = None,
) -> dict: ...
```

`user_id="system"` preserves existing local single-user behavior.

Internal request context:

```python
@dataclass(frozen=True)
class QARequestContext:
    raw_question: str
    outer_resolved_question: str | None
    explicit_paper_ids: tuple[str, ...]
    conversation_id: str | None
    user_id: str
    caller: Literal["deerflow", "rest", "python"]
```

Resolver output:

```python
@dataclass(frozen=True)
class QueryResolution:
    raw_question: str
    effective_question: str
    source: Literal[
        "outer_checkpoint",
        "api_resolved",
        "paper_rag_recent_turns",
        "paper_rag_research_memory",
        "none",
    ]
    policy: Literal["authoritative_outer", "inner_fallback", "single_turn"]
    rewrite_applied: bool
    outer_resolution_used: bool
    explicit_paper_ids: tuple[str, ...]
    memory_paper_scope_hint: tuple[str, ...]
    effective_paper_ids: tuple[str, ...]
    conflicts: tuple[str, ...]
    memory_used_as_evidence: bool = False
```

`context_source` and `memory_mode` are derived from this output for trace
compatibility. They are not trusted request inputs.

## Resolution Policy

The resolver applies this priority:

1. If `outer_resolved_question` is non-empty, use it as
   `effective_question`. Set policy `authoritative_outer`. Skip all internal
   query rewriting. Load memory only to compute `memory_paper_scope_hint`.
2. Else if `conversation_id` is present, load tenant-scoped recent turns and
   compressed research memory, then run one internal fallback rewrite. Set
   policy `inner_fallback`. The resolver chooses source
   `paper_rag_recent_turns` or `paper_rag_research_memory` based on the data
   that materially affected the rewrite.
3. Else use `raw_question` unchanged. Set policy `single_turn` and source
   `none`.

There must be no path where both old `history.rewrite_with_history()` and
`research_memory.rewrite_with_memory()` can rewrite the same request.

If internal rewrite fails, log a non-fatal warning, keep the raw question, set
source `none`, and continue QA. If memory hints conflict with explicit
`paper_ids`, keep explicit `paper_ids` and add a conflict string to the trace.

## Data Flow

```text
DeerFlow checkpoint or REST body
  -> adapter derives user_id and conversation_id
  -> QARequestContext
  -> context_resolver.resolve_query()
  -> wiki context using effective_question
  -> cache lookup using effective inputs
  -> retrieval and rerank using effective_question and hard paper_ids
  -> final prompt with retrieved chunks as evidence
  -> citation validation against selected chunks only
  -> trace query_resolution
  -> persist one tenant-scoped turn
  -> update research summary best-effort
```

Wiki context stays `background_not_evidence`. It can help query expansion and
the model's terminology, but it is not a resolver authority and never supplies
citations.

## Storage And Migration

Create canonical storage APIs:

```python
append_turn(
    *,
    user_id: str,
    conversation_id: str,
    raw_question: str,
    effective_question: str,
    answer: str,
    citations: list[str],
    paper_ids: list[str],
    trace: dict,
    resolution_source: str,
) -> None

recent_turns(
    *,
    user_id: str,
    conversation_id: str,
    limit: int = 3,
) -> list[ConversationTurn]
```

Back the API with new SQLite tables:

- `conversation_turns`
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `user_id TEXT NOT NULL`
  - `conversation_id TEXT NOT NULL`
  - `raw_question TEXT NOT NULL`
  - `effective_question TEXT NOT NULL`
  - `answer TEXT NOT NULL`
  - `citations_json TEXT NOT NULL`
  - `paper_ids_json TEXT NOT NULL`
  - `trace_json TEXT NOT NULL`
  - `resolution_source TEXT NOT NULL`
  - `created_at TEXT NOT NULL`
- `conversation_summaries`
  - `user_id TEXT NOT NULL`
  - `conversation_id TEXT NOT NULL`
  - `session_summary TEXT NOT NULL`
  - `research_memory_json TEXT NOT NULL`
  - `n_turns INTEGER NOT NULL`
  - `updated_at TEXT NOT NULL`
  - primary key `(user_id, conversation_id)`

Indexes:

- `conversation_turns(user_id, conversation_id, id)`
- `conversation_turns(user_id, conversation_id, created_at)`

Migration is lazy and non-destructive:

- If canonical tables are empty for `(user_id, conversation_id)`, best-effort
  copy matching rows from `research_memory_turns` and `qa_history`.
- Legacy rows without `user_id` migrate under `user_id="system"`.
- After canonical storage exists, new QA turns write only canonical turn rows.
- Old tables remain readable for rollback and are not dropped in this feature.

All memory reads and writes must filter by both `user_id` and
`conversation_id`.

## DeerFlow Adapter

The DeerFlow community tool remains an adapter. It should:

- add optional model-visible `resolved_question`;
- derive `conversation_id` from tool runtime context `thread_id` when
  available;
- derive `user_id` from DeerFlow runtime user context when available;
- fall back to `conversation_id=None` if no thread context is present;
- return `query_resolution` in the JSON payload along with answer, citations,
  abstain, trace id, and chunks.

If the exact LangChain runtime injection mechanism is not available for this
tool wrapper, add a small helper that reads the same runtime locations used by
DeerFlow middlewares: `runtime.context["thread_id"]` first, then
`configurable.thread_id` as fallback.

## Sync And Streaming

`qa_agentic.answer()` and `qa_stream.stream_answer()` must accept the same
contextual parameters:

```python
paper_ids: list[str] | None
conversation_id: str | None
user_id: str
resolved_question: str | None
```

Both paths must call the shared resolver once and expose the same
`trace.query_resolution` shape. Streaming may keep its existing event sequence,
but its retrieval query and persistence behavior must match sync for the same
inputs.

The REST `/api/paper_rag/qa` streaming endpoint must pass `conversation_id`,
`user_id`, and `resolved_question` to `stream_answer()`. `/qa/sync` must pass
the same fields to `answer()`.

## Cache Safety

QA cache lookup happens after query resolution and wiki resolution.

The cache key must include:

- `user_id`
- normalized `effective_question`
- sorted hard `paper_ids`
- wiki fingerprint
- memory paper-scope fingerprint if that hint changes retrieval inputs
- QA pipeline version string

Do not key cache entries by raw question alone. `How about it?` in two
different conversations must not share a cache entry unless the effective
question and all functional context are identical.

Cache payloads must store selected evidence chunk ids plus a corpus or chunk
content fingerprint. On cache hit, rehydrate chunks from the current store and
verify the fingerprint. If chunks cannot be rehydrated or the fingerprint is
stale, treat the entry as a miss and run QA normally.

## Trace Contract

Every sync response and streaming `done` event must include:

```json
{
  "query_resolution": {
    "raw_question": "...",
    "effective_question": "...",
    "source": "outer_checkpoint",
    "policy": "authoritative_outer",
    "rewrite_applied": false,
    "outer_resolution_used": true,
    "explicit_paper_ids": ["arxiv:2305.06983"],
    "memory_paper_scope_hint": [],
    "effective_paper_ids": ["arxiv:2305.06983"],
    "conflicts": [],
    "memory_used_as_evidence": false
  }
}
```

For backward compatibility, the top-level response may also expose
`trace.query_resolution`. Existing `trace.memory` may remain, but it must not
be placed inside the final prompt's `Evidence:` block.

## Prompt And Evidence Rules

The final QA prompt may contain:

- the system instructions;
- the user's effective question;
- wiki background marked `background_not_evidence`;
- selected paper chunks under the evidence block.

The final QA prompt must not contain:

- raw `research_memory.confirmed_findings`;
- prior answer previews as evidence;
- `qa_history` rows as evidence;
- wiki citations as accepted answer citations.

Citation validation remains authoritative. Accepted citations must correspond
to selected chunk ids.

## Error Handling

- Resolver failures are non-fatal and fall back to single-turn raw question.
- Memory load, migration, persistence, and summarization failures are
  non-fatal and recorded in trace when practical.
- Missing authenticated `user_id` in REST remains a 401 as today.
- Missing runtime `thread_id` in DeerFlow means no conversation fallback for
  that tool call.
- Outer and memory conflicts do not trigger a second LLM adjudication. The
  outer resolution wins and the conflict is reported in trace.

## Testing

Add focused tests for:

- outer `resolved_question` bypasses all internal rewriters;
- no `resolved_question` plus `conversation_id` invokes exactly one internal
  resolver;
- no `conversation_id` keeps single-turn behavior;
- "first/second" and "this paper/that paper/it" after topic switches;
- explicit `paper_ids` cannot be overridden by memory paper-scope hints;
- direct REST sync and streaming pass the same contextual fields;
- direct REST without outer resolution still uses Paper RAG fallback memory;
- memory summaries and recent-turn answer previews never enter final
  `Evidence:`;
- sync and streaming expose matching `query_resolution` fields;
- same `conversation_id` under two `user_id` values cannot share turns,
  summaries, or cache entries;
- cache key separates contextual follow-ups and rehydrates chunk evidence on
  hit;
- DeerFlow model-visible tool schema excludes `user_id`, `conversation_id`,
  `memory_mode`, and `context_source`;
- old `qa_history` and `research_memory_turns` rows can be lazily migrated or
  read for compatibility.

## Acceptance Criteria

- `paper_qa` has one query-resolution authority per request.
- DeerFlow can pass an authoritative `resolved_question` and Paper RAG will not
  rewrite over it.
- Direct REST and Python callers keep multi-turn fallback when they provide
  `conversation_id`.
- Sync and streaming QA resolve and trace questions consistently.
- Memory and wiki context can guide scope or terminology but never become final
  answer evidence.
- Cache hits cannot cross users, conversations, effective questions, paper
  scopes, wiki fingerprints, or stale evidence snapshots.
- Existing single-turn callers keep working without request changes.
