---
name: paper-research
description: Use this skill when the user asks about indexed academic papers, arXiv IDs, DOI references, literature reviews, paper comparison, paper sections, citations, BibTeX export, paper discovery, paper ingestion, or deliverables generated from a paper corpus.
allowed-tools:
  - paper_ingest
  - paper_qa
  - paper_search
  - paper_section
  - paper_compare
  - paper_discover
  - wiki_lookup
  - export_bibtex
  - paper_deliver
  - web_search
---

# Paper Research

Use `paper_qa` as the default path for questions about indexed papers. It performs query rewrite, hybrid retrieval, rerank, reflection, abstain checks, and citation validation internally.

Use `paper_ingest` when the user provides an arXiv ID, direct PDF URL, or local PDF path that is not already indexed. After ingestion, answer with `paper_qa`.

Use `paper_discover` to find candidate papers for a research topic. Discovery results are candidates only; ingest selected candidates before using them as final evidence.

Use `paper_search` only to find candidate paper IDs from the local corpus. Use `paper_section` for a specific section, `paper_compare` for structured multi-paper comparison, `wiki_lookup` for cached concept context, `export_bibtex` for references, and `paper_deliver` for Markdown, PowerPoint, Word, LaTeX/BibTeX, or PDF deliverables.

Every factual claim about paper content must be grounded in tool output. Prefer exact `[chunk:<id>]` citations returned by `paper_qa`; do not invent numeric citations or author-year citations.
