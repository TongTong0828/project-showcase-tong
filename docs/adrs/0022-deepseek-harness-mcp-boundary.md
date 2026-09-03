# ADR-0022 · DeepSeek Harness + MCP 宿主边界

- **日期**: 2026-08-13
- **状态**: final after G5
- **关联**: `specs/20260813-deepseek-harness-migration/`
- **Supersedes**: ADR-0008 / ADR-0015 / ADR-0020 / ADR-0021 的旧宿主决策

## Context

Paper RAG 的领域内核已经覆盖论文发现、入库、混合检索、Agentic QA、拒答、引用校验、Wiki、
交付物、反馈和主动能力。G5 后产品宿主收口到 DeepSeek Harness + MCP，旧 gateway、LangChain
Tool、旧 Agent Runtime、通用聊天入口、BetterAuth、LangGraph middleware 和监控运行面已退役。

产品目标改为本地单用户、Chat-first 的论文研究 Agent，而不是继续扩展多人旧宿主平台。
DeepSeek Harness 提供 Web、Session、Skill、Tool、审批和 Agent Runtime；MCP over stdio 适合作为
宿主与 Python 领域内核之间的稳定协议边界。

## Decision

采用 DeepSeek Harness 作为新的产品宿主，并通过 Native Broker + 私有 MCP child 连接现有
`src/paper_rag/`：

```text
DeepSeek Harness Web/Session/Agent
  -> paper-research Preset + project Skill
  -> Paper RAG Native Broker
  -> private stdio MCP
  -> paper_rag Python tools/application services
  -> SQLite + Qdrant + artifact directory
```

边界规则：

1. `src/paper_rag/` 不导入 DeepSeek Harness、Cordis 或 DSH UI。
2. `paper_rag.mcp` 是通用协议适配层，只调用现有领域 facade/application services，不复制
   retrieval、rerank、reflect、abstain 或 citation 逻辑。
3. 产品模型目录只暴露 Broker 注册的稳定 native tools；raw `mcp__paper_rag__*` 不进入
   Paper Research Preset。
4. `user_id/actor_id/conversation_id` 不出现在 model-visible schema。Broker 从可信 DSH
   execution context 注入 hidden metadata，Python Server 只信任 ServerConfig/RequestContext。
5. 写工具由 Broker executor 直接调用一次性 Approval；批准后再通过隐藏 `operation_id`
   和 Python 持久 receipt 防止 crash/reconnect/resume 重复副作用。
6. DSH Session 只作为外层对话和工具轨迹权威，不作为论文 claim 证据。最终论文结论仍只来自
   当前 indexed chunks。
7. G5 已删除旧宿主、旧测试和旧文档入口；回滚通过 `deepseek-harness-g5-pre-removal` tag 恢复宿主代码。

## Consequences

### Positive

- 领域内核继续保持 Python 包边界，可被 DSH、Codex、Claude Code 或其他 MCP Client 复用。
- 新产品入口更贴近本地研究助手，减少旧 gateway/auth/dashboard 相关运行面。
- 审批、凭据、Session、tool catalog 和写入幂等由迁移规格统一门禁验证。
- G0-G5 分阶段迁移；G5 后如需回滚宿主代码，仍不迁移或回滚 SQLite/Qdrant 主数据。

### Negative / Trade-offs

- DeepSeek Harness 仍处 Developer Preview，必须 exact pin 版本并验证 compatible Cordis graph。
- Native Broker 需要维护 DSH/Cordis API 适配、generation 生命周期和 exact catalog invariant。
- 本地单用户边界不会自动提供 tenant-scoped corpus；shared corpus 语义必须在文档和测试中保持明确。
- G4/G5 依赖 DSH smoke、clean checkout、旧能力矩阵和残留扫描，不执行真实写入论文库的 live smoke。

## Impact on Earlier ADRs

以下 ADR 的历史内容保留，但其中关于旧宿主作为长期产品宿主的决策进入 superseded 状态：

- ADR-0008：旧 LangChain Tool + Skill 集成边界由 DSH Preset + Native Broker + private MCP 替代。
- ADR-0015：旧 Gateway / BetterAuth / HTTP 产品宿主决策由本地 DSH Web + MCP 工具入口替代；SQLite/Qdrant 主数据不随宿主回滚。
- ADR-0020：旧 Gateway middleware 和观测栈属于退役宿主能力；仍适用的 timeout、redaction、metrics 要求已迁移到 Broker/DSH/Gate。
- ADR-0021：旧 LangGraph middleware 加固属于退役 Agent Runtime；仍适用的 cost、latency、recursion、PII 能力迁移为 DSH/Broker 行为测试或被明确判定为 host-specific。

G5 完成后，这些 ADR 从 `pending supersede` 改为 `superseded`。

## Gate Policy

正式 G0 只能在迁移规格提交且 checkout clean 后开始。G0 必须证明 exact DSH versions、loopback
Web、custom Preset、Native Broker、private MCP、credential bridge、direct Approval、
Session resume、crash/reconnect、cancel/timeout、standing generation 和 report validator
全部满足 `specs/20260813-deepseek-harness-migration/test/` 的 P0 用例。

任一 Gate 未通过时，只回滚该 Gate 新增的 DSH/MCP/Broker 层；不删除或回滚 Paper RAG 主数据。
