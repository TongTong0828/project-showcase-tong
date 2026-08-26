"""LLM-assisted retrieval recall runner.

Compares retrieval with no rewrite, local rewrite fallback, and the configured
LLM rewrite/HyDE path. This is a retrieval eval, not an LLM judge.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from eval.loader import load_jsonl  # noqa: E402
from eval.run_eval import _aggregate, _score_retrieval  # noqa: E402

RewriteFn = Callable[[str], dict]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--out", default=None)
    p.add_argument("--report-md", default=None)
    return p.parse_args()


def _no_rewrite(query: str) -> dict:
    return {
        "dense_queries": [query],
        "bm25_query": query,
        "raw": {"strategy": "baseline_no_rewrite"},
    }


def _local_rewrite(query: str) -> dict:
    from paper_rag.rag.query_rewrite import rewrite

    with _temporary_env("PAPER_RAG_FORCE_LOCAL_REWRITE", "1"):
        payload = rewrite(query)
    payload.setdefault("raw", {})
    payload["raw"]["strategy"] = "local_rewrite_hyde"
    return payload


def _llm_rewrite(query: str) -> dict:
    from paper_rag.rag.query_rewrite import rewrite

    with _temporary_env("PAPER_RAG_FORCE_LOCAL_REWRITE", None):
        payload = rewrite(query)
    payload.setdefault("raw", {})
    payload["raw"]["strategy"] = "llm_rewrite_hyde"
    return payload


STRATEGIES: dict[str, RewriteFn] = {
    "baseline_no_rewrite": _no_rewrite,
    "local_rewrite_hyde": _local_rewrite,
    "llm_rewrite_hyde": _llm_rewrite,
}


def run() -> int:
    from paper_rag import config as cfg
    from paper_rag.retrieve.pipeline import retrieve_round_with_rewrite

    args = parse_args()
    cfg.load()
    items = load_jsonl(args.file)
    print(f"loaded {len(items)} items")

    result: dict[str, dict] = {}
    baseline_rows: list[dict] | None = None
    for name, rewrite_fn in STRATEGIES.items():
        rows: list[dict] = []
        print(f"\n=== {name} ===")
        for item in items:
            row = {
                "qid": item.qid,
                "question": item.question,
                "intent": item.intent,
                "category": item.category or ("no_evidence" if not item.relevant_paper_ids else item.intent),
                "eval_tags": item.eval_tags,
                "expected_relevant_paper_count": len(item.relevant_paper_ids),
                "expected_relevant_chunk_count": len(item.relevant_chunk_ids),
                "has_chunk_labels": bool(item.relevant_chunk_ids),
            }
            t0 = time.time()
            try:
                chunks, rewrite_payload = retrieve_round_with_rewrite(
                    item.question,
                    None,
                    args.top_k,
                    rewrite_fn=rewrite_fn,
                )
                row["latency_ms"] = round((time.time() - t0) * 1000, 1)
                row["rewrite_query_count"] = len(rewrite_payload.get("dense_queries") or [])
                row["rewrite_raw"] = rewrite_payload.get("raw") or {}
                row.update(_score_retrieval(chunks, item, args.top_k))
            except Exception as exc:
                row["latency_ms"] = round((time.time() - t0) * 1000, 1)
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)

        if name == "baseline_no_rewrite":
            baseline_rows = rows
        summary = _summarize_with_baseline(rows, baseline_rows or rows)
        result[name] = {"summary": summary, "aggregate": _aggregate(rows), "items": rows}
        print(
            f"positive_paper_recall@k={summary['positive_paper_recall@k']} "
            f"positive_chunk_recall@k={summary['positive_chunk_recall@k']} "
            f"gain={summary['rewrite_gain_count']} "
            f"harm_rate={summary['rewrite_harm_rate']} "
            f"latency_ms={summary['latency_ms']} errors={summary['errors']}"
        )

    out_path = (
        Path(args.out)
        if args.out
        else Path(cfg.load().paths.index_dir) / "eval_runs" / "llm_recall_latest.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")

    if args.report_md:
        _write_llm_recall_report(Path(args.report_md), dataset=args.file, result=result)
        print(f"wrote {args.report_md}")
    return 0


def _summarize_with_baseline(rows: list[dict], baseline_rows: list[dict]) -> dict:
    aggregate = _aggregate(rows, include_categories=False)
    baseline_by_qid = {row.get("qid"): row for row in baseline_rows}
    gain = 0
    harm = 0
    comparable = 0
    for row in rows:
        base = baseline_by_qid.get(row.get("qid"))
        if not base:
            continue
        current_score = _recall_score(row)
        baseline_score = _recall_score(base)
        if current_score is None or baseline_score is None:
            continue
        comparable += 1
        if current_score > baseline_score:
            gain += 1
        elif current_score < baseline_score:
            harm += 1

    return {
        "positive_paper_recall@k": aggregate.get("positive_paper_recall@k"),
        "positive_paper_mrr": aggregate.get("positive_paper_mrr"),
        "positive_chunk_recall@k": aggregate.get("positive_chunk_recall@k"),
        "positive_chunk_mrr": aggregate.get("positive_chunk_mrr"),
        "rewrite_gain_count": gain,
        "rewrite_harm_count": harm,
        "rewrite_harm_rate": harm / comparable if comparable else None,
        "latency_ms": _avg(rows, "latency_ms"),
        "errors": sum(1 for row in rows if row.get("error")),
    }


def _recall_score(row: dict) -> float | None:
    if isinstance(row.get("chunk_recall@k"), (int, float)):
        return float(row["chunk_recall@k"])
    if isinstance(row.get("paper_recall@k"), (int, float)):
        return float(row["paper_recall@k"])
    return None


def _avg(rows: list[dict], key: str) -> float | None:
    vals = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    return round(mean(vals), 3) if vals else None


def _write_llm_recall_report(path: Path, *, dataset: str, result: dict[str, dict]) -> None:
    lines = [
        "# LLM-Assisted Retrieval Recall Report",
        "",
        f"- Dataset: `{dataset}`",
        "",
        "| Strategy | Paper Recall | Chunk Recall | Gain | Harm Rate | Latency ms | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, payload in result.items():
        summary = payload.get("summary") or {}
        lines.append(
            f"| `{name}` | `{summary.get('positive_paper_recall@k')}` | "
            f"`{summary.get('positive_chunk_recall@k')}` | "
            f"`{summary.get('rewrite_gain_count')}` | "
            f"`{summary.get('rewrite_harm_rate')}` | "
            f"`{summary.get('latency_ms')}` | `{summary.get('errors')}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@contextmanager
def _temporary_env(name: str, value: str | None):
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


if __name__ == "__main__":
    sys.exit(run())
