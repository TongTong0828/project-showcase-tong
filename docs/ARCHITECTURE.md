# ARCHITECTURE

> 一处看完 paper_rag 的整体设计。详细决策见各 ADR。

## 总览

```
┌─────────────────────── 离线 (Offline indexing) ───────────────────────┐
│                                                                       │
│   A0. Discover      A. Ingest         B1. Parse         B2. Index    │
│   ┌──────────┐     ┌────────┐        ┌──────────┐      ┌─────────┐  │
│   │ topic -> │     │ arxiv  │        │ MinerU   │      │ Qdrant  │  │
│   │ search + │ ──► │ s2/url │  ───►  │ local    │ ───► │ +       │  │
│   │ ranking  │     │ local  │        │ chunks   │      │ SQLite  │  │
│   └──────────┘     └────────┘        └──────────┘      └─────────┘  │
│   Discovery 只给候选与理由；手动 ingest 后才进入最终 QA 证据链。       │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────── 在线 (Agentic RAG) ────────────────────────────┐
│                                                                       │
│   DeerFlow Lead Agent  ──►  paper-research subagent                  │
│                              │                                        │
│                              ▼                                        │
│   community/paper_rag/tools.py (LangChain @tool wrappers)            │
│                              │                                        │
│                              ▼                                        │
│   paper_rag.tools.* (paper_discover / paper_search / paper_qa /      │
│                      paper_section / paper_compare / wiki_lookup)    │
│                              │                                        │
│   paper_qa 内闭环：意图 ─► 改写 ─► 混合检索 ─► rerank ─► 反思 ─► 迭代 │
│                              │                                        │
│   ┌──────────────────────────┴───────────────────────┐               │
│   ▼                                                  ▼               │
│   Qdrant.paper_chunks (dense)   +   SQLite (chunks/sections)         │
│   BM25 in-memory (sparse)       +   FlagReranker (cross-encoder)     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────── 自进化 Wiki (反哺) ────────────────────────────┐
│                                                                       │
│   每篇 ingest 完成 → on_paper_indexed(paper_id)                       │
│       └─ extract_concepts (LLM, 保 recall)                            │
│       └─ normalize (name → alias → 语义近邻 0.85)                     │
│       └─ create_entry / patch_entry (self_eval ≥0.7, 24h 限频)        │
│       └─ 写 SQLite wiki_entries/versions + Qdrant.wiki_entries        │
│                                                                       │
│   wiki_lookup tool   ─►   反哺 paper_qa（HyDE 种子；M5 启用）         │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

## 关键设计原则

1. **5 子系统解耦**（ADR-0001）：Discovery / 采集 / 解析入库 / 检索 / Wiki，独立可测可换
2. **双库分工不混**（ADR-0004）：Qdrant 只做向量+metadata 过滤；SQLite 只做关系/CRUD/wiki
3. **受控 loop 分层**：`paper_discover` 负责找候选论文，`paper_qa` 内闭环负责证据问答；候选摘要不能直接当 citation
4. **Wiki patch 不 rewrite**（ADR-0007）：LLM 只能 add_*；24h 限频；self_eval gate；版本日志
5. **DeerFlow 集成走 community/ + built-in subagent**（ADR-0008）：不 fork lead_agent，不破 harness/app boundary

## 状态机（ingest_pipeline）

```
created → fetched → parsed → chunked → embedded → indexed → done
                                                              │
                                                              ▼
                                                    (trigger wiki, optional)

任一步异常 → failed (with error 字段)；status 不退；可手动 force=True 重跑。
```

## 数据契约

### Chunk metadata（Qdrant payload 与 SQLite chunks 共同字段）

```python
{
    "chunk_id": str,            # 全局唯一
    "paper_id": str,            # arxiv:/doi:/sha1:/s2:/openalex:
    "section_id": str | None,
    "section": str,             # section name
    "section_idx": int,
    "modality": "text|figure|table|formula",
    "page": int | None,
    "text": str,                # 原文（payload + sqlite 都存）
    "context_text": str,        # 加了 [Title:][Section:] 前缀，仅 embedding 用
    "title": str,               # 论文标题，避免 join
    "neighbors": [chunk_id, ...] # 邻接 chunk
}
```

### Wiki entry（pydantic in `wiki/schema.py`）

```python
{
    "entry_id": "concept:<normalized name>",
    "name": str,
    "aliases": [str],
    "category": "concept|method|task|dataset|metric",
    "definition": str,
    "key_papers": [paper_id],
    "variants": [{"name", "summary", "paper_id"}],
    "related": [entry_id],
    "open_problems": [str],
    "evidence_chunks": [chunk_id],
    "version": int,             # 每次 upsert +1
    "updated_at": datetime,
    "lock_until": datetime,     # 24h 限频
}
```

## 调用边界

- `paper_rag` 包永远不导入 `deerflow.*` 或 `app.*`
- `backend/.../community/paper_rag/tools.py` 通过 `_ensure_paper_rag_importable()` lazy 注入 sys.path
- `backend/.../subagents/builtins/paper_research.py` 注册 `paper-research` 专家 subagent
- DeerFlow 不知道 `paper_rag` 的内部 schema；只看 LangChain Tool 的 JSON 字符串

## 配置生效顺序

1. CLI 参数 / env var
2. `config_path` 指定的 yaml
3. 默认 `config/default.yaml`
4. pydantic 默认值
