"""Prometheus-format metrics endpoint for paper_rag counters."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    """Render paper_rag metrics, or a fallback status gauge when unavailable."""
    try:
        from app.gateway.routers.paper_rag import _ensure_paper_rag_importable

        _ensure_paper_rag_importable()
        from paper_rag.observability.metrics import render

        body = render()
    except Exception as exc:
        logger.warning("paper_rag metrics unavailable: %s", exc)
        body = (
            "# HELP gateway_metrics_status indicates whether paper_rag metrics could be rendered\n"
            "# TYPE gateway_metrics_status gauge\n"
            "gateway_metrics_status 0\n"
        )

    return Response(content=body, media_type="text/plain; version=0.0.4")
