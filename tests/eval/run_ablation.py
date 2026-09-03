"""Retrieval ablation runner for Paper RAG.

Compares several retrieval strategies on the same eval set:

- dense_only: vector search only
- sparse_only: FTS5/BM25 sparse search only
- hybrid_rrf: dense+sparse RRF without rerank
- hybrid_rerank_no_rewrite: hybrid + rerank, original query only
- hybrid_rerank_rewrite: production retrieve_round with query rewrite/HyDE

The output is a JSON artifact plus a compact terminal table. It intentionally
does not call the LLM, so it is safe for local iteration and course demos.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from eval.loader import load_jsonl  # noqa: E402
from eval.run_eval import _aggregate, _score_retrieval  # noqa: E402

StrategyFn = Callable[[str, int], list[dict]]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--out", default=None)
    return p.parse_args()


def _dense_only(query: str, top_k: int) -> list[dict]:
    from paper_rag.retrieve.dense import retrieve

    return retrieve(query, top_k=top_k)


def _sparse_only(query: str, top_k: int) -> list[dict]:
    from paper_rag.retrieve.hybrid import _sparse_search

    return _sparse_search(query, top_k=top_k, paper_ids=None)


def _hybrid_rrf(query: str, top_k: int) -> list[dict]:
    from paper_rag.retrieve.hybrid import hybrid_search

    return hybrid_search(query, top_k=top_k, paper_ids=None)[:top_k]


def _hybrid_rerank_no_rewrite(query: str, top_k: int) -> list[dict]:
    from paper_rag.retrieve.pipeline import retrieve_round_with_rewrite

    def no_rewrite(q: str) -> dict:
        return {"dense_queries": [q], "hyde": ""}

    chunks, _ = retrieve_round_with_rewrite(query, None, top_k, rewrite_fn=no_rewrite)
    return chunks


def _hybrid_rerank_rewrite(query: str, top_k: int) -> list[dict]:
    from paper_rag.retrieve.pipeline import retrieve_round

    return retrieve_round(query, None, top_k)


STRATEGIES: dict[str, StrategyFn] = {
    "dense_only": _dense_only,
    "sparse_only": _sparse_only,
    "hybrid_rrf": _hybrid_rrf,
    "hybrid_rerank_no_rewrite": _hybrid_rerank_no_rewrite,
    "hybrid_rerank_rewrite": _hybrid_rerank_rewrite,
}


def _summarize_strategy(rows: list[dict]) -> dict:
    aggregate = _aggregate(rows, include_categories=False)

    def avg(key: str) -> float | None:
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(mean(vals), 3) if vals else None

    return {
        "paper_recall@k": avg("paper_recall@k"),
        "paper_mrr": avg("paper_mrr"),
        "positive_paper_recall@k": aggregate.get("positive_paper_recall@k"),
        "positive_paper_mrr": aggregate.get("positive_paper_mrr"),
        "paper_precision@k": avg("paper_precision@k"),
        "paper_ndcg@k": avg("paper_ndcg@k"),
        "chunk_recall@k": avg("chunk_recall@k"),
        "chunk_mrr": avg("chunk_mrr"),
        "positive_chunk_recall@k": aggregate.get("positive_chunk_recall@k"),
        "positive_chunk_mrr": aggregate.get("positive_chunk_mrr"),
        "fpr@k": avg("fpr@k"),
        "latency_ms": avg("latency_ms"),
        "errors": sum(1 for r in rows if r.get("error")),
    }


def main() -> int:
    from paper_rag import config as cfg

    args = parse_args()
    cfg.load()
    items = load_jsonl(args.file)
    print(f"loaded {len(items)} items")

    result: dict[str, dict] = {}
    for name, fn in STRATEGIES.items():
        print(f"\n=== {name} ===")
        rows: list[dict] = []
        for item in items:
            row = {
                "qid": item.qid,
                "question": item.question,
                "intent": item.intent,
                "category": item.category or ("no_evidence" if not item.relevant_paper_ids else item.intent),
                "expected_relevant_paper_count": len(item.relevant_paper_ids),
                "expected_relevant_chunk_count": len(item.relevant_chunk_ids),
                "has_chunk_labels": bool(item.relevant_chunk_ids),
            }
            t0 = time.time()
            try:
                chunks = fn(item.question, args.top_k)
                row["latency_ms"] = round((time.time() - t0) * 1000, 1)
                row.update(_score_retrieval(chunks, item, args.top_k))
            except Exception as exc:
                row["latency_ms"] = round((time.time() - t0) * 1000, 1)
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
        summary = _summarize_strategy(rows)
        result[name] = {"summary": summary, "aggregate": _aggregate(rows), "items": rows}
        print(
            f"positive_paper_recall@k={summary['positive_paper_recall@k']} "
            f"positive_paper_mrr={summary['positive_paper_mrr']} "
            f"positive_chunk_recall@k={summary['positive_chunk_recall@k']} "
            f"latency_ms={summary['latency_ms']} errors={summary['errors']}"
        )

    out_path = Path(args.out) if args.out else Path(cfg.load().paths.index_dir) / "eval_runs" / "ablation_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
