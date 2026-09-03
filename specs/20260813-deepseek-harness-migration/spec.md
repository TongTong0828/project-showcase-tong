# SPEC：DeepSeek Harness 替换 DeerFlow

**Feature**：`20260813-deepseek-harness-migration`
**状态**：Approved for G0（未开始实现）
**目标形态**：Chat-first、本地单用户论文研究 Agent
**主入口**：DeepSeek Harness Web
**业务内核**：现有 `src/paper_rag/`

## 1. 背景

Paper RAG 已经完成论文发现、采集、解析、混合检索、Agentic QA、拒答、引用校验、
Wiki、交付物、反馈和主动能力。当前产品将整个 DeerFlow 源码内嵌在
`integrations/deer-flow/`，用其提供 Agent Runtime、LangChain Tool、Gateway、
BetterAuth、通用聊天 UI 和 Paper RAG 专用页面。

本项目接下来的目标不是继续建设多人 DeerFlow 平台，而是形成一个更轻、更清晰的
本地论文研究 Agent。DeepSeek Harness 提供完整 Agent Runtime、Session、Skill、
Tool、审批、多 Agent 和 Web UI，适合替换 DeerFlow 宿主层。

## 2. 目标

1. 用 DeepSeek Harness 替换 DeerFlow 的 Agent Runtime、Session、Skill 和通用 Chat。
2. 通过一个 DSH Native Broker 私有连接 MCP，复用现有 Python 工具，不重写 Paper
   RAG 内核。
3. 让用户在一个聊天窗口完成：
   - 搜索已入库论文；
   - 带引用问答；
   - 阅读章节；
   - 发现候选论文；
   - 确认并入库；
   - 多论文比较；
   - Wiki 查询；
   - 导出 BibTeX；
   - 生成 Markdown、PPTX、DOCX、LaTeX/BibTeX 和 PDF；
   - 管理订阅、Inbox 和反馈。
4. 保持现有 retrieval、abstain、citation、query resolution 和评测质量不退化。
5. 在新入口稳定后，删除 `integrations/deer-flow/` 及其专属依赖和文档。

## 3. 非目标

- 不把 `src/paper_rag/` 重写成 TypeScript。
- 不把 `qa_agentic` 内循环改成 DSH Workflow。
- 不 Fork 或 vendor DeepSeek Harness 源码。
- 不在第一版复制 Knowledge Builder、Inbox、Subscriptions 等完整 Dashboard。
- 不提供公网、多用户、团队租户、SSO 或 BetterAuth 替代。
- 不在本迁移中补齐 tenant-scoped retrieval/Qdrant filter；论文语料按本地 shared corpus
  运行。
- 不迁移 DeerFlow 历史聊天记录到 DSH Session。
- 不改变 SQLite/Qdrant 主数据格式，除非独立数据兼容测试证明必要。
- 不在第一阶段默认开放 Bash、文件编辑、Code Mode、Ralph 或任意子 Agent。
- 不把 Discovery Web 摘要当作最终论文证据。

## 4. 用户故事

### US1 · 已入库论文问答

作为研究者，我希望直接在 DSH 聊天窗口询问论文问题，并得到带
`[chunk:<id>]` 引用的回答；证据不足时系统应明确拒答，而不是继续猜测。

### US2 · 论文发现与人工选择

作为研究者，我希望让 Agent 搜索一个研究主题、返回带理由的候选列表，然后由我选择
哪些论文入库。候选摘要在入库前不能成为最终引用证据。

### US3 · 安全入库

作为研究者，我希望 Agent 在执行下载、解析、embedding 和持久化前明确请求确认。
批量入库应有限额，失败不应破坏既有索引。

### US4 · 跨论文研究

作为研究者，我希望比较少量论文的方法、实验和局限，并让 Agent 组织多个有界的
`paper_qa` 调用。系统不能创建无限子 Agent 或不受控 fan-out。

### US5 · 可交付产物

作为研究者，我希望生成 Markdown 综述、PPTX、DOCX、LaTeX/BibTeX 或 PDF，并在
聊天中获得可打开的文件，而不是一段 Base64。

### US6 · 长会话恢复

作为研究者，我希望关闭页面后恢复同一 DSH Session，继续此前研究。DSH Session 是
外层对话权威；Python 内核不得再次用另一套历史把问题改写成不同含义。

### US7 · 主动研究辅助

作为研究者，我希望通过聊天管理关键词订阅、查看 Inbox、标记通知、触发 digest/stale
扫描并提交反馈。定时任务可以继续由现有 cron sidecar 执行。

### US8 · 可诊断与可回滚

作为维护者，我希望能查看 MCP 工具调用、trace id、abstain、citation 和故障类型；
在 DSH 预览版升级或新入口故障时，能在 G5 前切回 DeerFlow，而不迁移或回滚论文数据。

## 5. 功能需求

### 5.1 Runtime 与版本

| ID | 需求 | 可测判据 |
|---|---|---|
| FR-001 | DSH 版本锁定 | 所有直接 `@deepseek-ai/dsh*` 包使用同一 exact DSH 版本；Cordis/vendor 使用该 DSH 发布图验证过的 exact compatible version；lockfile 无重复 Cordis 实例和 peer 冲突 |
| FR-002 | DSH 独立运行 | 未启动任何 DeerFlow 进程时，DSH Web、MCP Server 和 Paper RAG 工具可用 |
| FR-003 | 不 vendor DSH | 仓库不新增 DeepSeek Harness 源码副本，只保存 profile/preset/plugin/lockfile |
| FR-004 | 本地边界 | 默认只监听 loopback；doctor 校验 effective Web config 和实际 listening socket，对非本地暴露给出阻断错误 |
| FR-005 | 私有 MCP | 原始 MCP tools 不直接注册进模型目录；只有 Native Broker 注册的受控原生工具可见 |
| FR-006 | 凭据桥 | Broker 从 `ctx.credentials` 解析 credential references，仅通过私有 child 的显式 env 注入；secret 不进入配置、dump、Session、结果或报告 |
| FR-007 | 精确目录 | `agent/created` 对每个 Agent 的 `agent.ctx` 应用 exact allowlist，`agent/pre-step` 重新核对完整目录；G1 只包含 `skill`、`ask_user_question` 和批准的 Paper RAG 原生工具，任何 extra/missing tool 都拒绝 step |

### 5.2 工具契约

G1 只读工具：

- `paper_status`
- `paper_list`
- `paper_search`
- `paper_qa`
- `paper_section`
- `paper_compare`
- `wiki_lookup`

G2 写入/外部工具：

- `paper_discover`
- `discovery_run_get`
- `paper_ingest`
- `discovery_candidate_ingest`
- `wiki_generate`
- `export_bibtex`
- `paper_deliver`

G3 主动/反馈工具：

- `subscription_list`
- `subscription_add`
- `subscription_toggle`
- `subscription_delete`
- `inbox_list`
- `inbox_mark_read`
- `inbox_dismiss`
- `feedback_record`
- `digest_run`
- `stale_scan`

以上名称同时是 Native Broker 注册给模型的稳定原生工具名。私有 MCP child 的 raw
tool names 可保持相同，但不会以 `mcp__paper_rag__*` 形式直接暴露给模型。

| ID | 需求 | 可测判据 |
|---|---|---|
| FR-010 | Schema 可发现 | MCP `tools/list` 返回稳定名称、描述、输入 Schema 和 outputSchema |
| FR-011 | 双视图输出 | Broker 保留 machine-readable canonical result，并把 `ok/error/abstain/citations/evidence_role/trace_id/truncated` 投影到模型真实可见的有界 text |
| FR-012 | Actor 身份隐藏 | `user_id/actor_id` 不出现在 model-visible Schema；本地版由 Server 固定 |
| FR-013 | Session 身份隐藏 | `conversation_id` 不出现在 model-visible Schema；Broker 仅通过 MCP `tools/call.params._meta.paper_rag` 注入 `exec.agent.id` 等私有 metadata，且不写入 Session tool arguments/results |
| FR-014 | 只读默认可执行 | G1 只读工具无需用户确认 |
| FR-015 | 写操作审批 | 写工具 executor 内直接调用 `ctx.approval.request()`；只有 `allowed-once` 才调用私有 MCP；approval/credentials/tools/scope 任一缺失时工具不注册或启动失败 |
| FR-016 | 批量上限 | Compare 最多 4 篇 × 4 维；一次候选入库最多 5 篇；超限在工具边界拒绝 |
| FR-017 | 本地路径限制 | `pdf_path` 仅允许配置的 import root，拒绝 traversal、symlink escape 和任意绝对路径 |
| FR-018 | 超时与取消 | 900s transport outer cap + Python handler 实际分类 deadline；DSH 取消能终止调用或使同步阶段安全收敛 |
| FR-019 | 错误标准化 | 领域失败使用 `{ok:false,error:{code,retryable}}` canonical result 并投影稳定 `[CODE]` text；transport failure 使用单独稳定错误 |
| FR-027 | 写入幂等 | Broker 在同一 direct-human request boundary 对 canonical args 做 fingerprint guard；批准后生成隐藏 `operation_id`，Python 持久 receipt 保证新 call id、crash、reconnect、resume 均不重复执行 |

### 5.3 证据和 Agent 行为

| ID | 需求 | 可测判据 |
|---|---|---|
| FR-020 | `paper_qa` 默认路由 | 已入库论文的内容问题优先调用 `paper_qa` |
| FR-021 | Abstain 权威 | `paper_qa` 返回 no_evidence 后，Agent 不用记忆或 Web 内容补造论文答案 |
| FR-022 | 引用权威 | Agent 只能展示工具返回的 chunk id，不得发明数字引用或 author-year 引用 |
| FR-023 | Discovery 非证据 | 候选结果明确标记 `discovery_only_not_answer_evidence` |
| FR-024 | 入库后再引用 | 新论文只有 ingest 完成且检索命中后才可进入最终证据 |
| FR-025 | 单一解析权威 | DSH 已将 follow-up 解析成 self-contained question 时，Python 不再次改写 |
| FR-026 | 内循环保留 | retrieval/rerank/reflect/abstain/citation 继续由 `paper_rag` 执行 |

### 5.4 Artifact

| ID | 需求 | 可测判据 |
|---|---|---|
| FR-030 | 文件落盘 | Deliverable 写入配置的 artifact root，使用随机 ID + 安全扩展名 |
| FR-031 | 不返回 Base64 | MCP 结果不含完整二进制或大段 Base64 |
| FR-032 | 元数据完整 | 返回 artifact_id、filename、path/URI、content_type、size、sha256、source_paper_ids |
| FR-033 | 路径不逃逸 | 所有 artifact 路径位于 artifact root 内 |
| FR-034 | 生命周期 | 记录清理策略；删除 artifact 不影响 Paper RAG 主数据 |

### 5.5 Session、Memory 与数据

| ID | 需求 | 可测判据 |
|---|---|---|
| FR-040 | DSH Session 恢复 | 重启 DSH 后相同 session 可恢复对话和工具轨迹 |
| FR-041 | 单一改写权威 | Agent 传 `resolved_question` 时 Python 不再改写；无 resolved question 时是否启用 Paper RAG memory 由 Broker 的明确配置决定 |
| FR-042 | 安全桥接 | 只有 Native Broker 可把 `exec.agent.id` 注入 Python；模型和普通 MCP Client 不可提供 conversation identity |
| FR-043 | 主数据不迁移 | 现有 papers、chunks、wiki、feedback、subscriptions、inbox 和 Qdrant vectors 原地复用；仅在行为库 additive 新增 operation receipt 表 |
| FR-044 | 本地 Actor 兼容 | 默认 actor 为 `system`，或经显式配置改为单一 local actor；不得宣称 shared corpus 已实现租户隔离 |
| FR-045 | Session 不作证据 | DSH Session 和 Research Memory 只能帮助解析/编排，不作为最终论文证据 |
| FR-046 | Session 版本分代 | Session root 按 exact DSH version 分代；升级保留旧 binary/lockfile/root 并用上一版本真实 fixture 验证；新版本不原地改写唯一副本 |

### 5.6 运维、观察和退役

| ID | 需求 | 可测判据 |
|---|---|---|
| FR-050 | Doctor | 检查 DSH 版本、Python、MCP、配置、SQLite、Qdrant、模型和写目录 |
| FR-051 | G0 兼容 runner | 一条真实命令启动 Host/Web/Preset/Broker/MCP/approval/session/cancel/reconnect，并生成结构化 G0 报告 |
| FR-052 | 本地日志安全 | 默认不启用完整 Session telemetry；日志和错误不泄露 API key、PDF 内容和 PII |
| FR-053 | 调用可关联 | 工具结果包含 Paper RAG trace_id，DSH Session 保留 tool/call 与 tool/result |
| FR-054 | 默认入口切换 | README、Makefile、`.env.example` 和 CI 先切到 DSH，DeerFlow 保留为 fallback |
| FR-055 | DeerFlow 退役门禁 | 只有 G0-G4 全通过且 pre-removal 回滚路径确认后，才删除 `integrations/deer-flow/` |
| FR-056 | 文档收口 | 退役时更新 README/ARCHITECTURE/SYSTEM_DESIGN/STATUS/OPERATIONS/ADR，并删除失效运行指南 |
| FR-057 | Gate report validator | G0–G5 结构化报告绑定 commit、exact versions、命令、case 状态、授权、隔离配置和有效期；缺失或过期时 Gate 失败 |
| FR-058 | Live 数据隔离 | Live G2 必须使用 `PAPER_RAG_CONFIG` 指向完整独立 YAML，同时隔离 SQLite、index/papers/parsed、feedback DB 和 Qdrant collections/path；doctor 指向主数据时拒绝执行 |
| FR-059 | 质量门禁独立 | golden retrieval、QA/citation、claim 和 verify-p0 使用 migration-owned Python 环境，不依赖 DeerFlow venv，并成为 G5 机器门禁 |

## 6. Chat-first 产品行为

### 6.1 Discover → Confirm → Ingest → QA

```text
用户：找 10 篇关于 Agentic RAG 的论文
Agent：调用 paper_discover，展示候选编号、来源、评分和理由
用户：入库 1、3、5
Agent：列出即将写入的 3 篇，触发审批
用户：批准
Agent：依次调用 candidate ingest，报告每篇状态
用户：比较三篇的方法和实验
Agent：调用 bounded paper_compare / paper_qa，返回 chunk citations
```

### 6.2 No-evidence

```text
paper_qa.abstain = no_evidence
-> Agent 明确说明当前语料不足
-> 可以建议 discover/ingest
-> 不允许用 Web snippet 或 Session memory 直接补一个论文结论
```

### 6.3 Deliverable

```text
用户：生成 PPT
Agent：列出格式、论文范围和标题，触发审批
用户：批准
Agent：调用 paper_deliver
Agent：返回文件卡片/本地 artifact locator + 生成元数据
```

## 7. 默认安全策略

Paper Research Preset 默认：

- 允许 Paper RAG G1 工具。
- 允许 Skill loader 和 Ask User。
- 使用 exact allowlist，G1 明确不含 `web_search`/`web_fetch`；G2 如单独批准搜索，只用于
  discovery 辅助，不作为 final evidence。
- 不允许 Bash、Pwsh、文件写入、str_replace_editor、Code Mode、Workflow、Ralph。
- 不允许通用 subagent；G3 如开启，只允许固定 Paper Research child preset，并设置：
  - 最大深度 1；
  - 最大并行数 3；
  - 每个子 Agent 最大 8 个 turns；
  - 每次任务最多 4 篇论文。
- `paper_ingest`、`discovery_candidate_ingest`、`wiki_generate`、`paper_deliver`、
  `subscription_*` 写操作和主动触发由 Broker executor 直接调用一次性审批；不是依赖
  可缺失的外挂 policy listener。

## 8. 范围

### 新增

```text
specs/20260813-deepseek-harness-migration/
src/paper_rag/mcp/
.dsh/skills/paper-research/SKILL.md
integrations/deepseek-harness/
tests/test_mcp_*.py
tests/test_dsh_*.py or integrations/deepseek-harness/tests/
```

### 修改

- `pyproject.toml`
- `Makefile`
- `.env.example`
- `.gitignore`
- `Dockerfile`（仅在 DSH 运行方式需要时）
- `.github/workflows/ci.yml`
- 根 README、架构、运维、状态和课程文档

### 最后删除

```text
integrations/deer-flow/
scripts/deerflow_smoke.py
tests/test_gateway_paper_rag.py
tests/test_middleware.py
tests/test_langgraph_middleware.py
docs/integration/deerflow_embedded.md
DeerFlow/LangChain 专属 optional dependencies and Make targets
```

历史 ADR 不物理删除；将 0008/0015/0020/0021 标记为 superseded，并新增迁移 ADR。

## 9. 成功标准

1. 在没有 DeerFlow 进程和依赖的环境中，用户能完成完整研究链路。
2. 直接 Python 与 MCP 的同输入结果在 answer evidence、citation、abstain 和
   query resolution 上等价。
3. DSH 行为评测不出现编造 citation、绕过 abstain、未确认写入和无限工具循环。
4. 所有现有核心测试通过；新增 MCP/DSH 测试通过。
5. Deliverable 可打开，且 Session 日志不保存 Base64。
6. DSH Session 可恢复；同 session follow-up 不发生双重 rewrite。
7. 默认启动、文档和 CI 已不依赖 DeerFlow。
8. G5 后 `rg -i 'deer.?flow'` 仅命中历史说明/ADR 的 superseded 记录，无运行引用。
9. G5 通过 migration-owned 环境运行 frozen retrieval、QA/citation、claim 和 P0 gate，
   且旧 DeerFlow 测试逐用例完成替代/删除分类。

## 10. 迁移门禁

### G0 · 版本与可行性

- 冻结当前质量 baseline 和旧测试能力矩阵。
- 锁定 exact DSH/compatible Cordis 版本。
- 真实 runner 验证 Web、Preset、Native Broker、私有 MCP、credential bridge、approval、
  text projection、取消、恢复和 reconnect。
- `DSH-G0-001..009` 全部通过；结构化报告 validator 通过。
- 记录 upstream compatibility gaps。

### G1 · 只读 MVP

- 只读工具可用。
- 核心 QA 对比通过。
- no-evidence 行为通过。
- DeerFlow 不参与运行。

### G2 · 完整研究链

- Discovery/ingest/compare/deliver 可用。
- 写操作审批和路径安全通过。
- artifact 生命周期通过。
- 如需要多轮 Python memory，session bridge 通过。

### G3 · 主动能力

- Subscription/Inbox/Feedback 工具可用。
- cron sidecar 独立于 DeerFlow。
- 无 Dashboard 也可完成日常管理。

### G4 · 默认入口

- DSH 成为 README/Makefile 默认入口。
- CI 覆盖 DSH smoke。
- `dsh-smoke` 在 clean checkout 上覆盖 loopback、telemetry、credential path、
  timeout policy 和 `paper-research` default preset。
- 不要求 7 天观察窗口；不执行会真实写入论文库的 live smoke。

### G5 · DeerFlow 退役

- 功能矩阵中 P0/P1 全部 `PASS` 或显式 `OUT_OF_SCOPE`。
- 无运行依赖或默认文档引用。
- 回滚窗口结束。
- 删除 DeerFlow、旧测试和旧依赖，运行 migration-owned retrieval、QA/citation、claim、
  P0、CUT validator 和 clean checkout。

## 11. 最终验收

- [ ] G0-G5 全部完成并有测试证据。
- [ ] `src/paper_rag/` 不导入 DSH、Cordis 或 MCP 客户端实现。
- [ ] `integrations/deepseek-harness/` 不实现 retrieval/abstain/citation 业务逻辑。
- [ ] DeerFlow 被删除后核心测试、MCP 测试和 DSH smoke 仍通过。
- [ ] 文档准确描述当前默认运行方式，不把 Developer Preview 描述成稳定生产平台。
