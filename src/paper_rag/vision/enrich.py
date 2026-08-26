"""Enrich visual chunks with model-generated summaries."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import config as cfg
from ..utils.logger import get_logger
from .cache import VisionSummaryCache
from .schema import (
    STATUS_CACHED,
    STATUS_FAILED,
    STATUS_FALLBACK,
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_UNAVAILABLE,
    VisualSummaryRequest,
    VisualSummaryResult,
)

log = get_logger("vision.enrich")

SummarizerFn = Callable[[VisualSummaryRequest], VisualSummaryResult]
_VISUAL_MODALITIES = {"figure", "table"}


def request_from_chunk(chunk: dict, *, model: str | None = None) -> VisualSummaryRequest:
    metadata = chunk.get("metadata") or {}
    return VisualSummaryRequest(
        paper_id=str(chunk.get("paper_id") or ""),
        chunk_id=str(chunk.get("chunk_id") or ""),
        modality=str(chunk.get("modality") or ""),
        asset_path=Path(str(chunk.get("asset_path"))),
        caption=str(metadata.get("caption") or _caption_from_text(chunk.get("text") or "")),
        surrounding_context=str(
            metadata.get("surrounding_context")
            or _context_from_text(chunk.get("text") or "")
        ),
        model=model,
    )


def enrich_chunks(
    paper_id: str,
    chunks: list[dict],
    *,
    summarizer: SummarizerFn | None = None,
    fallback_summarizer: SummarizerFn | None = None,
    cache: VisionSummaryCache | None = None,
    cache_enabled: bool | None = None,
    model: str | None = None,
    max_images_per_paper: int | None = None,
    max_image_bytes: int | None = None,
) -> list[dict]:
    """Add visual summaries to figure/table chunks without failing ingest."""
    c = cfg.load().vision
    if not c.enabled and summarizer is None and fallback_summarizer is None:
        return chunks

    chosen_model = model or c.model
    max_images = max_images_per_paper if max_images_per_paper is not None else c.max_images_per_paper
    max_bytes = max_image_bytes if max_image_bytes is not None else c.max_image_bytes
    use_cache = c.cache if cache_enabled is None else cache_enabled
    summary_cache = cache
    if summary_cache is None and use_cache:
        summary_cache = VisionSummaryCache(_resolve_cache_dir(c.cache_dir))
    primary = summarizer or _default_api_summarizer()
    fallback = fallback_summarizer or _default_local_summarizer()

    processed = 0
    for chunk in chunks:
        if chunk.get("paper_id") != paper_id:
            continue
        if chunk.get("modality") not in _VISUAL_MODALITIES:
            continue
        metadata = chunk.setdefault("metadata", {})
        asset_path = chunk.get("asset_path")
        if not asset_path:
            _mark(metadata, STATUS_SKIPPED, error="missing asset_path")
            continue
        path = Path(str(asset_path))
        if not path.exists():
            _mark(metadata, STATUS_SKIPPED, error="asset_path does not exist")
            continue
        if path.stat().st_size > max_bytes:
            _mark(metadata, STATUS_SKIPPED, error="max_image_bytes exceeded")
            continue
        if processed >= max_images:
            _mark(metadata, STATUS_SKIPPED, error="max_images_per_paper exceeded")
            continue

        request = request_from_chunk(chunk, model=chosen_model)
        cache_key = None
        if use_cache and summary_cache is not None:
            cache_key = summary_cache.key_for(request)
            cached = summary_cache.read(cache_key)
            if cached and cached.summary:
                cached.status = STATUS_CACHED
                cached.cache_key = cache_key
                _apply_summary(chunk, cached)
                processed += 1
                continue

        result = primary(request)
        if result.status != STATUS_OK or not result.summary:
            fallback_result = fallback(request)
            if fallback_result.status == STATUS_OK and fallback_result.summary:
                fallback_result.status = STATUS_FALLBACK
                result = fallback_result

        if cache_key:
            result.cache_key = cache_key
        if result.status in {STATUS_OK, STATUS_FALLBACK} and result.summary:
            if use_cache and summary_cache is not None and cache_key:
                summary_cache.write(cache_key, result)
            _apply_summary(chunk, result)
        else:
            failed = result
            if result.status == STATUS_UNAVAILABLE:
                failed = VisualSummaryResult(
                    status=STATUS_FAILED,
                    provider=result.provider,
                    model=result.model,
                    error=result.error,
                    cache_key=cache_key,
                )
            _mark(
                metadata,
                failed.status if failed.status != STATUS_UNAVAILABLE else STATUS_FAILED,
                provider=failed.provider,
                model=failed.model,
                error=failed.error,
                cache_key=failed.cache_key,
            )
        processed += 1
    return chunks


def _default_api_summarizer() -> SummarizerFn:
    c = cfg.load().vision
    if not (c.base_url and c.api_key and c.model):
        return lambda req: VisualSummaryResult(
            status=STATUS_FAILED,
            provider="api",
            model=c.model,
            error="vision API config missing",
        )
    from .api import OpenAIVisionSummarizer

    return OpenAIVisionSummarizer(
        base_url=c.base_url,
        api_key=c.api_key,
        model=c.model,
        timeout_sec=c.timeout_sec,
    ).summarize


def _default_local_summarizer() -> SummarizerFn:
    c = cfg.load().vision
    if not c.fallback_local:
        return lambda req: VisualSummaryResult(
            status=STATUS_UNAVAILABLE,
            provider="local",
            model=c.local_model,
            error="local fallback disabled",
        )
    from .local import LocalVisionSummarizer

    return LocalVisionSummarizer(c.local_model).summarize


def _resolve_cache_dir(cache_dir: str) -> Path:
    path = Path(cache_dir)
    if path.is_absolute():
        return path
    if str(path).startswith("./"):
        return cfg.PROJECT_ROOT / str(path)[2:]
    return cfg.PROJECT_ROOT / path


def _apply_summary(chunk: dict, result: VisualSummaryResult) -> None:
    metadata = chunk.setdefault("metadata", {})
    _mark(
        metadata,
        result.status,
        summary=result.summary,
        provider=result.provider,
        model=result.model,
        error=result.error,
        raw=result.raw,
        cache_key=result.cache_key,
    )
    summary_line = f"Visual summary: {result.summary}"
    for key in ("text", "context_text"):
        text = str(chunk.get(key) or "")
        if summary_line not in text:
            chunk[key] = f"{text.rstrip()}\n{summary_line}".strip()


def _mark(
    metadata: dict,
    status: str,
    *,
    summary: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    error: str | None = None,
    raw: dict | None = None,
    cache_key: str | None = None,
) -> None:
    metadata["visual_summary_status"] = status
    if summary is not None:
        metadata["visual_summary"] = summary
    if provider is not None:
        metadata["visual_summary_provider"] = provider
    if model is not None:
        metadata["visual_summary_model"] = model
    if error is not None:
        metadata["visual_summary_error"] = error
    if raw is not None:
        metadata["visual_summary_raw"] = raw
    if cache_key is not None:
        metadata["visual_summary_cache_key"] = cache_key


def _caption_from_text(text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith(("figure:", "table:")):
            return line.split(":", 1)[1].strip()
    return ""


def _context_from_text(text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith("context:"):
            return line.split(":", 1)[1].strip()
    return text[:500]
