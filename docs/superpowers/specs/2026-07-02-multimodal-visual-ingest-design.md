# Multimodal Visual Ingest Design

Date: 2026-07-02
Status: Approved for implementation planning
Owner: Paper RAG Agent

## Summary

Paper RAG already extracts figure, table, and formula chunks from MinerU/PyMuPDF markdown and stores `modality`, `asset_rel_path`, and `asset_path` when available. The current searchable text for figure chunks is mostly caption, surrounding context, and image path. This design upgrades ingestion so extracted figures and visual tables are summarized by a vision model, then indexed as enriched textual evidence while preserving the original image asset for UI inspection.

The selected approach is:

1. Use an OpenAI-compatible vision API as the primary visual summarizer.
2. Fall back to a lazy local Qwen2.5-VL adapter when the API is unavailable and local dependencies are installed.
3. If both summarizers fail, keep ingestion successful and fall back to the current caption/context behavior.
4. Store the visual summary and provenance metadata in existing chunk records.
5. Continue using the existing SQLite + Qdrant text-embedding retrieval stack instead of adding a separate image-vector index in this phase.

## Goals

- Improve recall and answer quality for questions about figures, diagrams, plots, screenshots, and visual tables.
- Convert image assets into citable text evidence through structured multimodal summaries.
- Preserve traceability from a summarized visual chunk back to the original image file.
- Control API cost through caching and per-paper limits.
- Keep ingestion robust: visual summarization failure must not fail paper ingestion.
- Reuse the existing retrieval, rerank, abstain, citation, and DeerFlow integration paths.

## Non-Goals

- Do not add CLIP/SigLIP-style image embeddings or a separate image vector collection in this phase.
- Do not require every environment to install a local vision model.
- Do not make QA cite uncached external metadata or non-indexed discovery candidates.
- Do not introduce full visual grounding or pixel-level verification claims; summaries are model-generated evidence annotations and must remain inspectable.
- Do not redesign the DeerFlow UI in the first implementation pass, beyond exposing enough metadata for a later citation image preview.

## Current State

Relevant existing components:

- `src/paper_rag/parse/mineru_local.py` copies MinerU image assets into `data/parsed/<paper_id>/figures/` and rewrites markdown image paths.
- `src/paper_rag/chunk/multimodal_chunker.py` extracts `figure`, `table`, and `formula` chunks from parsed markdown.
- `src/paper_rag/chunk/builder.py` resolves `asset_rel_path` into `asset_path`.
- `src/paper_rag/store/sqlite_store.py` stores chunk metadata including `modality`, `asset_path`, and `asset_rel_path`.
- `src/paper_rag/store/qdrant_store.py` stores chunk payloads and supports `modality` filtering.
- `src/paper_rag/retrieve/pipeline.py` detects figure/table/formula query hints and adds modality-specific retrieval.
- `src/paper_rag/rag/qa_agentic.py` already returns retrieved chunks internally for inspection, though the gateway response does not yet expose visual asset URLs.

The missing piece is model-based visual understanding before the chunk is embedded and indexed.

## Proposed Architecture

```text
PDF
  -> parse dispatcher
  -> MinerU / PyMuPDF parsed_dir
  -> paper.md + figures/
  -> multimodal chunk extraction
  -> visual summarization enrichment
  -> SQLite chunks + Qdrant payloads
  -> retrieval with modality hints
  -> QA citations
```

The new enrichment stage runs inside chunk building or immediately after chunk building, before SQLite/Qdrant upsert. It only mutates chunks with a visual asset and visual modality.

Target modalities for the first pass:

- `figure`: enabled when `asset_path` exists and points to a supported image file.
- `table`: use vision summarization only when there is an associated asset; markdown table text continues to work without a vision call.
- `formula`: out of scope for vision summarization; formulas remain text/LaTeX chunks.

## Data Model

Existing `Chunk` records already support JSON-like `metadata` and path fields. The implementation should avoid a disruptive schema migration unless current serialization cannot preserve the new fields. The preferred representation is:

```json
{
  "chunk_id": "figure chunk id",
  "paper_id": "arxiv:...",
  "modality": "figure",
  "text": "Figure: <caption>\nContext: <context>\nVisual summary: <summary>",
  "asset_rel_path": "figures/foo.png",
  "asset_path": "/abs/path/data/parsed/.../figures/foo.png",
  "metadata": {
    "element_type": "figure",
    "caption": "...",
    "surrounding_context": "...",
    "visual_summary": "...",
    "visual_summary_status": "ok",
    "visual_summary_provider": "api",
    "visual_summary_model": "qwen-vl-plus",
    "visual_summary_cache_key": "sha256:...",
    "visual_summary_error": null
  }
}
```

Allowed `visual_summary_status` values:

- `ok`: primary API model produced the summary.
- `fallback`: local fallback model produced the summary.
- `cached`: summary was loaded from cache.
- `skipped`: summarization was intentionally skipped, for example disabled config, unsupported file type, or per-paper limit exceeded.
- `failed`: summarizers failed, but ingestion continued with caption/context.

The `text` field used for embedding should include:

```text
Figure/Table label
Caption or alt text
Nearby paper context
Visual summary
Original asset relative path
```

This keeps dense retrieval and FTS retrieval compatible with existing code.

## Configuration

Add a new `vision` config block:

```yaml
vision:
  enabled: true
  provider: openai_compatible
  base_url: ${VISION_BASE_URL}
  api_key: ${VISION_API_KEY}
  model: qwen-vl-plus
  timeout_sec: 60
  fallback_local: true
  local_model: Qwen/Qwen2.5-VL-7B-Instruct
  max_images_per_paper: 40
  max_image_bytes: 8000000
  cache: true
  cache_dir: ./data/index/vision_cache
```

Environment variables:

- `VISION_BASE_URL`
- `VISION_API_KEY`
- `VISION_MODEL`

If `VISION_*` values are missing but `vision.enabled` is true, the system should try local fallback when enabled. If no usable summarizer exists, chunks are marked `skipped` or `failed` and ingestion continues.

## Visual Summary Prompt

The vision prompt should be deterministic and evidence-oriented. It should ask for a concise structured summary:

```text
You are summarizing a figure or visual table from an academic paper.
Use the image plus the provided caption and nearby paper context.
Do not invent exact numbers that are not legible.
If text or values are unclear, say "not legible".
Return compact JSON with:
- visual_type
- main_message
- axes_or_dimensions
- key_entities
- trends_or_comparisons
- supports_claim
- limitations_or_uncertainty
```

The stored `visual_summary` is a normalized prose rendering of that JSON so it embeds well. When the model returns valid JSON, the raw object is also stored in `metadata.visual_summary_raw`.

## API Summarizer

Add a module shaped around a small interface:

```python
class VisionSummarizer(Protocol):
    def summarize(self, request: VisualSummaryRequest) -> VisualSummaryResult: ...
```

Primary adapter:

- OpenAI-compatible chat completions with image input.
- Encodes the image as base64 data URL or uses provider-supported image URL/file input if available.
- Uses explicit timeout and small retry budget.
- Returns structured status and error details without throwing through the ingest pipeline except for programmer/config errors.

The adapter should live under a focused namespace such as:

```text
src/paper_rag/vision/
  __init__.py
  schema.py
  api.py
  local.py
  cache.py
  enrich.py
```

## Local Fallback

The first local fallback is a Qwen2.5-VL-compatible lazy adapter. It is optional at runtime because normal installations should not be forced to install heavy local vision dependencies. The adapter should:

- Be lazy-imported.
- Be disabled unless `vision.fallback_local: true`.
- Return an unavailable result when dependencies or model weights are missing.
- Avoid making normal ingestion import heavy vision dependencies.

This keeps the API-first path simple while still providing a concrete local fallback when the environment is prepared for it.

## Cache and Cost Control

Cache key:

```text
sha256(image bytes + caption + surrounding_context + model + prompt_version)
```

Cache value:

```json
{
  "status": "ok",
  "provider": "api",
  "model": "...",
  "prompt_version": "v1",
  "summary": "...",
  "raw": {...},
  "created_at": "..."
}
```

Cache behavior:

- If cache hit, do not call the model.
- Cache successful summaries.
- Do not cache failed model calls in the first implementation pass.
- Respect `max_images_per_paper` before making model calls.
- Skip files larger than `max_image_bytes` unless resizing is implemented.

## Retrieval and QA Behavior

No new retrieval architecture is needed for the first phase. Enriched chunks are embedded as text and indexed into the current Qdrant collection. Existing modality hinting should continue to work:

- Queries containing `figure`, `diagram`, `plot`, `image`, `图`, `图像`, `图表`, `示意图` should retrieve `modality=figure`.
- Queries containing `table`, `表`, `表格` should retrieve `modality=table`.

QA should continue to cite chunk ids with `[chunk:<id>]`. If a visual chunk is cited, the answer is grounded in the visual summary and surrounding context, not in raw pixels at answer time.

## DeerFlow and API Surface

Initial implementation can keep the current QA response shape unchanged, but chunk payloads should preserve:

- `modality`
- `asset_rel_path`
- `asset_path`
- `metadata.visual_summary`
- `metadata.visual_summary_status`

A follow-up UI task can expose cited visual chunks in the frontend by mapping safe asset URLs to `asset_path`. That UI task should be separate because it requires serving local image assets safely through the DeerFlow gateway.

## Failure Handling

Visual summarization is non-blocking:

- Missing API key: try local fallback if enabled; otherwise mark `skipped`.
- API timeout/error: try local fallback if enabled; otherwise mark `failed`.
- Local fallback unavailable: mark `failed`.
- Missing image file: mark `skipped` and keep caption/context.
- Invalid JSON from model: recover a plain-text summary when possible; otherwise mark `failed`.

All failures should be logged with enough detail for diagnosis but without leaking API keys or image data.

## Testing Strategy

Unit tests:

- Extracted figure chunks with `asset_path` are passed to the enrichment stage.
- API summarizer mock success appends `visual_summary` to chunk text and metadata.
- API summarizer mock failure triggers local fallback.
- API and local failure does not fail ingestion.
- Cache hit avoids model calls.
- `max_images_per_paper` produces `skipped` statuses after the limit.
- Oversized image produces `skipped`.
- Metadata survives SQLite and Qdrant payload upsert.
- Figure/image query terms trigger modality-specific retrieval.

Integration tests:

- Ingest a fixture paper markdown with one local figure asset.
- Run the pipeline with a fake vision adapter.
- Verify the resulting chunk count, metadata, Qdrant payload, and retrieval result.

No real external API calls should run in default tests.

## Observability

Add counters or structured logs for:

- `paper_rag_vision_summary_total{status,provider}`
- `paper_rag_vision_summary_cache_total{result}`
- `paper_rag_vision_summary_latency_ms{provider}`
- `paper_rag_vision_summary_skipped_total{reason}`

Metrics should use the existing observability helper pattern. If the helper is unavailable in a minimal environment, summarization continues and logs structured events instead.

## Rollout Plan

1. Add config and schema with defaults that do not break existing installs.
2. Add vision summarizer interfaces, API adapter, lazy Qwen2.5-VL fallback adapter, and cache.
3. Add enrichment stage into chunk build or ingest pipeline.
4. Add tests around mocked success/failure/cache/limits.
5. Update README and MinerU docs with vision summarization setup.
6. Keep UI image preview as a separate follow-up task.

## Implementation Decisions

- The first implementation uses an OpenAI-compatible chat-completions image message format with base64 data URLs. Provider-specific URL/file upload variants are left for later.
- `visual_summary` and related fields are stored inside chunk `metadata`; no first-class SQLite columns are added in this phase.
- The local fallback is implemented as a real lazy Qwen2.5-VL adapter that reports `unavailable` when dependencies or weights are missing.

## Acceptance Criteria

- With a mocked API vision model, ingesting a paper with a figure stores a visual summary in the figure chunk metadata.
- The figure chunk text embedded into Qdrant includes caption, context, and visual summary.
- If the API model fails and local fallback succeeds, chunk metadata records `visual_summary_status: fallback`.
- If all summarizers fail, ingest completes and records `visual_summary_status: failed` or `skipped`.
- Re-ingesting the same image uses cache and does not call the API mock again.
- A query mentioning a figure or image can retrieve the enriched figure chunk.
- Default tests do not require network access, API keys, or local vision model weights.
