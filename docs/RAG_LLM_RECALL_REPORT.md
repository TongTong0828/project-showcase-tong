# LLM-Assisted Retrieval Recall Report

- Dataset: `tests/eval/qa_set.claims.jsonl`

| Strategy | Paper Recall | Chunk Recall | Gain | Harm Rate | Latency ms | Errors |
|---|---:|---:|---:|---:|---:|---:|
| `baseline_no_rewrite` | `0.983` | `0.717` | `0` | `0.0` | `246.075` | `0` |
| `local_rewrite_hyde` | `0.983` | `0.817` | `4` | `0.025` | `215.31` | `0` |
| `llm_rewrite_hyde` | `1.0` | `0.933` | `10` | `0.05` | `3467.582` | `0` |
