# DeerFlow Integration Reference

Reference files and runbooks for wiring `paper_rag` into a DeerFlow
deployment. The runnable checkout under `integrations/deer-flow` is the source
of truth for the Gateway router, Harness tool adapter, and `paper-research`
subagent. This folder keeps only the reference snippets that are still tested
or useful for external ports; duplicated subagent code was removed to avoid
drift from the runnable Harness implementation.

| Folder | Purpose |
|---|---|
| `router/` | paper_rag HTTP endpoints + Prometheus `/metrics` router |
| `middleware/gateway/` | 8-layer gateway middleware (auth / observability / protection) |
| `middleware/langgraph/` | 4 langgraph middleware (token cost / latency / recursion guard / PII scrub) |
| Harness tools/subagent | Primary source lives in `integrations/deer-flow/backend/packages/harness/deerflow/community/paper_rag/` and `integrations/deer-flow/backend/packages/harness/deerflow/subagents/builtins/paper_research.py` |
| `frontend/` | Next.js workspace/paper-rag page |
| `observability/` | Prometheus + Grafana docker-compose override + alert rules |

See:

- `paper_rag/docs/adrs/0015-m8-service-deerflow-gateway.md`
- `paper_rag/docs/adrs/0020-gateway-middleware-and-observability.md`
- `paper_rag/docs/adrs/0021-langgraph-middleware-hardening.md`

for the design rationale behind each integration layer.
