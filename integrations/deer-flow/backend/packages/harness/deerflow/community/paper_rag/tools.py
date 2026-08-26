"""LangChain tool wrappers around the standalone paper_rag package.

The DeerFlow Harness owns agent runtime concerns; the standalone paper_rag
package owns parsing, retrieval, QA, wiki, and citation behavior. This module is
only an adapter between those two layers.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg


def _ensure_paper_rag_importable() -> None:
    """Find paper_rag when it is checked out beside, above, or inside DeerFlow."""
    try:
        import paper_rag  # noqa: F401

        return
    except ImportError:
        pass

    candidates: list[Path] = []
    if home := os.environ.get("PAPER_RAG_HOME"):
        root = Path(home).expanduser().resolve()
        candidates.extend([root / "src", root])

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.extend([
            parent / "src",
            parent / "paper_rag" / "src",
            parent / "paper-rag-agent" / "src",
        ])

    for candidate in candidates:
        if (candidate / "paper_rag").is_dir():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _runtime_context_from_config(config: RunnableConfig | None = None) -> tuple[str | None, str]:
    thread_id = None
    if isinstance(config, dict):
        configurable = config.get("configurable") or {}
        thread_id = configurable.get("thread_id")
    try:
        from deerflow.runtime.user_context import get_effective_user_id

        user_id = get_effective_user_id()
    except Exception:
        user_id = "system"
    return (str(thread_id) if thread_id else None, str(user_id or "system"))


@tool("paper_ingest", parse_docstring=True)
def paper_ingest_tool(
    arxiv_id: str | None = None,
    pdf_url: str | None = None,
    pdf_path: str | None = None,
    title_hint: str = "",
) -> str:
    """Ingest one paper into the local paper_rag index.

    Use this when the user provides an arXiv id, a direct PDF URL, or a local
    PDF path and wants it available for later paper_qa or paper_compare calls.

    Args:
        arxiv_id: Optional arXiv id, for example 2310.11511.
        pdf_url: Optional direct PDF URL.
        pdf_path: Optional local PDF path visible to the runtime.
        title_hint: Optional title hint for URL or local PDF ingestion.
    """
    _ensure_paper_rag_importable()
    from paper_rag.tools.paper_index import ingest

    return _json_dumps(
        ingest(
            {
                "arxiv_id": arxiv_id,
                "pdf_url": pdf_url,
                "pdf_path": pdf_path,
                "title_hint": title_hint or None,
            }
        )
    )


@tool("paper_qa", parse_docstring=True)
def paper_qa_tool(
    question: str,
    paper_ids: str | None = None,
    resolved_question: str | None = None,
    config: Annotated[RunnableConfig | None, InjectedToolArg()] = None,
) -> str:
    """Answer a research question using the indexed paper corpus.

    Use this tool for paper, arXiv, DOI, academic literature, method,
    experiment, and citation questions. The tool runs its own Agentic RAG loop
    and returns an answer grounded in retrieved chunks.

    Args:
        question: Natural-language research question.
        paper_ids: Optional comma-separated paper ids to restrict retrieval.
        resolved_question: Optional caller-resolved self-contained question.
    """
    _ensure_paper_rag_importable()
    from paper_rag.tools._schema import PaperQAInput
    from paper_rag.tools.paper_qa import paper_qa

    conversation_id, user_id = _runtime_context_from_config(config)
    out = paper_qa(
        PaperQAInput(
            question=question,
            paper_ids=_split_csv(paper_ids),
            conversation_id=conversation_id,
            user_id=user_id,
            resolved_question=resolved_question or None,
        )
    )
    trace = out.get("trace") or {}
    query_resolution = out.get("query_resolution") or trace.get("query_resolution")
    chunks = [
        {key: chunk.get(key) for key in ("chunk_id", "paper_id", "section", "modality", "text")}
        for chunk in out.get("chunks", [])[:8]
    ]
    return _json_dumps({
        "answer": out.get("answer", ""),
        "citations": out.get("citations", []),
        "abstain": out.get("abstain") or trace.get("abstain"),
        "trace_id": out.get("trace_id") or trace.get("trace_id"),
        "query_resolution": query_resolution,
        "chunks": chunks,
    })


@tool("paper_search", parse_docstring=True)
def paper_search_tool(query: str, top_k: int = 8) -> str:
    """Find indexed papers relevant to a query.

    Use this as a lightweight discovery step before choosing a paper id for
    deeper QA or section reading.

    Args:
        query: Search query.
        top_k: Maximum number of papers to return.
    """
    _ensure_paper_rag_importable()
    from paper_rag.tools._schema import PaperSearchInput
    from paper_rag.tools.paper_search import paper_search

    return _json_dumps(paper_search(PaperSearchInput(query=query, top_k=top_k)))


@tool("paper_section", parse_docstring=True)
def paper_section_tool(paper_id: str, section_name: str) -> str:
    """Retrieve a named section from one indexed paper.

    Use this when the user asks for a specific paper section such as method,
    experiments, limitations, or conclusion.

    Args:
        paper_id: Paper id, for example arxiv:2310.11511.
        section_name: Case-insensitive section name or substring.
    """
    _ensure_paper_rag_importable()
    from paper_rag.tools._schema import PaperSectionInput
    from paper_rag.tools.paper_section import paper_section

    return _json_dumps(paper_section(PaperSectionInput(paper_id=paper_id, section_name=section_name)))


@tool("paper_compare", parse_docstring=True)
def paper_compare_tool(paper_ids: str, dimensions: str = "motivation,method,results,limitations") -> str:
    """Compare multiple indexed papers across selected dimensions.

    Keep this tool scoped: compare a small set of papers and a small number of
    dimensions so the agent does not create an expensive uncontrolled loop.

    Args:
        paper_ids: Comma-separated paper ids.
        dimensions: Comma-separated comparison dimensions.
    """
    _ensure_paper_rag_importable()
    from paper_rag.tools._schema import PaperCompareInput
    from paper_rag.tools.paper_compare import paper_compare

    parsed_ids = _split_csv(paper_ids) or []
    parsed_dimensions = _split_csv(dimensions) or []
    return _json_dumps(paper_compare(PaperCompareInput(paper_ids=parsed_ids, dimensions=parsed_dimensions)))


@tool("paper_discover", parse_docstring=True)
def paper_discover_tool(topic: str, max_candidates: int = 10, sources: str | None = None) -> str:
    """Discover candidate papers for a research topic.

    Use this before deep QA when the indexed library may not contain enough
    papers. This tool returns candidates, scores, and selection reasons only;
    candidates must be ingested before they can become final answer evidence.

    Args:
        topic: Research topic or literature-review query.
        max_candidates: Maximum number of selected candidates to return.
        sources: Optional comma-separated source list, e.g. arxiv,semantic_scholar.
    """
    _ensure_paper_rag_importable()
    from paper_rag.discovery import runner

    out = runner.run_discovery(
        topic,
        user_id="harness",
        source_names=_split_csv(sources),
        max_candidates=max_candidates,
    )
    candidates = [
        {
            key: candidate.get(key)
            for key in (
                "id",
                "title",
                "paper_id",
                "arxiv_id",
                "doi",
                "score",
                "selected",
                "rank_reason",
                "skip_reason",
                "ingest_status",
            )
        }
        for candidate in out.get("candidates", [])[:max_candidates]
    ]
    return _json_dumps(
        {
            "run": out.get("run", {}),
            "trace_id": (out.get("trace") or {}).get("trace_id"),
            "candidates": candidates,
            "evidence_role": "discovery_only_not_answer_evidence",
        }
    )


@tool("wiki_lookup", parse_docstring=True)
def wiki_lookup_tool(concept: str) -> str:
    """Look up a concept in the paper wiki.

    Use this for cached concept definitions, aliases, related papers, open
    problems, and review notes generated from the indexed corpus.

    Args:
        concept: Concept name to look up.
    """
    _ensure_paper_rag_importable()
    from paper_rag.tools._schema import WikiLookupInput
    from paper_rag.tools.wiki_lookup import wiki_lookup

    return _json_dumps(wiki_lookup(WikiLookupInput(concept=concept)))


@tool("export_bibtex", parse_docstring=True)
def export_bibtex_tool(paper_ids: str) -> str:
    """Export metadata for indexed papers as BibTeX.

    Use this after a research session to assemble references for a report,
    paper note, slide deck, or literature review.

    Args:
        paper_ids: Comma-separated paper ids.
    """
    _ensure_paper_rag_importable()
    from paper_rag.tools.bibtex_export import BibtexExportInput, export_bibtex

    return _json_dumps(export_bibtex(BibtexExportInput(paper_ids=_split_csv(paper_ids) or [])))


@tool("paper_deliver", parse_docstring=True)
def paper_deliver_tool(
    format: str,
    paper_ids: str,
    title: str = "",
    options_json: str = "{}",
) -> str:
    """Generate a ready-to-use deliverable from indexed papers.

    Supported formats include markdown_survey, pptx, docx, latex_bib, and pdf.
    The returned JSON includes a base64-encoded artifact payload.

    Args:
        format: Deliverable format, for example markdown_survey or pptx.
        paper_ids: Comma-separated paper ids.
        title: Optional human-readable title.
        options_json: Optional JSON object with format-specific options.
    """
    import base64

    _ensure_paper_rag_importable()
    from paper_rag import deliver

    try:
        options = json.loads(options_json) if options_json else {}
    except json.JSONDecodeError:
        options = {}

    result = deliver.dispatch(
        format,
        _split_csv(paper_ids) or [],
        title=title or None,
        options=options,
        user_id="harness",
    )
    return _json_dumps(
        {
            "format": result.format,
            "filename": result.filename,
            "content_base64": base64.b64encode(result.content_bytes).decode("ascii"),
            "content_type": result.content_type,
            "size_bytes": len(result.content_bytes),
            "metadata": result.metadata,
        }
    )


__all__ = [
    "paper_ingest_tool",
    "paper_qa_tool",
    "paper_search_tool",
    "paper_section_tool",
    "paper_compare_tool",
    "paper_discover_tool",
    "wiki_lookup_tool",
    "export_bibtex_tool",
    "paper_deliver_tool",
]
