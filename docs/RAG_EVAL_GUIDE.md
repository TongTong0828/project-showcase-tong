# RAG Eval Guide

这份文档说明 Paper RAG Agent 的全部本地评测集、评测命令、指标口径和报告位置。它的目标是让学生和面试官能看懂：系统到底测了什么、为什么有些命令不需要 API key、如何判断一次 RAG 优化是否真的有效。

## 评测集

| 文件 | 规模 | 用途 | 是否进默认 gate |
|---|---:|---|---|
| `tests/eval/qa_set.example.jsonl` | 少量样例 | 新环境 smoke、学习 JSONL schema | 否 |
| `tests/eval/qa_set.golden.jsonl` | 60 条 | 稳定回归集；45 条正例带 chunk-level 标注，15 条 no-evidence | 是 |
| `tests/eval/qa_set.real.jsonl` | 40 条 | real/stress 探索集；用于发现失败模式和补 hard cases | 否 |
| `tests/eval/qa_set.claims.jsonl` | 40 条 | claim-level 集；30 条正例带 90 个 expected claims，10 条 no-evidence | 是 |

核心原则：`memory`、`wiki`、`discovery` 都不能作为最终答案证据。最终 QA 评测只认本轮 indexed chunks、selected evidence 和 citation。

## 三层评测

1. Retrieval recall：评检索有没有找到正确 paper/chunk。它像搜索引擎离线评测，不调用 chat API。
2. Citation precision：评答案引用是否来自真实 selected evidence，以及是否命中能直接支撑答案的 citation chunks。
3. Claim recall：评答案是否覆盖关键语义 claims；`grounded_claim_recall` 还要求这些 claim 的 citation 命中 supporting chunks。

LLM judge 只做手动质量报告，不进入默认快速门禁。默认 gate 用确定性 ID、pattern 和 citation 规则，方便本地复现。

## 命令速查

| 命令 | 评什么 | 需要 API key | 主要输出 |
|---|---|---|---|
| `make verify-p0` | lint、聚焦测试、import smoke、secret scan、retrieval golden gate | retrieval 部分不需要 | 终端 gate 结果 |
| `make eval-golden` | `qa_set.golden.jsonl` retrieval-only | 不需要 chat API | `data/index/eval_runs/<timestamp>.json` |
| `make eval-golden-qa` | golden QA no-judge：citation、must-contain、no-answer | 需要 | `data/index/eval_runs/<timestamp>.json` |
| `make eval-report` | golden retrieval Markdown 报告 | 不需要 chat API | `docs/RAG_EVAL_REPORT.md` |
| `make eval-citation-audit` | golden QA citation 审计 | 需要 | `docs/RAG_CITATION_AUDIT.md` |
| `make eval-ablation` | dense/sparse/hybrid/rerank/rewrite 对比 | 不需要 chat API | `data/index/eval_runs/ablation_latest.json` |
| `make eval-claims` | claim-level QA no-judge gate | 需要 | `data/index/eval_runs/claims_<timestamp>.json` |
| `make eval-claims-report` | claim-level Markdown 报告 | 需要 | `docs/RAG_CLAIM_EVAL_REPORT.md` |
| `make eval-llm-recall` | baseline/local/LLM rewrite+HyDE 召回对比 | LLM rewrite 策略需要 | `docs/RAG_LLM_RECALL_REPORT.md` |
| `make eval-claims-judge` | 可选 claim eval + LLM judge | 需要 | 手动质量报告 |

推荐顺序：

```bash
make verify-p0
make eval-golden-qa
make eval-claims
make eval-llm-recall
make eval-claims-report
```

如果只改检索策略，先跑：

```bash
make eval-golden
make eval-ablation
make eval-llm-recall
```

如果只改 prompt、evidence selection、citation validation 或 abstain，跑：

```bash
make eval-golden-qa
make eval-citation-audit
make eval-claims
```

## 最新本地基线

Retrieval golden gate：

| Metric | Value |
|---|---:|
| `positive_paper_recall@10` | 0.989 |
| `positive_chunk_recall@10` | 0.811 |
| `positive_paper_mrr` | 0.989 |
| `fpr@10` | 0.000 |
| `errors` | 0 |

QA no-judge gate：

| Metric | Value |
|---|---:|
| `citation_existence` | 1.000 |
| `citation_precision` | 0.867 |
| `citation_paper_precision` | 0.922 |
| `must_contain` | 0.933 |
| `no_answer_success_rate` | 1.000 |

Claim no-judge gate：

| Metric | Value |
|---|---:|
| `claim_recall` | 0.811 |
| `grounded_claim_recall` | 0.722 |
| `no_answer_success_rate` | 1.000 |
| `forbidden_claim_violations` | 0 |
| `errors` | 0 |

LLM-assisted recall 对比：

| Strategy | Paper recall@10 | Chunk recall@10 | Gain | Harm rate | Latency |
|---|---:|---:|---:|---:|---:|
| baseline_no_rewrite | 0.983 | 0.717 | 0 | 0.000 | 246.08 ms |
| local_rewrite_hyde | 0.983 | 0.817 | 4 | 0.025 | 215.31 ms |
| llm_rewrite_hyde | 1.000 | 0.933 | 10 | 0.050 | 3467.58 ms |

## Schema 要点

`qa_set.golden.jsonl` 和 `qa_set.real.jsonl` 每行是一个 `EvalItem`：

```json
{
  "qid": "g001",
  "question": "What is Self-RAG?",
  "category": "factual",
  "intent": "factual",
  "relevant_paper_ids": ["arxiv:2310.11511"],
  "relevant_chunk_ids": ["arxiv:2310.11511::chunk:0001"],
  "citation_chunk_ids": ["arxiv:2310.11511::chunk:0001"],
  "must_contain": ["Self-RAG"],
  "must_not_contain": [],
  "gold_answer": "Short reference answer.",
  "notes": "Why this item exists."
}
```

`qa_set.claims.jsonl` 额外包含：

```json
{
  "expected_claims": [
    {
      "id": "cl001.1",
      "text": "Self-RAG trains a model to retrieve, generate, and critique.",
      "accept_patterns": ["retrieve", "critique", "reflection"],
      "supporting_chunk_ids": ["arxiv:2310.11511::chunk:0001"]
    }
  ],
  "eval_tags": ["query_mismatch", "method"]
}
```

`relevant_chunk_ids` 用于检索：系统有没有找到核心证据。
`citation_chunk_ids` 用于引用：最终引用是否能直接支撑答案。
`supporting_chunk_ids` 用于 claim grounding：答案覆盖的 claim 是否真的被 cited chunk 支撑。

## 指标怎么读

| 指标 | 含义 | 常见失败原因 |
|---|---|---|
| `positive_paper_recall@k` | 正例目标论文是否进入 top-k | query rewrite 不够、paper scope 错、embedding/index 缺失 |
| `positive_chunk_recall@k` | 目标证据 chunk 是否进入 top-k | chunk 太粗/太碎、rerank 排错、术语召回弱 |
| `positive_paper_mrr` | 目标论文是否排在前面 | fusion/rerank 权重不合适 |
| `fpr@k` | 危险误召回是否出现在正确证据前 | 近邻论文干扰、过滤条件弱 |
| `citation_existence` | citation id 是否都来自 selected evidence | 伪引用、prompt 未约束、后处理漏校验 |
| `citation_precision` | citation 是否命中 `citation_chunk_ids` | 引用背景 chunk、同论文错 chunk |
| `citation_paper_precision` | citation 是否至少来自相关论文 | 错论文引用 |
| `claim_recall` | 答案覆盖了多少 expected claims | 答案漏结论、prompt 太保守、evidence selection 太窄 |
| `grounded_claim_recall` | covered claim 是否由 supporting chunks citation 支撑 | 答案说到了但引用没支撑 |
| `no_answer_success_rate` | no-evidence 是否拒答或说明证据不足 | abstain 阈值太松、检索噪声太强 |
| `rewrite_gain_count` | rewrite/HyDE 相比 baseline 新增命中多少样本 | LLM rewrite 有召回收益 |
| `rewrite_harm_rate` | rewrite/HyDE 相比 baseline 伤害多少样本 | rewrite 漂移或 HyDE 引入噪声 |

## 怎么扩展评测集

1. 先 ingest 你要覆盖的论文，确认 chunk 已进入 SQLite/Qdrant。
2. 每篇论文写 3-5 个 factual/method/evaluation 问题。
3. 每个主题加 compare、ambiguous、no-evidence 样本。
4. 先标 `relevant_paper_ids`，跑 `make eval-golden`。
5. 对核心题补 `relevant_chunk_ids`，再看 chunk recall。
6. 对最终答案可引用的直接证据补 `citation_chunk_ids`。
7. 对复杂题拆 2-4 个 `expected_claims`，每个 claim 标 `accept_patterns` 和 `supporting_chunk_ids`。
8. 跑 `make eval-claims-report`，看 missing claims，再决定是改检索、改 evidence selection、改 prompt，还是修标注。

不要为了过 gate 随便扩大标签。`citation_chunk_ids` 和 `supporting_chunk_ids` 只标能直接支撑答案的 chunk。

## 怎么解释结果

一个 RAG 改动有效，至少要满足：

- `make eval-golden` 不退化，尤其是 paper/chunk recall 和 MRR。
- `make eval-golden-qa` 不退化，尤其是 citation precision 和 no-answer。
- `make eval-claims` 不退化，尤其是 grounded claim recall。
- 如果改的是 rewrite/HyDE，`make eval-llm-recall` 应该显示 gain 多于 harm。

如果失败：

- retrieval 失败：先看 query、dense/sparse top-k、RRF/rerank、chunk 标注。
- citation 失败：看 `docs/RAG_CITATION_AUDIT.md`，区分 wrong paper、right paper wrong chunk、未引用。
- claim 失败：看 `docs/RAG_CLAIM_EVAL_REPORT.md` 的 missing claims。
- no-evidence 失败：看 abstain decision、evidence count、top score 和 answer 是否出现无证据断言。

## 常见误区

- 不要把 `eval-golden` 说成“模型评测”；它是 ID-level retrieval eval。
- 不要把 LLM judge 放进默认快速 gate；它成本高且有波动。
- 不要把 citation existence 等同于 citation precision。前者只证明 chunk id 没编造，后者才检查是否支撑答案。
- 不要把 claim recall 当成 NLI verifier。当前 v1 是 deterministic pattern + token-overlap，优点是稳定、低成本、可审计。
- 不要用 discovery/wiki/memory 当最终证据来源；最终答案仍必须回到 indexed chunks 和 citations。
