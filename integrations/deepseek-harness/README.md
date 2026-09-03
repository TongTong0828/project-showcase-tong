# Paper RAG DeepSeek Harness Integration

This directory owns the G0 DeepSeek Harness compatibility spike. It keeps DSH
package pins, profile patches, preset source, and deterministic scripts outside
the Python domain core.

Runtime state is repo-local and ignored:

- `data/runtime/deepseek-harness/versions/<dsh-version>/` is `DSH_HOME`.
- `data/runtime/deepseek-harness/credentials/.credentials.yaml` is the local
  credential provider path and is outside the versioned session root.
- `data/artifacts/` and `data/imports/` are reserved for later G2 artifact and
  import flows.

## Paper RAG Frontend

DSH Web is the Paper RAG frontend. The `Paper Research` preset exposes
broker-owned native tools for corpus status, discovery, ingestion, evidence QA,
comparison, sections, and artifact delivery. Tool results use portable cards:
structured MCP envelopes plus bounded Markdown fallback, with DSH generic result
cards when the host renders `presentResult`.

Write tools (`paper_ingest`, `discovery_candidate_ingest`, `paper_deliver`)
require one-shot approval and a direct user request boundary. Discovery
candidates are candidate-only metadata and must not be cited as answer evidence.

Useful commands:

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm dsh:dump-config
pnpm smoke
pnpm g0:compat --report ../../data/index/migration-gates/components/G0/dsh-g0-compat.json
node scripts/start.mjs
```
