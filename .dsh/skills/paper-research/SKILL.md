# Paper Research

Use Paper RAG tools for claims about indexed papers. Chat history, web snippets,
wiki entries, discovery metadata, and memory can help plan or route, but they are
not final paper evidence.

## Read-Only Defaults

- For indexed-paper content questions, call `paper_qa` first.
- For requests to read a named section, call `paper_section`.
- For corpus inventory or health, call `paper_status` or `paper_list`.
- For concept background, call `wiki_lookup` and treat the result as metadata.
- For comparisons, call `paper_compare` only within 4 papers by 4 dimensions.

## Follow-Ups

Resolve follow-up questions into a self-contained `question` before calling a
tool. If you can resolve it explicitly, also pass `resolved_question`.

## Evidence

- Treat `paper_qa` abstain/no-evidence as authoritative.
- Do not answer a paper claim from memory, web, wiki, or discovery-only text.
- Show only citations returned by the tool, such as `[chunk:<id>]`.
- Do not invent numeric citations, author-year citations, or chunk ids.

## Errors

If a tool returns an error or no evidence, report that state plainly and suggest
a narrow next step such as search, section lookup, or discovery. Do not claim an
ingest, deliverable, or paper answer succeeded unless the tool result says so.
