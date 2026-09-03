# RAG Eval Report

- Mode: `retrieval_only`
- Dataset: `tests/eval/qa_set.golden.jsonl`
- Items: `60`

## Aggregate

| Metric | Value |
|---|---:|
| `paper_recall@k` | `0.742` |
| `paper_mrr` | `0.742` |
| `paper_precision@k` | `0.4` |
| `paper_ndcg@k` | `0.972` |
| `positive_paper_recall@k` | `0.989` |
| `positive_paper_mrr` | `0.989` |
| `positive_paper_precision@k` | `0.4` |
| `positive_paper_ndcg@k` | `0.972` |
| `chunk_recall@k` | `0.811` |
| `chunk_mrr` | `0.869` |
| `chunk_precision@k` | `0.162` |
| `chunk_ndcg@k` | `0.751` |
| `positive_chunk_recall@k` | `0.811` |
| `positive_chunk_mrr` | `0.869` |
| `fpr@k` | `0.0` |
| `errors` | `0` |
| `n_positive` | `45` |
| `n_no_answer` | `15` |
| `n_chunk_labeled` | `45` |
| `chunk_label_coverage` | `1.0` |
| `cite_existence` | `None` |
| `cite_precision` | `None` |
| `cite_paper_precision` | `None` |
| `cite_recall` | `None` |
| `must_contain` | `None` |
| `no_answer_success_rate` | `None` |
| `violations` | `0` |
| `elapsed_sec` | `16.3` |
| `n_items` | `60` |

## Skipped Metrics

| Metric | Skipped Rows |
|---|---:|
| `paper_precision@k` | `15` |
| `paper_ndcg@k` | `15` |
| `chunk_recall@k` | `15` |
| `chunk_mrr` | `15` |
| `chunk_precision@k` | `15` |
| `chunk_ndcg@k` | `15` |
| `cite_precision` | `60` |
| `cite_paper_precision` | `60` |
| `cite_recall` | `60` |
| `fpr@k` | `26` |

## Gate

| Metric | Value | Rule | Status |
|---|---:|---|---|
| `positive_paper_recall@k` | `0.989` | `{'min': 0.95}` | PASS |
| `positive_chunk_recall@k` | `0.811` | `{'min': 0.75}` | PASS |
| `positive_paper_mrr` | `0.989` | `{'min': 0.85}` | PASS |
| `fpr@k` | `0.0` | `{'max': 0.05}` | PASS |
| `errors` | `0` | `{'max': 0}` | PASS |

## Items

| QID | Category | Recall | MRR | Citations |
|---|---|---:|---:|---:|
| `g001` | `factual` | `1.0` | `1.0` | `0` |
| `g002` | `method` | `1.0` | `1.0` | `0` |
| `g003` | `factual` | `1.0` | `1.0` | `0` |
| `g004` | `method` | `1.0` | `1.0` | `0` |
| `g005` | `method` | `1.0` | `1.0` | `0` |
| `g006` | `evaluation` | `1.0` | `1.0` | `0` |
| `g007` | `compare` | `1.0` | `1.0` | `0` |
| `g008` | `factual` | `1.0` | `1.0` | `0` |
| `g009` | `method` | `1.0` | `1.0` | `0` |
| `g010` | `compare` | `1.0` | `1.0` | `0` |
| `g011` | `evaluation` | `1.0` | `1.0` | `0` |
| `g012` | `method` | `1.0` | `0.5` | `0` |
| `g013` | `evaluation` | `1.0` | `1.0` | `0` |
| `g014` | `factual` | `1.0` | `1.0` | `0` |
| `g015` | `method` | `1.0` | `1.0` | `0` |
| `g016` | `method` | `1.0` | `1.0` | `0` |
| `g017` | `method` | `1.0` | `1.0` | `0` |
| `g018` | `method` | `1.0` | `1.0` | `0` |
| `g019` | `evaluation` | `1.0` | `1.0` | `0` |
| `g020` | `compare` | `1.0` | `1.0` | `0` |
| `g021` | `factual` | `1.0` | `1.0` | `0` |
| `g022` | `method` | `1.0` | `1.0` | `0` |
| `g023` | `compare` | `1.0` | `1.0` | `0` |
| `g024` | `method` | `1.0` | `1.0` | `0` |
| `g025` | `factual` | `1.0` | `1.0` | `0` |
| `g026` | `evaluation` | `1.0` | `1.0` | `0` |
| `g027` | `evaluation` | `1.0` | `1.0` | `0` |
| `g028` | `method` | `0.5` | `1.0` | `0` |
| `g029` | `factual` | `1.0` | `1.0` | `0` |
| `g030` | `method` | `1.0` | `1.0` | `0` |
| `g031` | `method` | `1.0` | `1.0` | `0` |
| `g032` | `evaluation` | `1.0` | `1.0` | `0` |
| `g033` | `compare` | `1.0` | `1.0` | `0` |
| `g034` | `compare` | `1.0` | `1.0` | `0` |
| `g035` | `evaluation` | `1.0` | `1.0` | `0` |
| `g036` | `method` | `1.0` | `1.0` | `0` |
| `g037` | `method` | `1.0` | `1.0` | `0` |
| `g038` | `method` | `1.0` | `1.0` | `0` |
| `g039` | `method` | `1.0` | `1.0` | `0` |
| `g040` | `compare` | `1.0` | `1.0` | `0` |
| `g041` | `method` | `1.0` | `1.0` | `0` |
| `g042` | `method` | `1.0` | `1.0` | `0` |
| `g043` | `evaluation` | `1.0` | `1.0` | `0` |
| `g044` | `evaluation` | `1.0` | `1.0` | `0` |
| `g045` | `compare` | `1.0` | `1.0` | `0` |
| `n001` | `no_evidence` | `0.0` | `0.0` | `0` |
| `n002` | `no_evidence` | `0.0` | `0.0` | `0` |
| `n003` | `no_evidence` | `0.0` | `0.0` | `0` |
| `n004` | `no_evidence` | `0.0` | `0.0` | `0` |
| `n005` | `no_evidence` | `0.0` | `0.0` | `0` |
