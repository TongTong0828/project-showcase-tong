# DeepSeek Harness Migration Research

## 1. 调研结论

DeepSeek Harness 可以替代本项目的 DeerFlow Agent Runtime，但不能开箱替代 DeerFlow
承载的多用户 Gateway、BetterAuth 和专用 Paper RAG Dashboard。目标产品已明确为
**Chat-first 本地研究助手**，因此第一阶段不要求复制 Dashboard；通过工具和结构化
Tool Card 完成论文发现、入库、问答、比较和交付。

正确边界是：

```text
替换：Agent Runtime / Session / Skill / Tool host / Chat UI
保留：paper_rag domain core / storage / eval / cron / data
新增：MCP contract + DSH preset/policy/presentation
```

## 2. 当前仓库证据

### R1 · `paper_rag` 已经是独立领域内核

- `src/paper_rag/` 有 120 个 Python 文件、约 13.6K LOC。
- 领域层包含采集、解析、切分、检索、Agentic QA、Wiki、Discovery、Deliver、
  Feedback 和 Proactive。
- `paper_rag` 包不导入 `deerflow.*` 或 `app.*`。
- `src/paper_rag/tools/` 已提供稳定的 Python 工具 facade。

结论：不需要复制或重写 Python 内核。

### R2 · DeerFlow 只是宿主适配层，但整体体积很大

- `integrations/deer-flow/` 当前有 1282 个跟踪文件，约 15.5 MB。
- 真正直接引用 Paper RAG 的 DeerFlow 运行/测试/页面文件约 10 个。
- 核心适配器是
  `integrations/deer-flow/backend/packages/harness/deerflow/community/paper_rag/tools.py`，
  仅把 Python facade 包装成 9 个 LangChain Tool。
- 专家 Agent 配置在
  `integrations/deer-flow/backend/packages/harness/deerflow/subagents/builtins/paper_research.py`。

结论：迁移应替换边界适配，不应逐文件翻译 DeerFlow。

### R3 · 现有 QA 内循环必须保留

`src/paper_rag/rag/qa_agentic.py` 已经集中实现：

```text
query resolution
-> wiki background
-> cache
-> classify
-> hybrid retrieve
-> rerank
-> bounded reflect loop
-> abstain
-> evidence selection
-> answer
-> citation validation
```

该链路有硬迭代上限、三档 abstain、引用校验、缓存和 trace。若改成 DSH Workflow，
会把确定性门禁交还模型，导致测试基线和证据纪律退化。

结论：DSH 负责外层研究编排，`paper_qa` 继续负责内层 RAG。

### R4 · 当前专用产品面不能由 DSH 自动复制

DeerFlow Paper RAG 页面约 1184 行，当前提供：

- Ask
- Knowledge Builder
- Inbox
- Subscriptions
- Discovery Trace
- Wiki Context
- Loop Trace
- Research Memory

Gateway Router 约 1362 行，暴露 26 个路由。

结论：第一阶段用 Chat + Tool Result 替代操作入口；只有高频结构化结果才开发 DSH
Conversation Node，不重做整套 Dashboard。

### R5 · 现有测试资产应作为迁移真值

- `tests/` 当前约 294 个测试函数。
- DeerFlow Paper RAG 专属适配/集成测试约 26 个。
- 评测已经覆盖 retrieval、abstain、citation、claim、query resolution、deliver、
  feedback、proactive 和 chaos。

结论：迁移测试必须比较 DSH/MCP 结果与直接 Python 调用，不能只断言“Agent 会回答”。

## 3. DeepSeek Harness 官方源码证据

调研快照：

- GitHub：`deepseek-ai/deepseek-harness`
- 源码快照版本：`0.1.0-rc.5`
- 快照 commit：`47f943859bef60e4160492346772ded9b24f765a`
- 2026-08-13 npm CLI 最新版本：`@deepseek-ai/dsh@0.1.0-rc.6`
- 官方状态：Developer Preview，README 明确声明存在 compatibility-breaking changes。

### R6 · DSH 能替代 Agent Runtime

官方架构提供：

- append-only Session Event Log
- Agent Loop / Turn / Step
- model adapters
- tool registry
- Skills
- Plan / Goal / Todo
- Subagents / Workflow / Ralph
- approval and filesystem sandbox
- Web、Headless、ACP、JSON-RPC 和 Python SDK

结论：DeerFlow 的 Agent Runtime、LangGraph Tool Host、通用 Chat 和 Session 层可被替代。

### R7 · Everything is a Plugin 适合做领域 Preset

DSH 通过 Cordis 在共享 Context 上提供：

```text
ctx.llm
ctx.tools
ctx.sessions
ctx.skills
ctx.agents
ctx.sandbox
ctx.jobs
ctx.goals
```

Agent Preset 可以选择只挂载领域工具，而不继承标准 Coding Agent 的 Bash、文件编辑、
Code Mode、Ralph 和通用子 Agent。

结论：Paper Research 应是独立的受限 Preset，而不是修改 `standard` Preset。

### R8 · MCP 是 Python/TypeScript 的合理协议边界

DSH 官方通用 MCP Client：

- 支持 stdio 与 Streamable HTTP。
- 将工具注册为 `mcp__<serverName>__<toolName>`。
- 支持 JSON Schema 输入、structuredContent、调用超时和自动重连。
- MCP 子进程可由插件生命周期启动和停止。

结论：Python 领域工具应通过 stdio MCP 暴露，避免把业务重写成 TypeScript。

### R9 · 通用 MCP Client 不会透传 DSH Session 身份

官方 `mcp-client/src/tools.ts` 调用 MCP 时只发送：

```json
{
  "method": "tools/call",
  "params": {
    "name": "<raw tool name>",
    "arguments": "<model-visible arguments>"
  }
}
```

`ToolExecution` 内部虽然带 `exec.agent`，通用 MCP Client 没有把它放入请求 metadata。

结论：

1. 官方通用 MCP Client 不能作为产品身份桥，不能假装自动拥有安全的
   DSH-session → Paper-RAG-conversation 映射。
2. 产品路径必须使用 Native Broker，从 `exec.agent.id` 注入隐藏的
   `conversation_id`；模型不能传该字段。
3. DSH 负责把 follow-up 解析成 self-contained question，Broker 总是把该结果作为
   authoritative outer resolution 传给 Python，避免第二次 rewrite。
4. wire contract 固定为 MCP `tools/call.params._meta.paper_rag`；G0 必须证明 TypeScript
   Broker 发送、Python Server 接收，且 metadata 不进入 raw Schema 或 Session。不能
   实现时 G0 失败。

### R10 · DSH Web 当前不是多用户公网平台

官方 Web Server 文档说明：

- 默认监听 `127.0.0.1`。
- 没有 TLS、认证或完整 origin policy。
- 非 loopback bind 会把服务直接暴露到网络。
- CLI 目前有意不支持 `--host 0.0.0.0`。

结论：本 spec 只承诺本机/可信环境单用户运行；多用户 SaaS 是独立后续项目。

### R11 · Sandbox 不是完整隔离

默认权限是 `workspace-write + ask`，但主要约束文件副作用：

- 不完整限制网络。
- 不完整隐藏宿主进程。
- 不是容器或 microVM。

结论：Paper Research Preset 不应默认暴露 Bash、文件编辑、Code Mode 和任意 URL fetch。

### R12 · 版本必须锁定，不能跟随 latest

源码快照为 `0.1.0-rc.5`，npm 已出现 `0.1.0-rc.6`。官方包体系要求同版本组合，插件
与 Session 格式仍在预发布阶段。

结论：G0 必须选择并锁定同一 release train；升级必须单独执行兼容测试，不能在迁移
中间自动漂移。

### R13 · 当前 `user_id` 不是完整语料租户边界

代码核对结果：

- `Paper` 表有 `user_id` 字段。
- conversation、feedback、subscription、inbox 等状态按 user id 隔离。
- 当前 dense/sparse retrieval 和 Qdrant search 不按 user id filter。
- `upsert_paper()` 没有稳定把 ingest metadata 中的 user id 写入 `Paper.user_id`。
- `paper_discover` 当前硬编码 `user_id="tool"`。
- `paper_compare` 的 QA 子调用会回落到 `user_id="system"`。

结论：本迁移只能承诺本地单用户 shared corpus，不能把现有 `user_id` 描述成安全的
多租户检索隔离。新 MCP 使用可信 `actor_id` 归属 memory/feedback/proactive/discovery
状态，默认 `system` 兼容现有数据；所有论文 retrieval 仍属于一个本地共享语料库。
真正的 tenant-scoped SQLite + Qdrant retrieval 需要独立数据设计和迁移，不进入本 spec。

### R14 · 通用 stdio MCP 不会继承 Paper RAG 模型密钥

DSH 的 subprocess/MCP transport 会删除名称匹配 `KEY|PASSWORD|SECRET|TOKEN` 的环境
变量，再合并插件显式配置的 `env`。因此父进程中的 `OPENAI_API_KEY` 和
`VISION_API_KEY` 不会隐式进入 Python MCP child。

Paper RAG 当前从 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`CHAT_MODEL` 等环境变量展开
配置；没有 key 时真实 QA/Wiki/Deliver LLM 调用会失败。DSH 自己能调用模型不代表
Python Core 自动获得同一凭据。

结论：产品路径不能仅挂载官方通用 MCP Client。需要一个 integration-owned native
Broker：

1. 从 `ctx.credentials` 按 reference 解析 Paper RAG 所需 secret。
2. 只在启动私有 MCP child 时通过显式 env 注入。
3. credential 更新时安全轮换 child generation。
4. secret 不进入 Cordis 配置、dump、Session、tool result 或测试报告。

### R15 · `tools/pre-execute` 缺失时默认允许

DSH Tool Runtime 的 pre-execute waterfall 在没有 policy listener 时默认返回 allow。
Approval Service 本身是 fail-closed 的，但只有调用方主动执行 `approval.request()` 时才
生效。把写工具作为普通 MCP tool 暴露，再依赖另一个 policy 插件返回 ask，会在 policy
未加载、scope 错误或 HMR 卸载时绕过审批。

结论：写工具审批必须在 native Broker 的 tool executor 内直接调用
`ctx.approval.request()`；只有 `allowed-once` 才调用私有 MCP。Broker 必须静态依赖
`tools + approval + credentials`，且只在 agent-scoped preset 内激活。任一服务缺失、
scope 错误、MCP/credential 初始化失败时，Paper RAG 工具都不注册。

### R16 · MCP `structuredContent` 不等于模型可见内容

官方 MCP Client 会保存 canonical `structuredContent`，但 Native 模型默认只看到
`output.render()` 生成的 text。MCP `isError=true` 还会被转换成普通 Error，结构化错误
字段可能丢失。

结论：所有会影响 Agent 决策的字段必须由 Broker 生成有界 text projection，包括：

- `ok/error.code/retryable`
- `abstain`
- `citations`
- `evidence_role`
- `trace_id`
- `truncated`

领域失败使用成功 transport 下的 `{ok:false,error}` canonical result；只有协议断开、
child crash 等 transport failure 才抛出稳定 `[MCP_UNAVAILABLE]` 错误。

### R17 · 现有评测和 P0 门禁依赖 DeerFlow venv

当前 `eval-golden`、`eval-golden-qa`、`eval-claims`、`eval-citation-audit` 和
`verify-p0` 都通过 `DEERFLOW_BACKEND_PY` 执行。若 G5 先删除 DeerFlow，再只运行当前
Python Core 清单，会同时失去：

- golden retrieval gate；
- QA/citation gate；
- claim gate；
- focused P0 guard；
- 65 个 DeerFlow Gateway/Middleware/LangGraph 测试承载的能力清单。

结论：G0 前冻结质量 baseline；G1 前把评测命令迁到 migration-owned Python 环境；G5
机器门禁必须显式运行 retrieval、QA/citation、claim、P0、能力迁移矩阵和 clean
checkout validator，不能通过删除旧测试获得绿色。

### R18 · DSH Session v0 不承诺跨 RC 兼容

官方 Session 和 JSONL persistence 都声明 `SESSION_FORMAT_VERSION=0`，旧格式没有升级
路径，compression/layout 变化要求使用新 root。仅在同版本进程内测试 restart/resume，
不能证明升级或降级兼容。

结论：Session root 必须按 exact DSH version 分代。升级时保留旧 binary/lockfile/root，
复制真实上一版本 fixture 做只读兼容验证；新版本不得原地改写唯一 Session 副本。回退
恢复旧版本及旧 root，而不是让旧 binary 读取新 root。

## 4. 方案比较

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 重写 Python Core 为 TS Plugin | 表面上单语言 | 重写 13.6K LOC，丢失评测基线 | 拒绝 |
| DSH Plugin 直接调用现有 HTTP Gateway | POC 快 | 继续保留 Gateway/FastAPI/旧产品耦合 | 仅可做 G0 spike，不作为最终边界 |
| 通用 DSH MCP Client + Python stdio MCP 直接暴露 | 解耦、POC 快 | 不透传 session/credential；写审批易失配；模型 text projection 受限 | 仅限 G0 fixture，不作为产品路径 |
| Native Broker + 私有 Python MCP | 可注入 credential/session；审批 fail-closed；精确 tool catalog；按工具超时 | 增加薄 TS Broker | 选定产品路径 |
| Fork DeepSeek Harness | 可任意改 UI/Runtime | 与预览版上游同步成本高 | 拒绝 |
| 立即删除 DeerFlow | 快速收口 | 无法回滚、容易漏产品能力 | 拒绝 |

## 5. 已确认设计决策

1. 新建独立规格目录，本迁移不是已有单一 RAG 功能的增量。
2. 通用 MCP 实现在 `src/paper_rag/mcp/`，DSH 专属配置在
   `integrations/deepseek-harness/`。
3. 项目 Skill 放 `.dsh/skills/paper-research/SKILL.md`，遵循 DSH 默认发现路径。
4. 首版是 Chat-first 本地单用户，不复制 DeerFlow Dashboard。
5. Paper RAG Native Broker 私有连接 MCP；原始 MCP 工具不直接注册到模型工具目录。
6. 写操作在 Broker executor 内直接调用一次性 Approval Service；不是外挂
   `pre-execute` listener。
7. Deliverable 返回 artifact locator，不把 Base64 或大二进制写入 Session。
8. G4 前 DeerFlow 保留，G5 才删除。
9. 本 spec 采用 single-actor + shared-corpus，不声称实现多用户检索隔离。
