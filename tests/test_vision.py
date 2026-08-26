"""Pure tests for visual-summary ingest enrichment."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_vision_config_defaults_exist():
    from paper_rag import config as cfg

    c = cfg.load()

    assert c.vision.provider == "openai_compatible"
    assert c.vision.max_images_per_paper >= 1
    assert c.vision.max_image_bytes > 0


def test_visual_summary_request_schema(tmp_path: Path):
    from paper_rag.vision.schema import VisualSummaryRequest

    image = tmp_path / "fig.png"
    image.write_bytes(b"fake")

    req = VisualSummaryRequest(
        paper_id="p1",
        chunk_id="c1",
        modality="figure",
        asset_path=image,
        caption="Pipeline",
        surrounding_context="The method has three stages.",
    )

    assert req.asset_path == image
    assert req.prompt_version == "v1"


def test_cache_round_trip(tmp_path: Path):
    from paper_rag.vision.cache import VisionSummaryCache
    from paper_rag.vision.schema import VisualSummaryRequest, VisualSummaryResult

    image = tmp_path / "fig.png"
    image.write_bytes(b"image")
    cache = VisionSummaryCache(tmp_path / "cache")
    req = VisualSummaryRequest(
        "p1",
        "c1",
        "figure",
        image,
        "caption",
        "context",
        model="vision-model",
    )

    key = cache.key_for(req)
    cache.write(
        key,
        VisualSummaryResult(
            status="ok",
            summary="A pipeline diagram.",
            provider="api",
            model="vision-model",
        ),
    )

    hit = cache.read(key)
    assert hit is not None
    assert hit.summary == "A pipeline diagram."
    assert hit.provider == "api"


def test_api_adapter_success(tmp_path: Path):
    from paper_rag.vision.api import OpenAIVisionSummarizer
    from paper_rag.vision.schema import VisualSummaryRequest

    image = tmp_path / "fig.png"
    image.write_bytes(b"image")
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            msg = SimpleNamespace(content='{"main_message":"A pipeline diagram"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    adapter = OpenAIVisionSummarizer(
        base_url="https://vision.example.test",
        api_key="test",
        model="vision-model",
        client_factory=lambda: fake_client,
    )

    out = adapter.summarize(VisualSummaryRequest("p1", "c1", "figure", image))

    assert out.status == "ok"
    assert out.provider == "api"
    assert out.model == "vision-model"
    assert "pipeline" in out.summary.lower()
    assert calls[0]["model"] == "vision-model"
    assert calls[0]["messages"][0]["content"][1]["type"] == "image_url"


def test_api_adapter_failure_returns_failed(tmp_path: Path):
    from paper_rag.vision.api import OpenAIVisionSummarizer
    from paper_rag.vision.schema import VisualSummaryRequest

    image = tmp_path / "fig.png"
    image.write_bytes(b"image")

    class FakeCompletions:
        def create(self, **kwargs):
            raise RuntimeError("provider down")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    adapter = OpenAIVisionSummarizer(
        base_url="https://vision.example.test",
        api_key="test",
        model="vision-model",
        client_factory=lambda: fake_client,
    )

    out = adapter.summarize(VisualSummaryRequest("p1", "c1", "figure", image))

    assert out.status == "failed"
    assert out.provider == "api"
    assert "provider down" in (out.error or "")


def test_enrich_chunks_appends_visual_summary(tmp_path: Path):
    from paper_rag.vision.enrich import enrich_chunks
    from paper_rag.vision.schema import VisualSummaryResult

    image = tmp_path / "fig.png"
    image.write_bytes(b"image")
    chunks = [
        {
            "chunk_id": "c1",
            "paper_id": "p1",
            "modality": "figure",
            "text": "Figure: pipeline\nContext: before after\nPath: figures/fig.png",
            "context_text": "Figure: pipeline",
            "asset_path": str(image),
            "metadata": {"element_type": "figure"},
        }
    ]

    out = enrich_chunks(
        "p1",
        chunks,
        summarizer=lambda req: VisualSummaryResult(
            status="ok",
            summary="Shows a three-stage pipeline.",
            provider="api",
            model="vision-model",
        ),
        cache_enabled=False,
    )

    assert "Visual summary: Shows a three-stage pipeline." in out[0]["text"]
    assert "Visual summary: Shows a three-stage pipeline." in out[0]["context_text"]
    assert out[0]["metadata"]["visual_summary"] == "Shows a three-stage pipeline."
    assert out[0]["metadata"]["visual_summary_status"] == "ok"
    assert out[0]["metadata"]["visual_summary_provider"] == "api"


def test_enrich_chunks_cache_hit_avoids_model_call(tmp_path: Path):
    from paper_rag.vision.cache import VisionSummaryCache
    from paper_rag.vision.enrich import enrich_chunks, request_from_chunk
    from paper_rag.vision.schema import VisualSummaryResult

    image = tmp_path / "fig.png"
    image.write_bytes(b"image")
    cache = VisionSummaryCache(tmp_path / "cache")
    chunk = {
        "chunk_id": "c1",
        "paper_id": "p1",
        "modality": "figure",
        "text": "Figure: cached\nContext: cache context\nPath: figures/fig.png",
        "context_text": "Figure: cached",
        "asset_path": str(image),
        "metadata": {},
    }
    req = request_from_chunk(chunk, model="vision-model")
    key = cache.key_for(req)
    cache.write(
        key,
        VisualSummaryResult(
            status="ok",
            summary="Cached summary.",
            provider="api",
            model="vision-model",
            cache_key=key,
        ),
    )
    calls = []

    out = enrich_chunks(
        "p1",
        [chunk],
        summarizer=lambda req: calls.append(req) or VisualSummaryResult(status="failed"),
        cache=cache,
        model="vision-model",
    )

    assert calls == []
    assert out[0]["metadata"]["visual_summary_status"] == "cached"
    assert out[0]["metadata"]["visual_summary"] == "Cached summary."


def test_enrich_chunks_fallback_success(tmp_path: Path):
    from paper_rag.vision.enrich import enrich_chunks
    from paper_rag.vision.schema import VisualSummaryResult

    image = tmp_path / "fig.png"
    image.write_bytes(b"image")
    chunk = {
        "chunk_id": "c1",
        "paper_id": "p1",
        "modality": "figure",
        "text": "original",
        "context_text": "original",
        "asset_path": str(image),
        "metadata": {},
    }

    out = enrich_chunks(
        "p1",
        [chunk],
        summarizer=lambda req: VisualSummaryResult(status="failed", error="api failed"),
        fallback_summarizer=lambda req: VisualSummaryResult(
            status="ok",
            summary="Local summary.",
            provider="local",
            model="qwen",
        ),
        cache_enabled=False,
    )

    assert out[0]["metadata"]["visual_summary_status"] == "fallback"
    assert out[0]["metadata"]["visual_summary_provider"] == "local"
    assert "Local summary." in out[0]["text"]


def test_enrich_chunks_all_failures_keep_ingest_text(tmp_path: Path):
    from paper_rag.vision.enrich import enrich_chunks
    from paper_rag.vision.schema import VisualSummaryResult

    image = tmp_path / "fig.png"
    image.write_bytes(b"image")
    chunk = {
        "chunk_id": "c1",
        "paper_id": "p1",
        "modality": "figure",
        "text": "original",
        "context_text": "original",
        "asset_path": str(image),
        "metadata": {},
    }

    out = enrich_chunks(
        "p1",
        [chunk],
        summarizer=lambda req: VisualSummaryResult(status="failed", error="boom"),
        fallback_summarizer=lambda req: VisualSummaryResult(status="unavailable", error="missing deps"),
        cache_enabled=False,
    )

    assert out[0]["text"] == "original"
    assert out[0]["context_text"] == "original"
    assert out[0]["metadata"]["visual_summary_status"] == "failed"
    assert "boom" in out[0]["metadata"]["visual_summary_error"]


def test_enrich_chunks_respects_per_paper_limit(tmp_path: Path):
    from paper_rag.vision.enrich import enrich_chunks
    from paper_rag.vision.schema import VisualSummaryResult

    chunks = []
    for i in range(2):
        image = tmp_path / f"fig-{i}.png"
        image.write_bytes(b"image")
        chunks.append(
            {
                "chunk_id": f"c{i}",
                "paper_id": "p1",
                "modality": "figure",
                "text": f"figure {i}",
                "context_text": f"figure {i}",
                "asset_path": str(image),
                "metadata": {},
            }
        )
    calls = []

    out = enrich_chunks(
        "p1",
        chunks,
        summarizer=lambda req: calls.append(req) or VisualSummaryResult(status="ok", summary="summary"),
        max_images_per_paper=1,
        cache_enabled=False,
    )

    assert len(calls) == 1
    assert out[0]["metadata"]["visual_summary_status"] == "ok"
    assert out[1]["metadata"]["visual_summary_status"] == "skipped"
    assert out[1]["metadata"]["visual_summary_error"] == "max_images_per_paper exceeded"
