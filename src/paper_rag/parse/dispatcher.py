"""Parse dispatcher: try MinerU, fall back to pymupdf when configured."""

from __future__ import annotations

import importlib
from pathlib import Path

from .. import config as cfg
from ..utils.logger import get_logger

log = get_logger("parse.dispatcher")


def parse_pdf(paper_id: str, pdf_path: str | Path) -> tuple[Path, str]:
    """Return (parsed_dir, parser_name) where parser_name in {'mineru','pymupdf'}."""
    c = cfg.load()
    if c.mineru.mode == "local":
        mineru_local = importlib.import_module("paper_rag.parse.mineru_local")

        try:
            return mineru_local.parse_pdf(paper_id, pdf_path), "mineru"
        except mineru_local.MineruError as e:
            log.warning(f"mineru failed: {e}")
            if not c.mineru.fallback_to_pymupdf:
                raise
            log.warning("falling back to pymupdf")
    fallback_pymupdf = importlib.import_module("paper_rag.parse.fallback_pymupdf")

    return fallback_pymupdf.parse_pdf(paper_id, pdf_path), "pymupdf"
