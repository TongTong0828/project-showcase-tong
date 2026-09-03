# DeepSeek Harness Migration Test Manifest

本清单绑定 [`case.md`](./case.md) 与
[`test-manifest.json`](./test-manifest.json)。命令是目标状态；在对应实现任务完成前，
允许以 `pending` 记录，但不得用尚不存在的命令作为通过证据。

每个 Gate 的机器入口只有：

```text
.venv/bin/python scripts/migration_gate.py run-gate ...
.venv/bin/python scripts/migration_gate.py validate-report ...
```

下表的 Core/MCP/DSH 命令是 orchestrator 内部 component commands，不由人工跳着执行后
拼报告。

## 1. Core Gates

| 命令 ID | 命令 | 覆盖 |
|---|---|---|
| `python-lint` | `.venv/bin/python -m ruff check --select E,F,W,I --ignore E501 src tests` | Python 静态规则 |
| `python-core` | `PYTHONPATH=src:tests .venv/bin/python -m pytest -q ...` | 现有领域核心回归 |
| `python-smoke` | `PYTHONPATH=src .venv/bin/python scripts/_run_smoke.py` | Core import |
| `secret-scan` | `.venv/bin/python scripts/secret_scan.py` | 凭证泄漏 |
| `diff-check` | `.venv/bin/python scripts/migration_gate.py diff-check --base-env MIGRATION_GATE_BASE --head HEAD` | Gate commit 范围的 patch hygiene |
| `eval-golden` | migration-owned `make eval-golden PY=.venv/bin/python` | strict retrieval gate |
| `eval-golden-qa` | migration-owned `make eval-golden-qa PY=.venv/bin/python` | QA / abstain / citation gate |
| `eval-citation-audit` | migration-owned citation audit | citation trace |
| `eval-claims` | migration-owned claim gate | grounded claim coverage |
| `verify-p0` | migration-owned focused P0 | abstain/rewrite/evidence/chaos/smoke |
| `quality-baseline-{freeze,validate}` | `scripts/migration_gate.py` | dataset/gate/result/test-count 基线 |
| `legacy-capability-matrix` | `scripts/migration_gate.py validate-legacy-matrix` | 65 个旧测试逐用例迁移 |

## 2. MCP Gates

| 命令 ID | 目标命令 | 覆盖 |
|---|---|---|
| `mcp-contract` | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_contract.py` | tools/list、Schema、result envelope、error、stdout purity |
| `mcp-tools` | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_tools.py` | 只读/写入/主动工具 facade |
| `mcp-security` | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_security.py` | identity、path、limits、secret、prompt injection |
| `mcp-artifacts` | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_artifacts.py` | artifact manifest/path/cleanup/Base64 禁止 |
| `mcp-operations` | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_mcp_operations.py` | operation receipt、重复调用、crash/unknown |
| `mcp-parity` | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_dsh_parity.py` | direct Python vs MCP 领域等价 |

## 3. DSH Deterministic Gates

在 `integrations/deepseek-harness/` 执行：

| 命令 ID | 目标命令 | 覆盖 |
|---|---|---|
| `dsh-install` | `pnpm install --frozen-lockfile` | exact dependency graph |
| `dsh-typecheck` | `pnpm typecheck` | Cordis/DSH plugin types |
| `dsh-test` | `pnpm test` | composition、policy、session bridge、behavior fixtures |
| `dsh-dump-config` | `pnpm dsh:dump-config` | 最终 composition 与工具面 |
| `dsh-smoke` | `pnpm smoke` | Web/Preset/MCP/tool discovery/read-only call |
| `dsh-g0-compat` | `pnpm g0:compat --report ../../data/index/migration-gates/components/G0/dsh-g0-compat.json` | 真实 Host/Web/Broker/private MCP/credential/approval/session/reconnect/cancel |
| `gate-report-g*` | `.venv/bin/python scripts/migration_gate.py validate-report ...` | commit/version/config/case/授权/evidence |
| `live-report-g*` | `scripts/migration_gate.py validate-live` | live runner 报告存在、有效、隔离、未过期 |
| `cut-validator` | `scripts/migration_gate.py validate-cutover` | CUT cases + 残留 + 旧能力矩阵 |
| `clean-checkout` | `scripts/deepseek_harness_clean_checkout_gate.sh` | 从零安装和启动 |

## 4. Gate Mapping

### G0

必需：

- `dsh-install`
- `dsh-typecheck`
- `dsh-test`
- `dsh-dump-config`
- `dsh-smoke`
- `dsh-g0-compat`
- `quality-baseline-freeze`
- `legacy-capability-matrix`
- `gate-report-g0`
- `DSH-G0-001..009` 必须全部 PASS，不允许将 P1 延后

### G1

必需：

- Core Gates 全部
- migration-owned retrieval/QA-citation/claim/P0 gates
- MCP Gates 全部（写入/Artifact 未实现部分可被精确跳过，不得整文件 skip）
- DSH deterministic gates 全部
- `LIVE-001`
- `live-report-g1` 与 `gate-report-g1`

### G2

必需：

- G1 全部
- 写入、Artifact、Session Bridge 适用用例
- `LIVE-002`、`LIVE-003`、`LIVE-004`
- 完整隔离 YAML doctor evidence
- `live-report-g2` 与 `gate-report-g2`

### G3

必需：

- Proactive/Feedback 现有单测
- `PRO-001..005`
- cron independence

### G4

必需：

- G3 全部
- `cutover-defaults`
- clean install rehearsal
- `dsh-smoke` 作为默认入口 cutover smoke
- `gate-report-g4`

### G5

必需：

- DeerFlow 删除后重新运行所有非历史 Gate
- `CUT-001..006`
- retrieval/QA-citation/claim/P0 全部质量门禁
- 65 个旧测试逐用例迁移矩阵
- `cut-validator`
- `rg` 残留分类报告
- clean checkout
- `gate-report-g5`

机器清单通过 `inherits_required_cases` 累计前置 Gate；G4/G5 不能只检查本 Gate 新增
case。G5 当前 commit 重新执行所有非历史 case。

## 5. Live 测试授权边界

以下动作有外部副作用，执行前需要单独授权：

- 调用真实 DeepSeek/其他模型。
- 搜索 arXiv/Semantic Scholar。
- 下载并入库论文。
- 生成长期保留 artifact。
- 运行 digest/stale 并写 Inbox。

默认 deterministic 测试使用 fixture/mock；没有授权时不能把 live case 标记为通过。

## 6. 证据格式

每个 Gate 报告至少记录：

```text
gate
commit
DSH exact versions
Python version
Node version
commands and exit codes
test counts
skipped cases and reason
live authorization
data directory
known failures
go/no-go
```

报告必须绑定 clean commit、exact DSH/Cordis/Python/Node versions、resolved config/data
fingerprints 和 case id。LIVE-001..004 默认 24 小时有效。缺失、过期、commit/config
不匹配或累计 required case 非 PASS 时 validator 必须失败。
