# P0/P1/P2 Completion Plan

This is the working project map for taking the embedded DeerFlow Paper RAG from
usable MVP to a stable beta.

## P0 - Stability And Release Gate

Status: in progress, mostly complete.

Acceptance:

- `make verify-p0` passes.
- `make eval-golden` passes with positive paper recall at 1.0.
- `make eval-golden-qa` passes with citation existence and no-answer success at 1.0.
- `.env` stays local-only and `make secret-scan` is clean.
- DeerFlow backend/frontend can be started with `make deerflow-backend` and
  `make deerflow-frontend`.

Current baseline:

| Metric | Value |
|---|---:|
| Positive paper recall@10 | 1.0 |
| Positive paper MRR | 0.947 |
| Citation existence | 1.0 |
| Must-contain coverage | 1.0 |
| No-answer success | 1.0 |
| No-answer direct abstain | 1.0 |

## P1 - Product Closure

Status: functional beta.

Scope:

- DeerFlow-style `/workspace/paper-rag` UI.
- Real QA with loading, error, answer, citations, feedback.
- Papers list and paper detail affordances.
- Ingest UI with done/skipped/dedup/error states.
- Wiki generation entry.
- Inbox read/dismiss.
- Subscription add/pause/resume/delete.

Acceptance:

- Backend integration tests cover each product API surface.
- Frontend typecheck and lint pass for the Paper RAG workspace page.
- Manual smoke covers QA, feedback, ingest, wiki, inbox, and subscriptions.

## P2 - RAG Quality System

Status: established, needs scale-up.

Scope:

- Strict golden set for release gates.
- Exploratory real set for finding failure modes.
- Feedback-derived hard cases.
- Query rewrite heuristics for known weak spots.
- Abstain calibration for no-answer behavior.
- Citation validation and suspicious citation stripping.

Acceptance:

- Golden set is the release gate.
- Real set and hard cases are used for exploratory optimization.
- New RAG changes include before/after eval JSON in `data/index/eval_runs/`.
- Chunk-level ground truth is added for citation precision as the set grows.

Next scale targets:

- Expand `qa_set.golden.jsonl` from 22 to 50-100 questions.
- Add `relevant_chunk_ids` for 10-20 high-value questions.
- Add LLM judge runs only after retrieval/no-judge metrics stay stable.
