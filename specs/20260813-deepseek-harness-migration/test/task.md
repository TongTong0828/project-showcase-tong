# SDT Tasks：DeepSeek Harness Migration

## 执行规则

- 本文件编排测试实施；详细断言以 [`case.md`](./case.md) 为准。
- 机器命令以 [`test-manifest.json`](./test-manifest.json) 为准。
- 每个 Gate 的 P0 用例全部通过后才能推进。
- Live 用例需要显式授权；未授权状态为 `NOT_RUN`，不能记为 PASS。
- G5 必须在 clean checkout 重新执行，不接受复用 G4 的本地结果。

## G0

- [ ] TT-001 锁定 exact DSH packages + exact compatible Cordis graph，运行 frozen install。
- [ ] TT-002 验证 loopback Web 和公开绑定阻断。
- [ ] TT-003 验证 `paper-research` Preset discovery/mount/exact tool catalog。
- [ ] TT-004 验证 Native Broker/private MCP handshake、canonical result 和模型 text projection。
- [ ] TT-005 验证 Approval 真实对象 API、exec.signal cancellation、allowed-once/reject/unavailable/mis-scope/HMR fail-closed。
- [ ] TT-006 验证 credential reference → explicit child env，并证明 dump/log/session/report 无 secret。
- [ ] TT-007 验证 Session restart/resume 和 versioned root，不重复执行历史工具。
- [ ] TT-008 验证 request boundary 的多用户消息批次、synthetic-only、user steering 和 resume。
- [ ] TT-009 冻结 quality baseline 和 65-test capability matrix。
- [ ] TT-010 验证 standing generation 双 Agent共享/切代/释放与 Host shutdown。
- [ ] TT-011 验证 Host timeout policy active、MCP crash/reconnect、timeout/cancel 和资源收敛。
- [ ] TT-012 运行统一 run-gate G0、dsh-g0-compat，并通过 current-commit report validator。

## G1

- [ ] TT-013 执行 Core Python gates。
- [ ] TT-014 执行 MCP contract/tool/security/parity tests。
- [ ] TT-015 执行 DSH typecheck/composition/Broker/approval/credential/behavior tests。
- [ ] TT-016 验证 model-visible Schema 不含 user/session authority，raw MCP tools 不可见。
- [ ] TT-017 验证 fixed single actor，且测试不误判为多租户 corpus 隔离。
- [ ] TT-018 验证 paper_status/list/search/section/wiki。
- [ ] TT-019 验证 QA 有证据/弱证据/无证据 parity。
- [ ] TT-020 验证 compare 上限和 citation paper scope。
- [ ] TT-021 验证 Agent 工具选择、abstain、citation 和 error honesty。
- [ ] TT-022 验证 hidden conversation id 来自 exec.agent.id，outer resolution 权威。
- [ ] TT-023 获得 live model 授权后执行 LIVE-001。
- [ ] TT-024 运行 migration-owned golden retrieval、QA/citation、claim、verify-p0 并生成 G1 report。

## G2

- [ ] TT-030 验证 discovery 结果为 candidate-only。
- [ ] TT-031 验证 ingest/candidate ingest/wiki generate 审批。
- [ ] TT-032 验证批量数量、source exact-one 和 force。
- [ ] TT-033 验证 import root traversal/symlink 防护。
- [ ] TT-034 验证 ingest 故障和取消后状态收敛。
- [ ] TT-035 验证 operation receipt、same-turn fingerprint、crash/unknown 防重。
- [ ] TT-036 验证 deliver 审批、artifact manifest、格式和路径。
- [ ] TT-037 验证 Session JSONL 无 Base64。
- [ ] TT-038 验证 artifact retention cleanup。
- [ ] TT-039 执行 SESSION-001..006。
- [ ] TT-040 执行完整 Discover → Confirm → Ingest → QA → Compare → Deliver fixture。
- [ ] TT-041 通过独立 YAML doctor 后，获得授权执行 LIVE-002..004。
- [ ] TT-042 通过 live report 和 Gate report validator，生成 G2 report。

## G3

- [ ] TT-050 验证 Subscription CRUD。
- [ ] TT-051 验证 Inbox list/read/dismiss。
- [ ] TT-052 验证 Feedback 脱敏、幂等和 rate limit。
- [ ] TT-053 验证 digest/stale 手动触发审批。
- [ ] TT-054 在 DSH 关闭时验证 cron independence。
- [ ] TT-055 生成 G3 report。

## G4

- [ ] TT-060 验证默认 README/Makefile/.env/CI 指向 DSH。
- [ ] TT-061 执行 clean install rehearsal。
- [ ] TT-062 执行 `.venv` Ruff、secret scan、base...HEAD diff check 和 DSH dump-config audit。
- [ ] TT-063 执行 DSH 默认入口 cutover smoke，不要求 7 天观察窗口。
- [ ] TT-064 确认 smoke 覆盖 loopback、telemetry、credential path、timeout policy 和默认 preset。
- [ ] TT-065 确认没有执行会真实写入论文库的 live smoke。
- [ ] TT-066 生成 G4 cutover report。
- [ ] TT-067 验证 G4 累计包含 G0-G3 required cases，并通过 clean checkout component。

## G5

- [ ] TT-070 删除 DeerFlow 后重跑 Core/MCP/DSH 和 migration-owned 全量质量门禁。
- [ ] TT-071 执行残留引用扫描并分类。
- [ ] TT-072 验证 65 个旧测试逐用例迁移矩阵及无 DeerFlow import/Make/CI/Docker/default docs。
- [ ] TT-073 在 clean checkout 从零安装。
- [ ] TT-074 执行 doctor/smoke。
- [ ] TT-075 执行 CUT validator 和 pre-removal tag 回滚路径。
- [ ] TT-076 验证 G4/G5 当前 commit 重新执行非历史 case，不继承观察窗口。
- [ ] TT-077 通过累计 G0-G5 required cases 和 G5 report validator，生成 final migration report。

## 报告状态

测试执行报告应使用以下状态：

- `PASS`
- `FAIL`
- `BLOCKED`
- `NOT_RUN`
- `NOT_APPLICABLE`（必须给出设计依据）

不能用“基本通过”“看起来正常”替代可审计状态。
