# Workbench Scoped Notes G3 Report

## Status

Go.

## Implementation Summary

- Extended Workbench QA requests with optional `project_id` and explicit
  `context_policy` controls.
- Preserved default global QA behavior when no project context is enabled.
- Added scoped Ask controls for pinned evidence, notes, and project-paper
  restriction.
- Rendered paper citations and user note references separately in the answer
  panel.
- Saved scoped QA results with the context policy used for the answer and a
  citation-to-paper mapping for later project compare reuse.

## Verification

- `.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -q`: PASS, 30 tests.
- `pnpm --dir integrations/paper-rag-workbench test`: PASS, 53 tests.
- `pnpm --dir integrations/paper-rag-workbench build`: PASS.
- `VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright`: PASS, 1 test.
- `.venv/bin/python scripts/secret_scan.py`: PASS, clean.
- `git status --short --branch`: clean at final audit.

## Read-Only Live Smoke

- Ran a temporary scoped QA through the Workbench FastAPI app with a temporary
  workspace SQLite database.
- No ingest, reindex, rebuild, delete, or real corpus write operation was run.
- Result: PASS.
- Observed response: HTTP 200, `ok=true`, `tool=paper_qa`, one paper citation,
  ten chunks, scoped `note_refs`, and the requested `context_policy`.
- Degraded condition: Qdrant server was not reachable, so retrieval used the
  existing FTS5 fallback path.

## Degraded Modes

- Notes are passed and displayed as user-authored context, not as paper
  evidence.
- Paper facts still require paper chunk citations.
- If pinned evidence or notes are unavailable in a selected project, the API
  returns `project_context_warnings` while preserving the QA response shape.
- DSH remains optional; scoped Ask does not depend on DSH private session
  internals.

## Go/No-Go

Go for the full Workspace + Compare + Scoped Notes gated program.

## Deferred Work

- Deliverables V1: literature review, related work, annotated bibliography, and
  evidence pack export.
- DSH public prefill API integration if a stable supported route is exposed.
- Workspace import/export and project backup.
- Index rebuild and data-quality repair flows remain approval-gated future work.
