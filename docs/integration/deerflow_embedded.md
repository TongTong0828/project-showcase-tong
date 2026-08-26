# Embedded DeerFlow Integration

This repository now carries a modified DeerFlow checkout at
`integrations/deer-flow`. It is the runnable host application for the
`paper_rag` gateway and UI integration.

## Layout

| Path | Purpose |
|---|---|
| `integrations/deer-flow/backend/app/gateway/routers/paper_rag.py` | HTTP API adapter for `paper_rag` |
| `integrations/deer-flow/backend/app/gateway/routers/metrics.py` | Prometheus-compatible `/metrics` endpoint |
| `integrations/deer-flow/frontend/src/app/workspace/paper-rag/page.tsx` | DeerFlow workspace UI |
| `scripts/deerflow_smoke.py` | Repeatable endpoint smoke check |

## Local run

Create/install the embedded DeerFlow backend virtualenv first, install the RAG
extras needed for real QA, then configure `.env`:

```bash
integrations/deer-flow/backend/.venv/bin/python -m pip install -e ".[embed,ingest]"
cp .env.example .env
```

For DeepSeek/OpenAI-compatible QA, keep real keys only in `.env`:

```bash
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-...
CHAT_MODEL=deepseek-chat
PAPER_RAG_CONFIG=config/local.yaml
```

Start the gateway:

```bash
make deerflow-backend
```

The backend target loads `.env` from the repository root when it exists and
defaults `PAPER_RAG_CONFIG` to `config/local.yaml`, which uses embedded Qdrant
for docker-free local demos.

In a second terminal:

```bash
make deerflow-frontend
```

The frontend target uses DeerFlow's same-origin `/api/*` rewrite and points it
at the local gateway through `DEER_FLOW_INTERNAL_GATEWAY_BASE_URL`. Do not set
`NEXT_PUBLIC_BACKEND_BASE_URL` for this local flow unless the gateway also
allows credentialed browser CORS.

Then smoke-check the gateway:

```bash
make deerflow-smoke
```

The smoke script checks `/api/paper_rag/status` and reports whether QA is in
`evidence-only` mode or backed by a configured LLM. Evidence-only is acceptable
for integration wiring checks, but not for the final real QA demo.

If dense retrieval logs show `dense=0` or `Collection paper_chunks not found`,
rebuild the embedded Qdrant index from already parsed papers:

```bash
make deerflow-rebuild-index
```

For a real RAG answer, install the embedding extras and configure the model
environment:

```bash
python scripts/deerflow_smoke.py \
  --base-url http://127.0.0.1:8001 \
  --timeout 180 \
  --qa-question "Summarize the indexed RAG papers." \
  --require-llm-answer
```

## Regression gates

Use these checks before changing DeerFlow wiring or RAG behavior:

```bash
make verify-p0
make eval-golden-qa
```

`make verify-p0` runs focused lint/tests, import smoke, secret scan, and
retrieval-only golden eval. `make eval-golden-qa` runs the strict QA golden set
with real LLM generation but no LLM judge.

Latest local golden QA baseline:

| Metric | Value |
|---|---:|
| Positive paper recall@10 | 1.0 |
| Positive paper MRR | 0.947 |
| Citation existence | 1.0 |
| Must-contain coverage | 1.0 |
| No-answer success | 1.0 |
| No-answer direct abstain | 1.0 |

## Blocking status

The DeerFlow wiring is blocking only if the gateway, UI page, or core
`paper_rag` endpoints fail to start. Full QA generation depends on heavier RAG
runtime dependencies (`FlagEmbedding`, provider credentials, and local index
state), but this path has a repeatable smoke and golden-eval gate now.

RAG optimization is no longer deferred: use the golden set as the stable gate,
and use `tests/eval/qa_set.real.jsonl` plus feedback-derived hard cases for
exploration.
