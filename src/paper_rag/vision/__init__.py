"""Vision-model enrichment for visual paper chunks."""

from .schema import (
    PROMPT_VERSION,
    STATUS_CACHED,
    STATUS_FAILED,
    STATUS_FALLBACK,
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_UNAVAILABLE,
    VisualSummaryRequest,
    VisualSummaryResult,
)

__all__ = [
    "PROMPT_VERSION",
    "STATUS_CACHED",
    "STATUS_FAILED",
    "STATUS_FALLBACK",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "STATUS_UNAVAILABLE",
    "VisualSummaryRequest",
    "VisualSummaryResult",
]
