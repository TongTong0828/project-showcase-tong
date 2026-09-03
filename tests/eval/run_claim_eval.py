"""Claim-level RAG eval runner.

This runner complements retrieval/citation eval:

- retrieval eval asks whether the system found the right paper/chunk
- citation eval asks whether cited chunks are valid and directly supportive
- claim eval asks whether the final answer covers expected semantic claims
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

from eval.claim_metrics import score_claims  # noqa: E402
from eval.loader import load_jsonl  # noqa: E402
from eval.metrics import must_not_contain_violations  # noqa: E402
from eval.run_eval import (  # noqa: E402
    _evaluate_gate,
    _looks_like_insufficient_evidence,
    _score_answer,
    _score_retrieval,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="Path to claim-level jsonl")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--out", default=None)
    p.add_argument("--gate", default=None)
    p.add_argument("--report-md", default=None)
    p.add_argument("--judge", action="store_true", help="Run optional LLM judge")
    return p.parse_args()


def run() -> int:
    from paper_rag import config as cfg
    from paper_rag.rag.qa_agentic import answer

    args = parse_args()
    cfg.load()
    items = load_jsonl(args.file)
    print(f"loaded {len(items)} items")

    rows: list[dict] = []
    t0 = time.time()
    for idx, item in enumerate(items, 1):
        row = {
            "qid": item.qid,
            "question": item.question,
            "intent": item.intent,
            "category": item.category or ("no_evidence" if not item.relevant_paper_ids else item.intent),
            "eval_tags": item.eval_tags,
            "expected_claim_count": len(item.expected_claims),
            "expected_relevant_paper_count": len(item.relevant_paper_ids),
        }
        try:
            rt0 = time.time()
            out = answer(item.question, paper_ids=None)
            row["latency_ms"] = round((time.time() - rt0) * 1000, 1)
            row["answer"] = out.get("answer", "")
            row["citations"] = out.get("citations", [])
            trace = out.get("trace", {}) or {}
            abstain = trace.get("abstain") or {}
            row["stopped_by"] = trace.get("stopped_by")
            row["abstain_decision"] = abstain.get("decision")
            row.update(_score_retrieval(out.get("chunks") or [], item, args.top_k))
            row.update(_score_answer(out, item, run_judge=args.judge))
            row.update(_score_claim_answer(out, item))
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        _print_claim_summary(idx, len(items), row)

    aggregate = _aggregate_claim_rows(rows)
    aggregate["elapsed_sec"] = round(time.time() - t0, 1)
    aggregate["n_items"] = len(items)

    gate_result = None
    if args.gate:
        gate_result = _evaluate_claim_gate(aggregate, Path(args.gate))
        aggregate["gate"] = gate_result

    print("\n=== CLAIM AGGREGATE ===")
    for key, value in aggregate.items():
        print(f"  {key:28s}  {value}")

    out_path = (
        Path(args.out)
        if args.out
        else Path(cfg.load().paths.index_dir) / "eval_runs" / f"claims_{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"aggregate": aggregate, "items": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {out_path}")

    if args.report_md:
        _write_claim_report(Path(args.report_md), dataset=args.file, aggregate=aggregate, rows=rows)
        print(f"wrote {args.report_md}")
    if gate_result and not gate_result["passed"]:
        return 2
    return 0


def _score_claim_answer(out: dict, item) -> dict:
    answer_text = out.get("answer", "")
    citations = out.get("citations") or []
    scored = score_claims(
        answer=answer_text,
        citation_ids=citations,
        expected_claims=getattr(item, "expected_claims", []),
    )
    scored["forbidden_claim_violations"] = must_not_contain_violations(
        answer_text,
        getattr(item, "must_not_contain", []),
    )
    if not getattr(item, "relevant_paper_ids", []):
        trace = out.get("trace", {}) or {}
        abstain = trace.get("abstain") or {}
        scored["no_answer_ok"] = float(
            trace.get("stopped_by") in {"no_evidence_abstain", "no_chunks"}
            or abstain.get("decision") in {"no_evidence", "no_chunks"}
            or (not citations and _looks_like_insufficient_evidence(answer_text))
        )
    return scored


def _aggregate_claim_rows(rows: list[dict]) -> dict:
    def avg(key: str) -> float | None:
        vals = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return round(mean(vals), 3) if vals else None

    claim_labeled = [row for row in rows if row.get("expected_claim_count", 0) > 0]
    no_answer = [
        row
        for row in rows
        if row.get("expected_relevant_paper_count") == 0
        or row.get("category") == "no_evidence"
    ]
    out = {
        "claim_recall": avg("claim_recall"),
        "grounded_claim_recall": avg("grounded_claim_recall"),
        "no_answer_success_rate": avg("no_answer_ok"),
        "forbidden_claim_violations": sum(
            int(row.get("forbidden_claim_violations", 0)) for row in rows
        ),
        "errors": sum(1 for row in rows if row.get("error")),
        "n_claim_labeled": len(claim_labeled),
        "n_no_answer": len(no_answer),
        "claim_label_coverage": round(len(claim_labeled) / len(rows), 3) if rows else None,
        "skipped_metrics": {
            "claim_recall": sum(1 for row in rows if not isinstance(row.get("claim_recall"), (int, float))),
            "grounded_claim_recall": sum(
                1 for row in rows if not isinstance(row.get("grounded_claim_recall"), (int, float))
            ),
            "no_answer_ok": sum(1 for row in rows if not isinstance(row.get("no_answer_ok"), (int, float))),
        },
    }
    decisions: dict[str, int] = {}
    for row in rows:
        decision = row.get("abstain_decision")
        if isinstance(decision, str) and decision:
            decisions[decision] = decisions.get(decision, 0) + 1
    if decisions:
        out["abstain_decisions"] = decisions
    return out


def _evaluate_claim_gate(aggregate: dict, gate_path: Path) -> dict:
    return _evaluate_gate(aggregate, gate_path, mode="claim_no_judge")


def _write_claim_report(path: Path, *, dataset: str, aggregate: dict, rows: list[dict]) -> None:
    lines = [
        "# RAG Claim Eval Report",
        "",
        f"- Dataset: `{dataset}`",
        f"- Items: `{aggregate.get('n_items', len(rows))}`",
        "",
        "## Aggregate",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in aggregate.items():
        if key in {"gate", "skipped_metrics", "abstain_decisions"}:
            continue
        lines.append(f"| `{key}` | `{value}` |")
    if aggregate.get("gate"):
        lines.extend(["", "## Gate", "", "| Metric | Value | Rule | Status |", "|---|---:|---|---|"])
        for check in aggregate["gate"]["checks"]:
            status = "PASS" if check["passed"] else f"FAIL {check['reason']}"
            lines.append(
                f"| `{check['metric']}` | `{check['value']}` | `{check['rule']}` | {status} |"
            )
    lines.extend(["", "## Low Claim Recall Items", ""])
    low_rows = [
        row for row in rows
        if isinstance(row.get("claim_recall"), (int, float)) and row.get("claim_recall", 1.0) < 1.0
    ]
    low_rows.sort(key=lambda row: (row.get("claim_recall", 1.0), row.get("qid", "")))
    for row in low_rows[:80]:
        lines.extend([
            f"### `{row.get('qid')}` {row.get('category') or ''}",
            "",
            f"- Question: {row.get('question')}",
            f"- claim_recall: `{row.get('claim_recall')}`",
            f"- grounded_claim_recall: `{row.get('grounded_claim_recall')}`",
            "",
            "| Missing Claim | Text |",
            "|---|---|",
        ])
        for claim in row.get("missing_claims") or []:
            lines.append(f"| `{claim.get('id')}` | {claim.get('text')} |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_claim_summary(idx: int, total: int, row: dict) -> None:
    if row.get("error"):
        print(f"[{idx}/{total}] {row['qid']} ERROR {row['error'][:120]}")
        return
    print(
        f"[{idx}/{total}] {row['qid']} | "
        f"claim={row.get('claim_recall')} | "
        f"grounded={row.get('grounded_claim_recall')} | "
        f"no_answer={row.get('no_answer_ok')}"
    )


if __name__ == "__main__":
    sys.exit(run())
