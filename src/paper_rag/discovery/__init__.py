"""Paper discovery loop.

Discovery finds candidate papers for a research topic and records why each
candidate was selected or skipped. It does not provide answer evidence; QA must
still cite indexed paper chunks from the RAG pipeline.
"""

from __future__ import annotations

from .runner import ingest_candidate, run_discovery

__all__ = ["ingest_candidate", "run_discovery"]
