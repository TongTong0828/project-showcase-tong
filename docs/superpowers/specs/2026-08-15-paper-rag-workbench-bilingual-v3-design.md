# Paper RAG Workbench Bilingual V3 Design

## Purpose

Make Paper RAG Workbench feel like the primary Chinese-first research cockpit
while preserving an English UI for debugging, sharing, and future contributors.
This release is a focused P0 product polish pass: bilingual interface,
language persistence, and full fixture-flow verification. It does not expand
scope into Compare, Notes, Collections, or Deliverables.

## Current Context

The Workbench is the main Paper RAG frontend at `http://127.0.0.1:3090`.
It currently exposes:

- Overview: corpus/model/credential status and DSH entry.
- Health: SQLite, Qdrant, LLM, retrieval fallback, and quality diagnostics.
- Library: indexed papers, section reader, paper detail, DSH handoff.
- Search: evidence retrieval, chunk inspection, DSH handoff.
- Ask: streaming QA, citations, chunk drilldown, agent timeline, DSH handoff.
- Discover: candidate discovery and approval-gated ingest.

The UI copy is English-first and spread across React pages/components. The
backend, Paper RAG kernel, DSH broker, credentials, and corpus data should not
change for this release.

## Goals

- Add a small local i18n layer with language values `zh` and `en`.
- Default the Workbench UI to Chinese.
- Add a visible `中 / EN` toggle in the Workbench shell.
- Persist the selected language in `localStorage` using key
  `paper-rag-workbench-language`.
- Translate navigation, page headings, helper text, form labels, buttons,
  status labels, empty states, modals, tables, timeline labels, and approval
  copy.
- Preserve dynamic research content exactly as returned by Paper RAG:
  paper titles, abstracts, chunk text, citations, model names, error payloads,
  IDs, generated answers, and evidence snippets are not machine-translated.
- Keep DSH as the separate chat/trace companion and Workbench as the main UI.
- Re-run the existing fixture flow in Chinese and verify English switching.

## Non-Goals

- Do not implement Compare, Collections, Notes, Literature Review, Annotated
  Bibliography, Related Work, Evidence Pack export, PDF export, or BibTeX export
  in this release.
- Do not change Paper RAG retrieval, QA, ingestion, parsing, Qdrant, SQLite, or
  DeepSeek model behavior.
- Do not change `deepseek-v4-flash`.
- Do not create or restore `integrations/deer-flow/`.
- Do not commit `.env`, API keys, `data/index`, runtime credentials, DSH
  sessions, real PDFs, generated `dist`, `node_modules`, or temporary smoke
  data.
- Do not run real-library write smoke tests unless the user explicitly approves
  that run.
- Do not translate user/model authored answer content. Only UI chrome and
  Workbench-owned status text are translated.

## Product Behavior

### Language Defaults

On first load, Workbench renders Chinese UI. If `localStorage` contains a valid
language value, the saved value wins. Invalid or missing values fall back to
Chinese.

### Toggle

The sidebar header contains a compact segmented toggle:

```text
中 | EN
```

The active language is visually selected and exposed with
`aria-pressed="true"`. Switching languages immediately updates visible UI copy
without reloading the page.

### Translation Scope

Chinese copy should be natural and product-facing, not literal debug text.
Recommended labels:

- Overview -> `概览`
- Health -> `健康检查`
- Library -> `论文库`
- Search -> `检索`
- Ask -> `问答`
- Discover -> `发现`
- DSH Chat -> `DSH 对话`
- Open DSH Chat -> `打开 DSH 对话`
- Agent Timeline -> `执行轨迹`
- Answer -> `回答`
- Citations -> `引用`
- Quality Issues -> `质量问题`
- Send to DSH -> `发送到 DSH`
- Approve candidate ingest -> `批准候选入库`
- Ingest selected -> `入库所选`

Keep technical names visible where they help debugging:

- `DSH`
- `Qdrant`
- `SQLite`
- `FTS`
- `deepseek-v4-flash`
- `chunk:<id>`
- `arxiv:<id>`

### Empty and Error States

Workbench-owned fallback text is translated, for example:

- `Loading overview...` -> `正在加载概览...`
- `Health unavailable` -> `健康检查不可用`
- `Search unavailable` -> `检索不可用`

Raw backend error details can remain as-is after the translated title because
they are diagnostic content.

### Testing Scope

The release is complete when:

- Unit tests prove default Chinese fallback, English switching, persistence, and
  interpolation.
- Component/page tests render through the i18n provider and assert Chinese UI
  labels for representative flows.
- Playwright fixture smoke starts in Chinese, completes Overview -> Health ->
  Library -> Search -> Ask -> Discover, and switches to English at least once.
- `pnpm --dir integrations/paper-rag-workbench test` passes.
- `pnpm --dir integrations/paper-rag-workbench build` passes.
- `VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright`
  passes.
- `.venv/bin/python scripts/secret_scan.py` reports clean.
- Git worktree is clean after commit.

## Recommended Approach

Implement a Workbench-local i18n module instead of adding a third-party
dependency. The current UI is small enough that a typed message dictionary is
simpler than introducing a full translation framework.

```text
App
  -> I18nProvider
     -> Shell with language toggle
     -> Pages and components call useI18n().t(...)
```

The dictionary should be flat and typed:

```ts
messages.zh["nav.overview"] === "概览"
messages.en["nav.overview"] === "Overview"
```

This keeps tests stable and makes missing keys a TypeScript error once the
English dictionary is used as the canonical key set.

## Future Specs

After this P0 ships, create separate specs for:

- `Paper Detail V4`: stronger section map, per-paper search, and evidence
  pinning.
- `Compare V1`: multi-paper method/contribution/limitation comparison.
- `Notes and Collections V1`: topic workspaces and chunk-level notes.
- `Deliverables V1`: literature review, annotated bibliography, related work,
  evidence pack, Markdown/PDF/BibTeX exports.
