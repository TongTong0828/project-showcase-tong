# Wiki Closed Loop B Design

## Goal

Upgrade wiki from a side-channel generated artifact into a consumed, traceable, self-evolving research background layer.

This is a full B-scope implementation:

- Wiki entries may be injected into QA as background context.
- Wiki entries may guide query rewrite and retrieval.
- Wiki entries must never be treated as final answer evidence.
- Final answers must still cite only indexed paper chunks with `[chunk:<id>]`.
- QA failures and user feedback should create review pressure back into wiki.
- UI and traces should show when wiki context was used.

## Non-Goals

- Do not implement C-scope wiki-as-answer-source behavior.
- Do not allow citations to wiki entries.
- Do not use wiki content to bypass abstain or citation validation.
- Do not redesign the whole paper_rag UI.
- Do not replace existing chunk retrieval, reranking, or evidence selection.

## Product Behavior

When a user asks `paper_qa`, the system should:

1. Resolve relevant wiki concepts from the question and optional `paper_ids`.
2. Build a compact `wiki_context` payload containing concept names, aliases, definitions, key papers, versions, and evidence chunk references.
3. Use that payload for query rewrite and retrieval hints.
4. Inject a concise "Wiki background, not evidence" block into the final answer prompt.
5. Instruct the model that wiki background may help interpret terms, but factual claims must be grounded only in provided evidence chunks.
6. Validate citations against selected evidence chunks exactly as today.
7. Return trace metadata showing which wiki entries were consumed.

The frontend Ask view should surface consumed wiki concepts when present. Knowledge Builder should distinguish generated wiki from consumed wiki and review-needed wiki.

## Architecture

### `paper_rag.wiki.context`

Add a small module responsible for read-only wiki consumption:

- `resolve_wiki_context(question, paper_ids=None, max_entries=3) -> WikiContext`
- Match by exact name, alias, semantic near miss, and optional key-paper overlap.
- Return compact serializable data, not ORM rows.
- Include a stable fingerprint derived from `entry_id:version` pairs.
- Mark the role as `background_not_evidence`.

The module should degrade quietly if wiki is disabled, empty, or unavailable.

### Query Rewrite Integration

Extend retrieval rewrite so wiki context can add:

- aliases as dense query variants,
- key paper titles or ids as hints when scoped,
- short definition keywords as BM25 expansion.

Existing callers should keep working without wiki context.

### QA Prompt Integration

In `qa_agentic`, resolve wiki context after history and memory rewrite but before retrieval. Use it in two places:

- retrieval/query rewrite hints,
- final answer prompt as a separate background block.

The final prompt must say:

- wiki background is not evidence,
- do not cite wiki background,
- if wiki conflicts with evidence chunks, evidence chunks win,
- every factual answer claim still needs `[chunk:<id>]`.

### Closed Loop Events

Add a lightweight wiki review queue table in the existing paper SQLite database:

- `id`
- `event_type`
- `concept`
- `paper_id`
- `question`
- `reason`
- `status`
- `payload_json`
- `created_at`
- `updated_at`

Initial event producers:

- QA no chunks.
- QA no evidence abstain.
- QA weak evidence.
- Feedback `thumbs_down` with reason `hallucination`, `irrelevant`, `incomplete`, or `wrong_citation`.
- Feedback `judge_score` when `faithful` or `complete` is below 3.0.

Review events must not block QA. Duplicate events are coalesced when the same event type, concept, paper id, and reason already exists in the previous 24 hours.

### Trace And Metrics

QA responses should include:

```json
{
  "trace": {
    "wiki_context": {
      "role": "background_not_evidence",
      "fingerprint": "...",
      "entries": [
        {
          "entry_id": "...",
          "name": "...",
          "version": 2,
          "aliases": ["..."],
          "key_papers": ["..."]
        }
      ]
    }
  }
}
```

Metrics should count wiki context hits, misses, and review queue events when the local metrics helper makes that straightforward.

QA should also persist lightweight wiki consumption events when wiki context
entries are present. These events power Knowledge Builder's consumed status and
should include trace id, paper id, wiki entry id/name, fingerprint, question,
and timestamp.

### Cache Safety

QA cache keys must account for wiki context fingerprint. If wiki context changes, a cached answer produced from older background should not be reused as if it used current background.

If changing the existing cache schema is risky, include the fingerprint in the effective question key at the call site.

### API And UI

Backend:

- Ensure QA sync responses pass through `trace.wiki_context`.
- Add Knowledge Builder signals for `wiki_status`, `wiki_consumed`, and `wiki_review_needed`.
- Compute `wiki_consumed` from `wiki_consumption_events`.
- Compute `wiki_review_needed` from pending `wiki_review_queue` rows.

Frontend:

- In Ask results, show consumed wiki concept chips when `trace.wiki_context.entries` is present.
- In Knowledge Builder, show whether wiki is `ready`, `consumed`, or `review-needed`.
- Keep generated wiki viewing behavior intact.

## Data Flow

```text
ingest -> wiki queue -> create/patch entries
                          |
paper_qa question --------+
  -> resolve wiki_context
  -> query rewrite expansion
  -> chunk retrieval/rerank
  -> final prompt with wiki background
  -> citation validation against chunks only
  -> trace wiki_context
  -> weak/no evidence events enqueue wiki review
```

## Error Handling

- Wiki resolution failures are non-fatal.
- Wiki queue/review queue failures are non-fatal.
- If wiki background is empty, QA behavior remains equivalent to the current flow.
- If wiki context exists but chunk evidence is weak or missing, abstain remains authoritative.
- If wiki and chunks disagree, prompt and tests require chunks to win.

## Testing

Add focused tests for:

- wiki context resolution by name, alias, semantic fallback stub, and paper overlap.
- query rewrite receives wiki aliases/definition terms.
- QA prompt includes wiki background when available.
- wiki background cannot produce wiki citations or non-chunk citations.
- no-evidence and weak-evidence paths enqueue review events.
- cache key/fingerprint changes when wiki entry versions change.
- API response preserves `trace.wiki_context`.
- frontend renders wiki concept chips from QA trace.

## Acceptance Criteria

- A `paper_qa` call can visibly consume wiki background in trace.
- Final answer citations are still validated only against selected chunks.
- Wiki context changes invalidate or bypass stale QA cache entries.
- Weak/no-evidence QA paths create non-blocking wiki review events.
- The Ask UI shows consumed wiki concepts.
- Existing wiki generation and manual wiki viewing continue to work.
