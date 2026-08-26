"""End-to-end RAG evaluation runner.

Usage:
    python tests/eval/run_eval.py --file tests/eval/qa_set.example.jsonl
    python tests/eval/run_eval.py --file my.jsonl --no-judge --top-k 8
    python tests/eval/run_eval.py --file my.jsonl --retrieval-only

Outputs:
    - per-item results -> stdout (one line summary)
    - aggregate report -> stdout (table)
    - full json dump   -> data/index/eval_runs/<ts>.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from eval.loader import load_jsonl  # noqa: E402
from eval.metrics import (  # noqa: E402
    citation_existence_rate,
    citation_paper_precision,
    citation_precision,
    citation_recall,
    false_positive_rate,
    mrr,
    must_contain_score,
    must_not_contain_violations,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="Path to qa_set jsonl")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--no-judge", action="store_true",
                   help="Skip LLM-judge even when gold_answer is provided")
    p.add_argument("--retrieval-only", action="store_true",
                   help="Only run retrieval (no LLM answering); recall metrics only")
    p.add_argument("--out", default=None, help="Override output JSON path")
    p.add_argument("--gate", default=None, help="JSON gate thresholds to enforce")
    p.add_argument("--report-md", default=None, help="Optional Markdown report path")
    p.add_argument("--citation-audit-md", default=None, help="Optional citation audit Markdown path")
    return p.parse_args()


def run() -> int:
    args = parse_args()
    from paper_rag import config as cfg

    cfg.load()
    items = load_jsonl(args.file)
    print(f"loaded {len(items)} items")

    per_item: list[dict] = []
    t0 = time.time()
    for i, it in enumerate(items, 1):
        rec = {
            "qid": it.qid,
            "question": it.question,
            "intent": it.intent,
            "category": it.category or ("no_evidence" if not it.relevant_paper_ids else it.intent),
            "expected_relevant_paper_count": len(it.relevant_paper_ids),
            "expected_relevant_chunk_count": len(it.relevant_chunk_ids),
            "expected_citation_chunk_count": len(_citation_label_ids(it)),
            "has_chunk_labels": bool(it.relevant_chunk_ids),
            "has_citation_labels": bool(_citation_label_ids(it)),
            "irrelevant_paper_ids": it.irrelevant_paper_ids,
            "relevant_chunk_ids": it.relevant_chunk_ids,
            "citation_chunk_ids": _citation_label_ids(it),
        }
        try:
            if args.retrieval_only:
                from paper_rag.retrieve.pipeline import retrieve_round

                rt0 = time.time()
                chunks = retrieve_round(it.question, None, args.top_k)
                rec["latency_ms"] = round((time.time() - rt0) * 1000, 1)
                rec.update(_score_retrieval(chunks, it, args.top_k))
            else:
                from paper_rag.rag.qa_agentic import answer

                rt0 = time.time()
                out = answer(it.question, paper_ids=None)
                rec["latency_ms"] = round((time.time() - rt0) * 1000, 1)
                rec["answer"] = out["answer"]
                rec["citations"] = out["citations"]
                trace = out.get("trace", {}) or {}
                rec["stopped_by"] = trace.get("stopped_by")
                abstain = trace.get("abstain") or {}
                rec["abstain_decision"] = abstain.get("decision")
                rec["abstain_evidence_score"] = abstain.get("evidence_score")
                rec["abstain_top_chunk_score"] = abstain.get("top_chunk_score")
                rec["abstain_score_field"] = abstain.get("score_field")
                rec.update(_score_retrieval(out["chunks"], it, args.top_k))
                rec.update(_score_answer(out, it, run_judge=not args.no_judge))
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"

        per_item.append(rec)
        _print_summary(i, len(items), rec)

    elapsed = time.time() - t0
    agg = _aggregate(per_item)
    agg["elapsed_sec"] = round(elapsed, 1)
    agg["n_items"] = len(items)

    gate_result = None
    mode = _eval_mode(args)
    if args.gate:
        gate_result = _evaluate_gate(agg, Path(args.gate), mode=mode)
        agg["gate"] = gate_result

    print("\n=== AGGREGATE ===")
    for k, v in agg.items():
        print(f"  {k:24s}  {v}")

    out_path = (
        Path(args.out)
        if args.out
        else Path(cfg.load().paths.index_dir) / "eval_runs" / f"{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"aggregate": agg, "items": per_item}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {out_path}")
    if args.report_md:
        _write_markdown_report(
            Path(args.report_md),
            mode=mode,
            dataset=args.file,
            aggregate=agg,
            items=per_item,
        )
        print(f"wrote {args.report_md}")
    if args.citation_audit_md:
        _write_citation_audit_report(
            Path(args.citation_audit_md),
            aggregate=agg,
            items=per_item,
        )
        print(f"wrote {args.citation_audit_md}")
    if gate_result and not gate_result["passed"]:
        return 2
    return 0


def _score_retrieval(chunks: list[dict], item, k: int) -> dict:
    pred_papers = [c.get("paper_id") for c in chunks if c.get("paper_id")]
    pred_chunks = [c.get("chunk_id") for c in chunks if c.get("chunk_id")]
    pred_papers_for_fpr = _papers_before_first_relevant(pred_papers, item.relevant_paper_ids)
    out = {
        "n_retrieved": len(chunks),
        "paper_recall@k": recall_at_k(pred_papers, item.relevant_paper_ids, k),
        "paper_mrr": mrr(pred_papers, item.relevant_paper_ids),
        "paper_precision@k": (
            precision_at_k(pred_papers, item.relevant_paper_ids, k)
            if item.relevant_paper_ids
            else None
        ),
        "paper_ndcg@k": ndcg_at_k(pred_papers, item.relevant_paper_ids, k),
        "chunk_recall@k": None,
        "chunk_mrr": None,
        "chunk_precision@k": None,
        "chunk_ndcg@k": None,
    }
    if item.relevant_chunk_ids:
        out["chunk_recall@k"] = recall_at_k(pred_chunks, item.relevant_chunk_ids, k)
        out["chunk_mrr"] = mrr(pred_chunks, item.relevant_chunk_ids)
        out["chunk_precision@k"] = precision_at_k(pred_chunks, item.relevant_chunk_ids, k)
        out["chunk_ndcg@k"] = ndcg_at_k(pred_chunks, item.relevant_chunk_ids, k)
    fpr = false_positive_rate(pred_papers_for_fpr, item.irrelevant_paper_ids, k)
    out["fpr@k"] = fpr
    return out


def _papers_before_first_relevant(
    predicted: list[str],
    relevant: list[str],
) -> list[str]:
    if not relevant:
        return predicted
    rel = set(relevant)
    before: list[str] = []
    seen: set[str] = set()
    for paper_id in predicted:
        if paper_id in rel:
            break
        if paper_id not in seen:
            before.append(paper_id)
            seen.add(paper_id)
    return before


def _score_answer(out: dict, item, *, run_judge: bool) -> dict:
    answer_text = out.get("answer", "")
    cites = out.get("citations", [])
    allowed_chunks = out.get("evidence_chunks") or out.get("chunks", [])
    retrieved_ids = [c.get("chunk_id") for c in allowed_chunks if c.get("chunk_id")]
    all_chunks = _dedupe_chunks((out.get("chunks") or []) + (out.get("evidence_chunks") or []))
    chunk_meta = {
        c.get("chunk_id"): (i, c)
        for i, c in enumerate(all_chunks, 1)
        if c.get("chunk_id")
    }
    citation_labels = _citation_label_ids(item)
    citation_papers = [
        (chunk_meta.get(cid) or (None, {}))[1].get("paper_id")
        for cid in cites
    ]
    res = {
        "n_citations": len(cites),
        "cite_existence": citation_existence_rate(cites, retrieved_ids),
        "cite_precision": None,
        "cite_paper_precision": citation_paper_precision(citation_papers, item.relevant_paper_ids),
        "cite_recall": None,
        "must_contain": must_contain_score(answer_text, item.must_contain),
        "violations": must_not_contain_violations(answer_text, item.must_not_contain),
        "citation_details": _citation_details(cites, chunk_meta, citation_labels, item.relevant_paper_ids),
    }
    if not item.relevant_paper_ids:
        trace = out.get("trace", {}) or {}
        abstain_decision = (trace.get("abstain") or {}).get("decision")
        stopped_by = trace.get("stopped_by")
        res["no_answer_ok"] = float(
            stopped_by in {"no_evidence_abstain", "no_chunks"}
            or abstain_decision in {"no_evidence", "no_chunks"}
            or (not cites and _looks_like_insufficient_evidence(answer_text))
        )
    cp = citation_precision(cites, citation_labels)
    if cp is not None:
        res["cite_precision"] = cp
    cr = citation_recall(cites, citation_labels)
    if cr is not None:
        res["cite_recall"] = cr

    if run_judge and item.gold_answer:
        from eval.judge import judge

        res["judge"] = judge(item.question, item.gold_answer, out.get("answer", ""))
    return res


def _citation_label_ids(item) -> list[str]:
    labels = getattr(item, "citation_chunk_ids", None) or []
    return list(labels or getattr(item, "relevant_chunk_ids", []) or [])


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for chunk in chunks:
        cid = chunk.get("chunk_id")
        if cid and cid in seen:
            continue
        if cid:
            seen.add(cid)
        out.append(chunk)
    return out


def _citation_details(
    citations: list[str],
    chunk_meta: dict,
    citation_labels: list[str],
    relevant_paper_ids: list[str],
) -> list[dict]:
    citation_label_set = set(citation_labels)
    relevant_paper_set = set(relevant_paper_ids)
    details = []
    for cid in citations:
        rank, chunk = chunk_meta.get(cid, (None, {}))
        paper_id = chunk.get("paper_id")
        matches_label = cid in citation_label_set
        matches_paper = paper_id in relevant_paper_set
        if matches_label:
            diagnosis = "direct_support"
        elif matches_paper:
            diagnosis = "right_paper_wrong_chunk"
        else:
            diagnosis = "wrong_paper_or_unknown_chunk"
        details.append({
            "chunk_id": cid,
            "paper_id": paper_id,
            "title": chunk.get("title"),
            "section": chunk.get("section"),
            "rank": rank,
            "matches_citation_label": matches_label,
            "matches_relevant_paper": matches_paper,
            "diagnosis": diagnosis,
        })
    return details


def _print_summary(idx: int, total: int, rec: dict) -> None:
    if "error" in rec:
        print(f"[{idx}/{total}] {rec['qid']} ERROR {rec['error'][:120]}")
        return
    bits = [f"recall@k={rec.get('paper_recall@k', 0):.2f}",
            f"mrr={rec.get('paper_mrr', 0):.2f}",
            f"cites={rec.get('n_citations', 0)}",
            f"must={rec.get('must_contain', 1):.2f}"]
    if isinstance(rec.get("cite_precision"), (int, float)):
        bits.append(f"cite_p={rec['cite_precision']:.2f}")
    print(f"[{idx}/{total}] {rec['qid']} | " + " | ".join(bits))


def _aggregate(per_item: list[dict], *, include_categories: bool = True) -> dict:
    def _avg(key: str) -> float:
        vals = [r[key] for r in per_item if isinstance(r.get(key), (int, float))]
        return round(mean(vals), 3) if vals else None

    def _avg_in(rows: list[dict], key: str) -> float:
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(mean(vals), 3) if vals else None

    positives = [r for r in per_item if r.get("paper_recall@k") is not None and _has_relevant_paper(r)]
    no_answer = [r for r in per_item if r.get("paper_recall@k") is not None and not _has_relevant_paper(r)]
    chunk_labeled = [r for r in positives if r.get("has_chunk_labels")]

    answer_rows = [r for r in per_item if "answer" in r]

    out = {
        "paper_recall@k": _avg("paper_recall@k"),
        "paper_mrr": _avg("paper_mrr"),
        "paper_precision@k": _avg("paper_precision@k"),
        "paper_ndcg@k": _avg("paper_ndcg@k"),
        "positive_paper_recall@k": _avg_in(positives, "paper_recall@k"),
        "positive_paper_mrr": _avg_in(positives, "paper_mrr"),
        "positive_paper_precision@k": _avg_in(positives, "paper_precision@k"),
        "positive_paper_ndcg@k": _avg_in(positives, "paper_ndcg@k"),
        "chunk_recall@k": _avg("chunk_recall@k"),
        "chunk_mrr": _avg("chunk_mrr"),
        "chunk_precision@k": _avg("chunk_precision@k"),
        "chunk_ndcg@k": _avg("chunk_ndcg@k"),
        "positive_chunk_recall@k": _avg_in(chunk_labeled, "chunk_recall@k"),
        "positive_chunk_mrr": _avg_in(chunk_labeled, "chunk_mrr"),
        "fpr@k": _avg("fpr@k"),
        "errors": sum(1 for r in per_item if r.get("error")),
        "n_positive": len(positives),
        "n_no_answer": len(no_answer),
        "n_chunk_labeled": len(chunk_labeled),
        "chunk_label_coverage": round(len(chunk_labeled) / len(positives), 3) if positives else None,
        "cite_existence": _avg("cite_existence"),
        "cite_precision": _avg("cite_precision"),
        "cite_paper_precision": _avg("cite_paper_precision"),
        "cite_recall": _avg("cite_recall"),
        "must_contain": _avg("must_contain"),
        "no_answer_success_rate": _avg("no_answer_ok"),
    }
    if answer_rows:
        out.update(
            {
                "violations": sum(int(r.get("violations", 0)) for r in per_item),
            }
        )
    else:
        out["violations"] = 0
    if no_answer and any(r.get("stopped_by") or r.get("abstain_decision") for r in no_answer):
        abstained = [
            r
            for r in no_answer
            if r.get("stopped_by") in {"no_evidence_abstain", "no_chunks"}
            or r.get("abstain_decision") in {"no_evidence", "no_chunks"}
        ]
        out["no_answer_abstain_rate"] = round(len(abstained) / len(no_answer), 3)
    decisions: dict[str, int] = {}
    for r in per_item:
        decision = r.get("abstain_decision")
        if isinstance(decision, str) and decision:
            decisions[decision] = decisions.get(decision, 0) + 1
    if decisions:
        out["abstain_decisions"] = decisions
    judge_keys = ("faithful", "complete", "concise")
    judges = [r.get("judge") for r in per_item if isinstance(r.get("judge"), dict) and "faithful" in r["judge"]]
    if judges:
        for k in judge_keys:
            out[f"judge_{k}"] = round(mean(j[k] for j in judges), 2)
    out["skipped_metrics"] = _skipped_metrics(per_item)
    if include_categories:
        by_category: dict[str, dict] = {}
        categories = sorted({str(r.get("category") or r.get("intent") or "uncategorized") for r in per_item})
        for category in categories:
            rows = [r for r in per_item if (r.get("category") or r.get("intent") or "uncategorized") == category]
            by_category[category] = _aggregate(rows, include_categories=False)
        out["by_category"] = by_category
    return out


def _skipped_metrics(per_item: list[dict]) -> dict[str, int]:
    keys = (
        "paper_precision@k",
        "paper_ndcg@k",
        "chunk_recall@k",
        "chunk_mrr",
        "chunk_precision@k",
        "chunk_ndcg@k",
        "cite_precision",
        "cite_paper_precision",
        "cite_recall",
        "fpr@k",
    )
    return {
        key: sum(1 for r in per_item if not isinstance(r.get(key), (int, float)))
        for key in keys
    }


def _eval_mode(args: argparse.Namespace) -> str:
    if args.retrieval_only:
        return "retrieval_only"
    if args.no_judge:
        return "qa_no_judge"
    return "judge"


def _evaluate_gate(aggregate: dict, gate_path: Path, *, mode: str) -> dict:
    data = json.loads(gate_path.read_text(encoding="utf-8"))
    thresholds = data.get(mode) or data.get("metrics") or data
    checks = []
    for metric, rule in thresholds.items():
        value = aggregate.get(metric)
        passed = isinstance(value, (int, float))
        reason = ""
        if not passed:
            reason = "missing_or_skipped"
        else:
            if "min" in rule and value < rule["min"]:
                passed = False
                reason = f"{value} < {rule['min']}"
            if "max" in rule and value > rule["max"]:
                passed = False
                reason = f"{value} > {rule['max']}"
            if "eq" in rule and value != rule["eq"]:
                passed = False
                reason = f"{value} != {rule['eq']}"
        checks.append({
            "metric": metric,
            "value": value,
            "rule": rule,
            "passed": passed,
            "reason": reason,
        })
    return {"mode": mode, "passed": all(c["passed"] for c in checks), "checks": checks}


def _write_markdown_report(
    path: Path,
    *,
    mode: str,
    dataset: str,
    aggregate: dict,
    items: list[dict],
) -> None:
    lines = [
        "# RAG Eval Report",
        "",
        f"- Mode: `{mode}`",
        f"- Dataset: `{dataset}`",
        f"- Items: `{aggregate.get('n_items', len(items))}`",
        "",
        "## Aggregate",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in aggregate.items():
        if key in {"by_category", "gate", "skipped_metrics", "abstain_decisions"}:
            continue
        lines.append(f"| `{key}` | `{value}` |")
    if aggregate.get("skipped_metrics"):
        lines.extend(["", "## Skipped Metrics", "", "| Metric | Skipped Rows |", "|---|---:|"])
        for key, value in aggregate["skipped_metrics"].items():
            lines.append(f"| `{key}` | `{value}` |")
    if aggregate.get("gate"):
        lines.extend(["", "## Gate", "", "| Metric | Value | Rule | Status |", "|---|---:|---|---|"])
        for check in aggregate["gate"]["checks"]:
            status = "PASS" if check["passed"] else f"FAIL {check['reason']}"
            lines.append(
                f"| `{check['metric']}` | `{check['value']}` | "
                f"`{check['rule']}` | {status} |"
            )
    lines.extend(["", "## Items", "", "| QID | Category | Recall | MRR | Citations |", "|---|---|---:|---:|---:|"])
    for row in items[:50]:
        lines.append(
            f"| `{row.get('qid')}` | `{row.get('category')}` | "
            f"`{row.get('paper_recall@k')}` | `{row.get('paper_mrr')}` | "
            f"`{row.get('n_citations', 0)}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_citation_audit_report(path: Path, *, aggregate: dict, items: list[dict]) -> None:
    rows = [
        row for row in items
        if isinstance(row.get("cite_precision"), (int, float))
        and row.get("cite_precision", 1.0) < 0.75
    ]
    rows.sort(key=lambda r: (r.get("cite_precision", 1.0), r.get("qid", "")))
    lines = [
        "# RAG Citation Audit",
        "",
        f"- Aggregate cite_precision: `{aggregate.get('cite_precision')}`",
        f"- Aggregate cite_paper_precision: `{aggregate.get('cite_paper_precision')}`",
        f"- Low precision rows: `{len(rows)}`",
        "",
        "## Low Precision Items",
        "",
    ]
    for row in rows[:80]:
        lines.extend([
            f"### `{row.get('qid')}` {row.get('category') or ''}",
            "",
            f"- Question: {row.get('question')}",
            f"- cite_precision: `{row.get('cite_precision')}`",
            f"- cite_paper_precision: `{row.get('cite_paper_precision')}`",
            f"- retrieval labels: `{row.get('relevant_chunk_ids', [])}`",
            f"- citation labels: `{row.get('citation_chunk_ids', [])}`",
            "",
            "| Citation | Paper | Section | Rank | Match | Diagnosis |",
            "|---|---|---|---:|---|---|",
        ])
        for detail in row.get("citation_details") or []:
            match = "yes" if detail.get("matches_citation_label") else "no"
            lines.append(
                f"| `{detail.get('chunk_id')}` | `{detail.get('paper_id')}` | "
                f"`{detail.get('section')}` | `{detail.get('rank')}` | "
                f"{match} | `{_detail_diagnosis(detail)}` |"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _detail_diagnosis(detail: dict) -> str:
    if detail.get("diagnosis"):
        return str(detail["diagnosis"])
    if detail.get("matches_citation_label"):
        return "direct_support"
    if detail.get("matches_relevant_paper"):
        return "right_paper_wrong_chunk"
    return "wrong_paper_or_unknown_chunk"


def _has_relevant_paper(rec: dict) -> bool:
    return bool(rec.get("expected_relevant_paper_count", 0))


def _looks_like_insufficient_evidence(answer: str) -> bool:
    low = (answer or "").lower()
    hints = (
        "does not contain",
        "does not mention",
        "not contain",
        "not provided",
        "cannot answer",
        "can't answer",
        "insufficient evidence",
        "evidence is insufficient",
        "未在",
        "没有",
        "无法回答",
    )
    return any(hint in low for hint in hints)


if __name__ == "__main__":
    sys.exit(run())
