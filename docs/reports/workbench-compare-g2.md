# Workbench Compare G2 Report

## Status

Go.

## Implementation Summary

- Added an evidence-first Compare API and local persistence for compare runs
  and compare cells.
- Added a Chinese-first Compare route with dimension selection, project paper
  selection, a structured comparison matrix, explicit `No pinned evidence`
  states, and compare-to-DSH handoff preview.
- Added explicit selected-paper subset submission from the UI and backend
  membership checks so compare runs cannot include papers outside the project.
- Compare now can use saved QA citation mappings as partial evidence while
  still distinguishing them from pinned evidence and missing evidence states.
- Added saved compare run visibility on the Workspace page.
- Kept DSH optional and prompt-only; Compare does not read DSH private sessions
  and does not require DSH availability.

## Verification

- `.venv/bin/python -m pytest tests/test_workbench_workspace_store.py tests/test_workbench_api.py -q`: PASS, 30 tests.
- `pnpm --dir integrations/paper-rag-workbench test`: PASS, 53 tests.
- `pnpm --dir integrations/paper-rag-workbench build`: PASS.
- `VITE_WORKBENCH_FIXTURES=1 pnpm --dir integrations/paper-rag-workbench playwright`: PASS, 1 test.
- `.venv/bin/python scripts/secret_scan.py`: PASS, clean.
- `git status --short --branch`: clean at final audit.

## Degraded Modes

- LLM synthesis is intentionally treated as unavailable for Compare V1; the
  Workbench renders a deterministic evidence-only matrix instead of failing.
- Cells with pinned evidence expose supporting chunk ids and
  `evidence_backed` confidence.
- Cells without pinned evidence show `No pinned evidence` and `missing`
  confidence.
- Notes can be included as note ids for interpretation, but paper facts remain
  tied to chunk ids.
- Saved QA citations can contribute partial evidence only when their source
  chunk maps to the same project paper.

## Go/No-Go

Go for Gate 3 Scoped Notes Retrieval V1.

## Next Gate

Gate 3 should add Ask project context controls for pinned evidence, notes, and
project-paper restriction while keeping default global QA unchanged.
