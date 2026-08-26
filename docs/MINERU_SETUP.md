# MinerU Setup and Verification

This project treats MinerU as the preferred PDF parser and falls back to
PyMuPDF when MinerU is not ready. Use the doctor command before large ingests:

```bash
PAPER_RAG_CONFIG=config/local.yaml .venv/bin/python scripts/mineru_doctor.py
```

## Install Dependencies

In a terminal with network access:

```bash
.venv/bin/python -m pip install -U -e ".[mineru]"
```

The project `mineru` extra installs `magic-pdf[full]` and
`opencv-python-headless`. The full extra is required for modules such as
`doclayout_yolo`, `ultralytics`, `rapid_table`, `pyclipper`, and `shapely`.

If editable install is not desired:

```bash
.venv/bin/python -m pip install -U "magic-pdf[full]>=1.3.12,<2" opencv-python-headless
```

## Model Weights

`config/magic-pdf.json` points MinerU at:

```text
data/index/mineru_models
```

For the current CPU/local config, layout recognition uses `doclayout_yolo`.
The doctor checks for this enabled weight:

```text
data/index/mineru_models/Layout/YOLO/doclayout_yolo_docstructbench_imgsz1280_2501.pt
```

Download MinerU model weights using the official MinerU model download guide:

```text
https://github.com/opendatalab/MinerU/blob/master/docs/how_to_download_models_en.md
```

Keep the directory layout from MinerU's `model_configs.yaml`.

For the currently enabled layout-only CPU config, this helper downloads the
first required weight:

```bash
PAPER_RAG_CONFIG=config/local.yaml \
  .venv/bin/python scripts/download_mineru_layout_model.py
```

## Try One Parse

After dependencies and weights are present:

```bash
PAPER_RAG_CONFIG=config/local.yaml \
  .venv/bin/python scripts/mineru_doctor.py \
  --try-parse data/papers/arxiv_2310.11511/raw.pdf \
  --paper-id arxiv:2310.11511 \
  --strict
```

Expected result:

- all doctor checks pass;
- `data/parsed/arxiv_2310.11511/paper.md` is produced by MinerU;
- `data/parsed/arxiv_2310.11511/figures/` contains copied local assets when images are extracted.

## Optional Vision Summaries for Figures and Tables

MinerU gives Paper RAG the local image assets. The optional vision enrichment
stage turns those assets into searchable text evidence before chunks are
embedded:

```text
figure/table image + caption + nearby context
  -> OpenAI-compatible vision API
  -> visual_summary metadata
  -> enriched chunk text
  -> SQLite + Qdrant
```

Enable it in `config/local.yaml`:

```yaml
vision:
  enabled: true
  base_url: $VISION_BASE_URL
  api_key: $VISION_API_KEY
  model: $VISION_MODEL
```

Then set local environment variables:

```bash
export VISION_BASE_URL=https://your-vision-provider.example/v1
export VISION_API_KEY=sk-your-vision-key
export VISION_MODEL=qwen-vl-plus
```

If the API is unavailable, a local Qwen2.5-VL fallback can be enabled:

```bash
.venv/bin/python -m pip install -U -e ".[vision-local]"
```

```yaml
vision:
  fallback_local: true
  local_model: Qwen/Qwen2.5-VL-7B-Instruct
```

Visual summarization never blocks ingest. If the API key is missing, the API
times out, local dependencies are unavailable, or the image file is missing,
the chunk remains indexed with the original caption/context and records a
`visual_summary_status` such as `skipped` or `failed`.

## Rebuild the RAG Index

Once MinerU parses the corpus successfully:

```bash
PAPER_RAG_CONFIG=config/local.yaml .venv/bin/python scripts/rebuild_index_from_parsed.py
PAPER_RAG_CONFIG=config/local.yaml .venv/bin/python scripts/validate_metadata_paths.py --strict
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PAPER_RAG_CONFIG=config/local.yaml \
  .venv/bin/python tests/eval/run_eval.py --file tests/eval/qa_set.real.jsonl --retrieval-only
```

This verifies that SQLite chunks, Qdrant payloads, and local metadata paths are aligned.
