# DeepSeek Harness Migration Cleanup and Rollback Plan

## 1. 原则

- 测试数据与用户正式数据分目录、分数据库或使用唯一 user/paper 前缀。
- G5 前清理 DSH 不得删除 DeerFlow fallback。
- 清理 Runtime/Session/Artifact 不得连带删除 Paper RAG 主数据。
- 任何真实外部写入都必须先记录数据目录、paper id、artifact id 和清理责任人。
- 不把 `.credentials.yaml`、Session JSONL、真实 PDF 或生成文件提交到 Git。

## 2. 目录分类

| 目录 | 类型 | 默认处理 |
|---|---|---|
| `data/runtime/deepseek-harness/` | 可重建运行时、profile、session、settings | 测试后可删；credentials 单独处理 |
| `data/artifacts/` | 可重建交付物 | 按 artifact manifest 清理 |
| `data/imports/` | 用户输入 PDF | 测试 fixture 可删；用户文件需确认 |
| `data/index/` | Paper RAG 主数据 | 不随 DSH 清理 |
| Qdrant volume | Paper RAG 主数据 | 不随 DSH 清理 |
| 临时测试目录 | 测试隔离数据 | 每次 suite 自动删除 |

## 3. Deterministic Test Cleanup

- Pytest 使用 `tmp_path` 或临时环境变量覆盖：
  - SQLite path
  - feedback/proactive DB path
  - artifact root
  - import root
  - DSH session root
- Qdrant 测试使用 in-memory/fake client 或唯一临时 collection。
- Vitest 使用临时 `DSH_HOME` 和 fixture MCP child。
- 测试结束必须：
  - 关闭 MCP child；
  - 停止 Web Server；
  - 等待 reconnect timer 清理；
  - 删除 temp profile/session/artifact；
  - 断言无悬空进程或端口。

## 4. Live G1 Cleanup

G1 只允许真实模型读取现有测试论文：

- 不执行 ingest。
- 不生成长期 artifact。
- DSH Session 放在专用目录：

```text
data/runtime/deepseek-harness/sessions/g1-acceptance-<timestamp>/
```

验收完成后可保留报告所需的脱敏 Session 摘要；原始 Session 只在本地保存，不入库。

## 5. Live G2 Cleanup

执行前记录：

```text
run_id
test actor_id
test data root
paper ids
discovery run ids
candidate ids
artifact ids
Qdrant collection
authorization
```

推荐使用隔离配置：

```text
TEST_ROOT=<absolute temp or dedicated root>
PAPER_RAG_ACTOR_ID=dsh-test-<timestamp>
PAPER_RAG_CONFIG=<TEST_ROOT>/config.yaml
FEEDBACK_SQLITE_PATH=<TEST_ROOT>/index/feedback.sqlite
PAPER_RAG_ARTIFACT_ROOT=<TEST_ROOT>/artifacts
PAPER_RAG_IMPORT_ROOT=<TEST_ROOT>/imports
```

`config.yaml` 必须是完整配置，并至少覆盖：

```yaml
paths:
  data_root: <TEST_ROOT>
  papers_dir: <TEST_ROOT>/papers
  parsed_dir: <TEST_ROOT>/parsed
  index_dir: <TEST_ROOT>/index
  sqlite_path: <TEST_ROOT>/index/papers.sqlite
  bm25_path: <TEST_ROOT>/index/bm25.pkl
  models_dir: <shared read-only model cache or TEST_ROOT>/models
qdrant:
  url: ""
  local_path: <TEST_ROOT>/index/qdrant
  collection_chunks: paper_chunks_<RUN_ID>
  collection_wiki: wiki_entries_<RUN_ID>
```

不得使用不存在的 `PAPER_RAG_DATA_DIR`。Live runner 在启动前调用 doctor，doctor 同时解析
测试配置和默认本地配置；以下任意对象相同或位于主数据 root 下时 fail closed：

- `data_root/papers_dir/parsed_dir/index_dir/sqlite_path/bm25_path`
- feedback SQLite
- Qdrant local path
- Qdrant chunk/wiki collection names
- artifact/import roots

doctor report 必须把 resolved paths/collections 和 comparison 结果写入 Gate report，但不
写 secret。

清理顺序：

1. 停止 DSH 和 MCP child。
2. 删除该 run 的 artifact 目录。
3. 删除测试 DSH Session。
4. 删除整个独立 TEST_ROOT；若使用远程 Qdrant，则仅删除本次唯一 collection。
5. Live runner 若发现共享主数据配置，必须在任何网络/写调用前退出；“误用共享数据后再
   清理”不是正常回退路径。
6. 运行主配置 status/list 并比较 pre/post fingerprint，确认正式数据未变化。

## 6. Artifact Cleanup

- 仅删除 manifest `created_at` 超过 retention 的 artifact 目录。
- 删除前验证目录 resolve 后位于 artifact root。
- 缺失/损坏 manifest 默认跳过并报警，不递归删除未知目录。
- 清理报告记录：
  - scanned
  - deleted
  - skipped
  - bytes reclaimed
  - errors

## 7. Runtime Reset

`make dsh-clean-runtime` 只能删除：

- 指定 `versions/<exact-dsh-version>/` 下的 profile dependencies
- generated preset copies
- DSH sessions
- transient settings/cache

默认不得删除：

- `.credentials.yaml`
- `data/runtime/deepseek-harness/credentials/`
- `data/index`
- Qdrant volume
- `data/imports`
- `data/artifacts`

若需要删除 credential，必须使用单独显式命令或人工操作。

## 8. Gate Rollback

### G0

删除 `integrations/deepseek-harness` spike 产物和临时 `DSH_HOME`。无主数据变化。

### G1

- 停止 DSH。
- README/Makefile 仍指向 DeerFlow，无需入口切换。
- MCP optional extra 可保留，不影响 Core。

### G2

- 将 `PAPER_RAG_MCP_TOOLSET` 降回 `readonly`。
- 禁用 native session bridge 和 presentation plugin。
- 清理测试 artifact。
- DeerFlow 继续作为默认入口。

### G3

- 将 toolset 降回 `research`。
- cron sidecar 保持原状。
- 已有 subscription/inbox 数据不回滚；它们属于 Paper RAG 主数据。

### G4

- 恢复 README/Makefile 默认 DeerFlow。
- DSH Session 保留用于故障分析。
- 不回滚通过 DSH 正常写入的 Paper RAG 数据。

### G5

G5 是最后的代码退役：

1. 创建明确的 pre-removal commit/tag。
2. 删除 DeerFlow。
3. G5 clean checkout 和 CUT validator 通过后不再保留即时双运行 fallback。
4. 如需恢复，通过 Git revert/pre-removal tag 恢复代码，再运行旧依赖安装和 smoke。
5. Paper RAG 主数据不需要反向迁移。

## 9. DeerFlow Removal Checklist

- [ ] 无默认 Make target 调用 DeerFlow。
- [ ] 无 CI job 加载 DeerFlow。
- [ ] 无 Python test 从 DeerFlow 路径加载文件。
- [ ] 无 Docker/README/Operations 默认使用 DeerFlow。
- [ ] `deerflow` optional extra 已删除。
- [ ] LangChain 依赖若无其他用途已删除。
- [ ] `scripts/deerflow_smoke.py` 已删除。
- [ ] 历史 ADR 标记 superseded，而不是伪装成仍有效。
- [ ] `rg -i 'deer.?flow'` 的剩余命中已逐项解释。
- [ ] clean checkout 完成 DSH 安装、doctor、smoke 和 tests。

## 10. 不允许的清理方式

- 不使用 `git clean -fdx` 清理共享工作区。
- 不删除整个 `data/`。
- 不重建正式 Qdrant collection 来“恢复干净”。
- 不直接删除未知 SQLite 行。
- 不把拒绝/失败的 live test 当作可忽略残留。
- 不在 G5 前删除 DeerFlow fallback。
