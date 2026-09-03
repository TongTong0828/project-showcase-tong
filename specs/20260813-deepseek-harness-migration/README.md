# DeepSeek Harness Migration

**状态**：Completed（G0-G5 已按 manifest 执行，G5 清退旧宿主）
**日期**：2026-08-13
**目标**：用 DeepSeek Harness 替换旧 Agent Runtime，保留并复用现有 `paper_rag` Python 领域内核。

## 文档地图

| 文档 | 职责 |
|---|---|
| [`HANDOFF.md`](./HANDOFF.md) | AI 从任意 cwd/worktree 接手时的仓库发现、文件优先级和启动规则 |
| [`spec.md`](./spec.md) | SPEC：产品目标、用户故事、功能需求、范围和最终验收 |
| [`plan.md`](./plan.md) | SDD：目标架构、组件边界、工具与会话契约、部署、迁移和回滚设计 |
| [`database-change-plan.md`](./database-change-plan.md) | 数据变更计划：新增写操作幂等 receipt 表，论文主数据与 Qdrant schema 不变 |
| [`tasks.md`](./tasks.md) | 分阶段实施任务与 Gate 状态 |
| [`research.md`](./research.md) | 代码与 DeepSeek Harness 官方源码调研证据 |
| [`test/case.md`](./test/case.md) | SDT：功能、契约、行为、故障与切换测试用例 |
| [`test/task.md`](./test/task.md) | SDT 分 Gate 执行任务 |
| [`test/manifest.md`](./test/manifest.md) | 人可读测试命令与阶段门禁 |
| [`test/test-manifest.json`](./test/test-manifest.json) | 机器可读测试清单 |
| [`test/cleanup-plan.md`](./test/cleanup-plan.md) | 测试数据、进程、配置和 DeerFlow 退役清理计划 |

## 一句话方案

```text
DeepSeek Harness Web/Session/Agent
  -> Paper Research preset + project Skill
  -> Paper RAG Native Broker
  -> private Paper RAG MCP
  -> existing paper_rag Python core
  -> SQLite + Qdrant + artifact directory
```

不是重写 `src/paper_rag/`，也不是把 RAG 内循环改成 Harness Workflow。迁移对象是
`integrations/deer-flow/` 所承载的 Agent Runtime、LangChain Tool、通用聊天入口和
宿主集成。

## Gate Ledger

| Gate | 状态 | 通过条件 |
|---|---|---|
| G0 · 版本与可行性 Spike | Passed | 锁定一套同版本 DSH 包，验证 Web、Preset、MCP、审批和 Session 恢复 |
| G1 · 只读 MVP | Passed | `search/qa/section/wiki` 通过 MCP 在 DSH 中可用，引用与拒答不退化 |
| G2 · 完整研究链 | Passed | Discover → Confirm → Ingest → QA/Compare → Deliver 全链路通过 |
| G3 · 主动能力 | Passed | Inbox/Subscription/Feedback 可通过 Chat-first 工具管理，cron 独立运行 |
| G4 · 默认入口切换 | Passed | README/Makefile/CI 默认指向 DSH，DSH cutover smoke 与 clean checkout 通过 |
| G5 · 旧宿主退役 | Passed | 无运行依赖、无未迁移 P0 能力、回滚 tag 已保存，旧宿主源码已删除 |

任何 Gate 未通过时，只回滚该阶段新增的 DSH 层；`src/paper_rag/`、SQLite 和 Qdrant
数据不随宿主回滚。
