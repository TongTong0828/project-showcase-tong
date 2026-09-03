# DatabaseChangePlan

## Classification

`additive`

## Reason

本迁移不改变论文、chunk、Wiki 或 Qdrant 主数据模型，但为了保证写工具在
crash/reconnect/session resume 下不重复执行，需要在行为数据库新增操作回执表。以下
现有数据继续原地复用：

- papers / sections / chunks / ingest runs
- conversation turns / summaries
- Wiki entries / versions / review queue / usage
- discovery runs / candidates
- feedback events
- subscriptions / inbox / paper access
- Qdrant chunk/wiki collections

## DDL

在现有 `feedback.sqlite` 增加：

```sql
CREATE TABLE IF NOT EXISTS mcp_operation_receipts (
    operation_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    request_boundary_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_operation_fingerprint
ON mcp_operation_receipts(
    conversation_id,
    request_boundary_id,
    tool_name,
    args_sha256
);

CREATE INDEX IF NOT EXISTS idx_mcp_operation_actor_time
ON mcp_operation_receipts(actor_id, created_at);

CREATE INDEX IF NOT EXISTS idx_mcp_operation_lookup
ON mcp_operation_receipts(conversation_id, tool_name, args_sha256, updated_at);
```

`status` 允许：

```text
running
succeeded
failed
cancelled
outcome_unknown
```

`result_json/error_json` 只保存 bounded receipt，不保存完整 chunks、论文正文、Base64 或
credential。每列序列化上限 64 KiB；大结果只保存 trace/artifact locator/关键状态和
content sha256。

`request_boundary_id` 由 Broker 在 `agent/pre-step` 对本次 claimed messages 中所有
`source.kind="user"` 的稳定 `message.id` 按顺序计算：

```text
UUIDv5(fixed_namespace, session_id + "\0" + message_ids.join("\0"))
```

只有 synthetic messages 时继承已有 boundary；resume 后没有新的 direct-user message 时
boundary 为空，写工具被拒绝。`operation_id` 由 Broker 根据固定 namespace 和
`conversation_id + request_boundary_id + tool_name + args_sha256` 生成 UUIDv5，不由
模型提供。同一 user request 内即使模型产生新的 tool call id，也命中同一 operation。

写工具 handler 的顺序：

1. 原子插入 `running` receipt。
2. 已有同 operation id：
   - `succeeded/failed/cancelled`：返回已记录结果；
   - `running/outcome_unknown`：返回 `OPERATION_OUTCOME_UNKNOWN`，不重复执行。
3. 执行业务副作用。
4. 原子更新 final status/result/error。
5. 进程崩溃留下的 `running` 在下一次启动时标记为 `outcome_unknown`，等待领域状态核对或
   用户显式新操作。

`paper_rag.mcp.operations` 在 Server 启动、开始接收 MCP request 之前，用一个事务把旧
`running` 标记为 `outcome_unknown`。更新条件包含启动时间之前的 rows，不能修改本进程
刚创建的 receipt。

同一 conversation 下如果最近相同 `tool_name + args_sha256` 为 `outcome_unknown`，Broker
不得静默生成新 operation。它先展示 unknown 状态和可核对的领域资源，再发起带明确
“重新执行可能重复副作用”文案的一次性审批；只有用户批准后，新 direct-human request
才生成新 operation id。

不新增 Qdrant collection，不修改论文主表。

Retention：

- succeeded/failed/cancelled receipt 默认保留 90 天；
- outcome_unknown 默认长期保留，只有人工核对后才能归档；
- 清理按 actor/time 执行，不影响 feedback/subscription/inbox 数据；
- Gate/live 测试使用独立 feedback DB。

## DML / Backfill

无历史数据回填。表首次使用时幂等创建。

本地版默认使用固定 `actor_id="system"`，并映射到既有 API 的 `user_id` 参数。部署可
显式选择另一个固定 actor，但本 spec 不承诺论文语料按 user id 隔离；当前 corpus 仍是
单用户 shared corpus。该行为不需要数据库迁移。

## Non-Database Persistence

以下是新文件存储：

```text
data/runtime/deepseek-harness/   # DSH profiles/settings/sessions
data/artifacts/                  # deliverable files + manifest.json
```

- DSH Session 格式由锁定的 Harness 版本管理，不写入 Paper RAG SQLite。
- Artifact manifest 是文件级元数据，不新增数据库表。
- 两类目录都可以独立清理，不影响 Paper RAG 主数据。

## Rollout

1. G0/G1 使用隔离测试目录验证。
2. G2 开启 artifact root。
3. G2 开启任何写工具前创建并验证 receipt 表。
4. G4 才将 repo-local DSH runtime 作为默认入口。
5. 不需要停机迁移。

## Rollback

- 停止 DSH、关闭 MCP toolset 或切回 DeerFlow 即可。
- 不回滚已成功写入的论文、Wiki、Subscription、Inbox 或 Feedback 数据。
- 删除 DSH Session/Artifact 不删除 SQLite/Qdrant 数据。
- 回滚时保留 `mcp_operation_receipts`，旧代码不会读取它；不要删除审计和幂等证据。

## Data Risk

数据库结构风险为低且 additive；主要风险来自写工具使用现有接口产生业务数据。通过以下
方式控制：

- DSH approval；
- Server-side fixed actor；
- persistent operation receipt；
- ingest/deliver 数量与路径限制；
- 隔离 live test data；
- G5 前保留 DeerFlow fallback。
