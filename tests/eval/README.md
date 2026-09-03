# paper_rag 评测说明

这个目录是课程/面试级 RAG Eval Harness。它不是只跑一个 demo
question，而是把“检索是否找到证据、生成是否绑定证据、无证据是否拒答”
拆开评估。

## 评测集分层

- `qa_set.golden.jsonl`：60 条稳定回归集，45 条正例带 chunk-level 标注，15 条 no-evidence。用于 release gate、检索改动回归、课程演示。
- `qa_set.real.jsonl`：40 条 real/stress 集，覆盖更宽的问题形态、模糊问题和压力样本。用于发现问题，不直接作为唯一 hard gate。
- `qa_set.claims.jsonl`：40 条 claim-level 集，30 条正例带 90 个 expected claims，10 条 no-evidence。用于评估答案是否覆盖关键语义结论，以及 LLM rewrite/HyDE 是否真的提升召回。
- `qa_set.example.jsonl`：最小模板，适合新环境 smoke。

## 三档运行模式

| 模式 | 命令 | 评什么 | 是否需要 chat API |
|---|---|---|---|
| Retrieval-only | `make eval-golden` | paper/chunk recall、MRR、precision、nDCG、FPR、latency | 不需要 |
| QA no-judge | `make eval-golden-qa` | 上面 + citation existence/precision/recall、must-contain、no-answer | 需要，用于答案生成 |
| Citation audit | `make eval-citation-audit` | 逐条解释 citation 命中、错引论文、同论文错 chunk | 需要，用于答案生成 |
| Claim no-judge | `make eval-claims` | claim recall、grounded claim recall、missing claims、forbidden claim violations | 需要，用于答案生成 |
| LLM recall | `make eval-llm-recall` | baseline/local/LLM rewrite+HyDE 的 paper/chunk recall、gain、harm、latency | LLM rewrite 策略需要 |
| Judge | `python tests/eval/run_eval.py --file ...` | 上面 + faithful/complete/concise LLM judge | 需要，手动质量报告 |

`make eval-golden` 会设置 `PAPER_RAG_FORCE_LOCAL_REWRITE=1`，即使
`.env` 里配置了 DeepSeek/OpenAI，也不会调用 chat completion。它只比较
retrieval 输出的 paper/chunk id 和 golden label。

## 评测集 schema

每行一个 `EvalItem`（见 `schema.py`）：

```jsonc
{
  "qid": "q001",
  "question": "...",
  "category": "factual|method|evaluation|compare|ambiguous|no_evidence",
  "intent": "factual|reasoning|explore",
  "relevant_paper_ids": ["arxiv:..."],   // paper-level GT；no-evidence 时为空
  "relevant_chunk_ids": ["..."],          // retrieval GT；用于 chunk recall/MRR
  "citation_chunk_ids": ["..."],          // citation GT；为空时回退到 relevant_chunk_ids
  "irrelevant_paper_ids": ["arxiv:..."],  // 明确危险误召回；只统计 first evidence 之前的泄漏
  "must_contain": ["关键术语"],            // 答案必须出现的子串
  "must_not_contain": ["错误数字"],        // 答案不能出现的子串
  "expected_claims": [
    {
      "id": "cl001.1",
      "text": "答案应该覆盖的语义 claim",
      "accept_patterns": ["可接受表达", "re:regex pattern"],
      "supporting_chunk_ids": ["..."]       // grounded claim 的支撑证据
    }
  ],
  "eval_tags": ["query_mismatch", "compare"],
  "gold_answer": "...",                   // 给 LLM-judge 用，可选
  "notes": "..."
}
```

无 chunk label 时，`chunk_recall`、`cite_precision`、`cite_recall` 会显示
为 skipped/null，不再聚合成误导性的 `0.0`。没有任何 citation 时，
`cite_precision` 也会 skipped，漏引由 `cite_recall` 暴露。

无 `expected_claims` 时，claim 指标会 skipped/null。claim matching v1
使用人工 `accept_patterns`、大小写不敏感匹配、`re:` 正则和轻量 token
overlap fallback；它不是 LLM judge，所以能稳定进本地 gate。

## 指标定义

| 指标 | 含义 |
|---|---|
| `positive_paper_recall@k` | 正例里，目标论文是否出现在 top-k |
| `positive_paper_mrr` | 目标论文越靠前越好，第一名为 1.0 |
| `positive_chunk_recall@k` | 标注过的证据 chunk 是否进入 top-k |
| `paper/chunk_precision@k` | top-k 中有多少是标注相关 id |
| `paper/chunk_ndcg@k` | 相关结果排得越靠前越好 |
| `fpr@k` | 明确标注的危险误召回是否出现在第一个正确 evidence 之前 |
| `cite_existence` | 生成答案里的 citation id 是否都来自本轮 selected evidence chunks |
| `cite_precision` | citation 是否命中 `citation_chunk_ids` |
| `cite_paper_precision` | citation 是否至少来自相关论文，用于区分错论文和同论文错 chunk |
| `cite_recall` | 标注过的 citation chunks 有多少被答案引用 |
| `claim_recall` | 答案覆盖了多少 `expected_claims` |
| `grounded_claim_recall` | 答案覆盖 claim，且 citation 命中该 claim 的 `supporting_chunk_ids` |
| `missing_claims` | 未覆盖的 claim 列表，用于审计答案缺口 |
| `forbidden_claim_violations` | 命中 must-not-contain / forbidden claim 的次数 |
| `no_answer_success_rate` | no-evidence 问题是否拒答或明确证据不足 |
| `rewrite_gain_count` | rewrite/HyDE 策略相对 baseline 新增命中的样本数 |
| `rewrite_harm_rate` | rewrite/HyDE 策略相对 baseline 伤害召回的比例 |

## Strict gate

阈值在 `gates.strict.json`：

```text
positive_paper_recall@10 >= 0.95
positive_chunk_recall@10 >= 0.75
positive_paper_mrr       >= 0.85
fpr@10                   <= 0.05
errors                   == 0
```

最新本地 baseline：`positive_paper_recall@10=0.989`，
`positive_chunk_recall@10=0.811`，`positive_paper_mrr=0.989`，
`fpr@10=0.000`。

最新 QA no-judge baseline：`cite_existence=1.000`，
`cite_precision=0.867`，`cite_paper_precision=0.922`，
`must_contain=0.933`，`no_answer_success_rate=1.000`，
`no_answer_abstain_rate=0.933`。

最新 claim no-judge baseline：`claim_recall=0.811`，
`grounded_claim_recall=0.722`，`no_answer_success_rate=1.000`，
`forbidden_claim_violations=0`，`errors=0`。

最新 ablation：

| Strategy | Positive paper recall@10 | Positive paper MRR | Positive chunk recall@10 | Avg latency |
|---|---:|---:|---:|---:|
| dense_only | 0.922 | 0.974 | 0.767 | 198.22 ms |
| sparse_only | 0.956 | 0.782 | 0.567 | 2.19 ms |
| hybrid_rrf | 0.944 | 0.959 | 0.811 | 152.66 ms |
| hybrid_rerank_no_rewrite | 0.989 | 0.959 | 0.733 | 156.95 ms |
| hybrid_rerank_rewrite | 0.989 | 0.989 | 0.811 | 220.52 ms |

最新 LLM-assisted recall 对比：

| Strategy | Positive paper recall@10 | Positive chunk recall@10 | Rewrite gain | Harm rate | Avg latency |
|---|---:|---:|---:|---:|---:|
| baseline_no_rewrite | 0.983 | 0.717 | 0 | 0.000 | 246.08 ms |
| local_rewrite_hyde | 0.983 | 0.817 | 4 | 0.025 | 215.31 ms |
| llm_rewrite_hyde | 1.000 | 0.933 | 10 | 0.050 | 3467.58 ms |

## 标注流程建议（成本最低）

1. 选 5~10 篇你最熟悉的论文，先 ingest 入库。
2. 每篇出 5~8 个问题，覆盖 factual、method、evaluation、compare。
3. 先填 `relevant_paper_ids`，跑 retrieval-only 看 paper recall。
4. 对核心问题补 1~2 个 `relevant_chunk_ids`，再看 chunk recall。
5. 加 no-evidence、错误前提、时间敏感问题，验证拒答。
6. 对关键答案拆 2~4 个 `expected_claims`，并给每个 claim 标
   `supporting_chunk_ids`。
7. 最后再补 `gold_answer` 和 `must_contain`，跑 QA/no-judge、claim eval
   或 judge。

**先跑 retrieval-only，再跑 QA**。如果检索本身没找到证据，生成结果再漂亮也
只是幻觉风险。

```bash
make eval-golden
make eval-report
make eval-citation-audit
make eval-ablation
make eval-golden-qa
make eval-claims
make eval-claims-report
make eval-llm-recall
```

## 输出

- 每条一行简报（recall/mrr/cites/must_contain/cite_p）
- 末尾 aggregate 表
- 完整 JSON 落到 `data/index/eval_runs/<timestamp>.json`，方便 diff 历次实验
- `make eval-report` 额外生成 `docs/RAG_EVAL_REPORT.md`
- `make eval-citation-audit` 额外生成 `docs/RAG_CITATION_AUDIT.md`
- `make eval-ablation` 输出不同检索策略对比 JSON
- `make eval-claims-report` 额外生成 `docs/RAG_CLAIM_EVAL_REPORT.md`
- `make eval-llm-recall` 额外生成 `docs/RAG_LLM_RECALL_REPORT.md`

## 加大评测规模时

- 评测耗时 ≈ N × (检索时间 + LLM 时间 × 迭代轮数)
- LLM-judge 单题 ≈ 1 次额外调用
- 大批量先 `--retrieval-only`，之后再分段跑完整 RAG
