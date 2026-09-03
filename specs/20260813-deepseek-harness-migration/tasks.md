# DeepSeek Harness Migration Tasks

## 执行规则

- 按 Gate 顺序执行，后续 Gate 不得绕过前置 Gate。
- 每个 Gate 先补失败测试，再实现，再运行该 Gate 清单。
- G5 前不得删除 `integrations/deer-flow/`。
- 未获得用户明确批准，不执行写入真实论文库的 live smoke。
- DSH 版本升级不与功能迁移混在同一任务。

## 0. 规格与审批

- [x] T001 调研现有 Paper RAG、DeerFlow 耦合面和测试基线。
- [x] T002 调研 DeepSeek Harness Agent、Preset、MCP、Session、权限和 Web 安全边界。
- [x] T003 编写 SPEC、SDD、任务、SDT 用例、manifest 和 cleanup plan。
- [x] T004 评审并批准 `spec.md` 的产品范围（独立复审通过，无 P0/P1）。
- [x] T005 评审并批准 `plan.md` 的架构、身份、会话、权限和退役门禁（Native Broker 方案复审通过）。
- [x] T006 评审并批准 `test/` 下的 SDT 与机器清单（42 命令、67 cases、累计 Gate 模型对账通过）。
- [x] T007 创建 ADR-0022，声明 DSH + MCP 新边界，并将 ADR-0008/0015/0020/0021 的宿主决策标记为待 supersede。

## 1. G0 · Compatibility Spike

- [ ] T008 冻结当前 golden retrieval、QA/citation、claim、verify-p0 基线及 dataset/gate/result fingerprints。
- [x] T009 对 Gateway 17、Gateway middleware 25、LangGraph middleware 23 个测试逐用例建立迁移矩阵。
- [x] T010 选择同一 exact DSH version 的全部直接 DSH 包，以及其 dependency graph 验证过的 exact compatible Cordis/vendor 版本。
- [ ] T011 将 `eval-golden*`、`eval-citation-audit`、`eval-claims*`、`eval-llm-recall` 和 `verify-p0` 从 `DEERFLOW_BACKEND_PY` 迁移为 `$(PY)`/migration-owned `.venv`，再冻结 baseline。
- [x] T012 在 `integrations/deepseek-harness/package.json` exact-pin 版本并生成 lockfile。
- [x] T013 建立 repo-local versioned `DSH_HOME` 与独立 credential provider path，加入 `.gitignore`。
- [x] T014 建立最小 Web profile，默认 loopback、telemetry disabled，并断言 Host timeout policy active。
- [x] T015 建立 `paper-research` Preset 源和同步脚本，验证 UI 可选择该 Preset。
- [x] T016 建立 Native Broker + 私有 stdio MCP fixture，验证 raw tools 不进入模型目录。
- [x] T017 实现 credential reference bridge，验证显式 child env、热轮换和 secret redaction。
- [x] T018 写工具 executor 按真实对象签名直接调用一次性 Approval 并传 `exec.signal`；验证 missing/mis-scope/HMR 全部 fail closed。
- [x] T019 拆分 `INHERITED_GLOBAL_ALLOW` 与 `FINAL_MODEL_CATALOG`，验证 agent-created restrict 与 pre-step schema invariant。
- [x] T020 实现 direct-human request boundary state，覆盖多消息批次、synthetic-only、user steering、resume。
- [x] T021 验证 MCP child crash/reconnect、same-version Session resume、versioned root、standing generation 多 Agent 生命周期和 cancellation。
- [x] T022 实现统一 `run-gate` orchestrator、`dsh-g0-compat` 与结构化 report validator。
- [x] T024 固定 hidden wire 为 `tools/call.params._meta.paper_rag`，验证 TS 发送/Python 接收且不落 Session。
- [x] T025 将 Host timeout policy active 纳入 profile、doctor、dump-config 和 G0 fail-closed。
- [ ] T023 只有 001..009 全 PASS、baseline/matrix/report validator 全通过才进入 G1。

## 2. G1 · Python MCP Foundation

- [ ] T030 在 `pyproject.toml` 增加经 G0 验证的 `harness` optional extra。
- [ ] T031 新增 `src/paper_rag/mcp/__main__.py` 和 stdio Server 生命周期。
- [ ] T032 新增 MCP registry，按 `readonly/research/full` 注册工具。
- [ ] T033 新增稳定 result envelope 和 error code 映射。
- [ ] T034 新增 server config：single actor、artifact root、import root、toolset。
- [ ] T035 实现 fixed `actor_id=system`（可部署时显式覆盖为一个 local actor），拒绝模型参数覆盖。
- [ ] T036 新增 framework-neutral runtime status service。
- [ ] T037 新增 framework-neutral visible paper list service。
- [ ] T038 为 MCP tool list、Schema、outputSchema、错误和关闭行为写契约测试。
- [ ] T039 确认 core import 不要求 MCP optional dependency。
- [ ] T059 新增 `mcp_operation_receipts` additive migration 和原子 receipt API。

## 3. G1 · Read-only Tools

- [ ] T040 暴露 `paper_status`。
- [ ] T041 暴露 `paper_list`。
- [ ] T042 暴露 `paper_search`。
- [ ] T043 暴露 `paper_qa`，不暴露 user/session policy 字段。
- [ ] T044 暴露 `paper_section`。
- [ ] T045 暴露 bounded `paper_compare`，把可信 actor context 映射到每个 QA 子调用。
- [ ] T046 暴露 `wiki_lookup`。
- [ ] T047 Broker 对 canonical result 做 bounded text projection，确保模型可见 ok/error/abstain/citations/evidence_role/trace/truncated。
- [ ] T048 为每个工具补 validation/not-found/unavailable 测试。
- [ ] T049 为 Qdrant down、LLM down、reranker degrade 保留现有 graceful behavior。

## 4. G1 · DSH Preset、Skill 与策略

- [ ] T050 新增 `.dsh/skills/paper-research/SKILL.md`。
- [ ] T051 编写短 Persona，完整领域规则放 Skill。
- [ ] T052 Preset 只挂载 Skill、Ask User、Compaction 和 Paper RAG Native Broker。
- [ ] T053 默认不挂载 Bash、FS write、Code Mode、Workflow、Ralph、generic subagent。
- [ ] T054 对继承工具应用 exact allowlist，并断言模型目录完整相等。
- [ ] T055 Skill 强制 follow-up self-contained question。
- [ ] T056 Skill 强制 abstain/citation/discovery evidence 规则。
- [ ] T057 新增 DSH composition/Broker/Approval/credential deterministic tests。
- [ ] T058 新增 start、doctor、smoke、g0-compat 和 Gate report validator。

## 5. G1 · Parity 与行为验收

- [ ] T060 选择固定 QA parity fixture，覆盖有证据、弱证据、无证据和 follow-up。
- [ ] T061 比较直接 Python 与 MCP 的 citations、abstain、trace 和 effective question。
- [ ] T062 验证 DSH Agent 对论文内容选择 `paper_qa`。
- [ ] T063 验证指定章节选择 `paper_section`。
- [ ] T064 验证 no-evidence 后 Agent 不用 Web/Memory 补造答案。
- [ ] T065 验证 Agent 不生成工具未返回的 citation。
- [ ] T066 验证 DSH Session 恢复后 follow-up 仍是 self-contained question。
- [ ] T067 验证 hidden conversation id 来自 `exec.agent.id`，Broker 强制 outer resolution，无双重 rewrite。
- [ ] T068 运行冻结 baseline 对账、核心/MCP/DSH tests、golden retrieval、QA/citation、claim、verify-p0 和 live smoke。
- [ ] T069 产出 G1 report；DeerFlow 仍为默认入口。

## 6. G2 · Discovery 与写入工具

- [ ] T070 暴露 `paper_discover`，固定 evidence_role 为 discovery-only。
- [ ] T071 暴露 `discovery_run_get`，避免用户必须依赖一次性长结果。
- [ ] T072 暴露 `paper_ingest`，执行 exact-one source 校验。
- [ ] T073 暴露 `discovery_candidate_ingest`。
- [ ] T074 暴露 `wiki_generate`。
- [ ] T075 Broker 写工具 executor 直接 request Approval，只有 allowed-once 调用私有 MCP。
- [ ] T076 审批消息展示论文数量、来源、force、写入范围和预计外部调用。
- [ ] T077 一次候选批量入库最多 5 篇。
- [ ] T078 `pdf_path` 只允许 import root，覆盖 traversal 和 symlink escape。
- [ ] T079 验证拒绝审批时 SQLite/Qdrant/文件系统没有变化。
- [ ] T080 验证 ingest 取消/超时后状态最终收敛到 done/failed，而不是半状态。
- [ ] T081 为所有写工具接入 hidden operation id、receipt、same-turn fingerprint 和 outcome-unknown 防重。

## 7. G2 · Deliverable 与 Artifact

- [ ] T090 暴露 `export_bibtex`。
- [ ] T091 暴露 `paper_deliver`，限制格式和论文数量。
- [ ] T092 新增 artifact store，使用 UUID 目录和原子文件写入。
- [ ] T093 生成 manifest：mime、size、sha256、paper ids、trace、created_at。
- [ ] T094 MCP 返回 locator，不返回 Base64。
- [ ] T095 Broker 对 deliver 直接请求 Approval，并展示格式、标题、论文范围和输出目录。
- [ ] T096 增加 artifact Tool Card 或采用 DSH 现有 deliverable presentation。
- [ ] T097 补 artifact path、filename sanitization、partial file、cleanup 测试。
- [ ] T098 新增 30 天 artifact cleanup CLI。

## 8. G1/G2 · Session 与版本分代

- [ ] T100 model-visible Schema 不含 `conversation_id`，Broker 从 `exec.agent.id` 注入可信 metadata。
- [ ] T101 Broker 总是提供 outer `resolved_question`，Python 跳过内部 rewrite。
- [ ] T102 验证两个 DSH Session 之间 research memory 不串线。
- [ ] T103 定义并测试 Session fork identity 策略。
- [ ] T104 Session root 按 exact DSH version 分代，credential provider 独立。
- [ ] T105 用真实上一版本 Session fixture 验证升级；不兼容时保留旧 binary/root 读取策略。
- [ ] T106 验证新版本不写旧 root，回退恢复旧 lockfile/binary/root。

## 9. G2 · 完整研究行为

- [ ] T110 验证 Discover → candidate presentation → user confirm → ingest。
- [ ] T111 验证 discovery snippet 从未成为 final citation。
- [ ] T112 验证入库成功后才可用 `paper_qa` 引用。
- [ ] T113 验证 compare 最大 4 papers × 4 dimensions。
- [ ] T114 验证 deliver 前复述请求并经过审批。
- [ ] T115 验证同 turn fingerprint deny 和跨 crash/reconnect/resume operation receipt 防重。
- [ ] T116 验证 Tool error 时 Agent 不宣称成功。
- [ ] T117 运行 G2 SDT 并产出 full research workflow report。

## 10. G3 · Proactive、Inbox 与 Feedback

- [ ] T120 暴露 subscription list/add/toggle/delete。
- [ ] T121 暴露 inbox list/read/dismiss。
- [ ] T122 暴露 feedback record，沿用现有脱敏和 rate limit。
- [ ] T123 暴露 digest/stale 手动触发并走审批。
- [ ] T124 保持 `paper_rag.proactive.cron_runner` 独立，不迁到 DSH Goal/Ralph。
- [ ] T125 验证 DSH 关闭时 cron 仍能写 Inbox。
- [ ] T126 验证固定 actor 的 proactive/feedback 状态归属，并确认论文检索仍按 shared corpus 运行。
- [ ] T127 更新 Skill 中 Chat-first 管理示例。
- [ ] T128 运行 G3 SDT。

## 11. G4 · 默认入口切换

- [ ] T130 新增 `dsh-install/doctor/start/smoke/test/clean-runtime` Make targets。
- [ ] T131 根 README/README_ZH 默认 Quick Start 改为 DSH。
- [ ] T132 更新 `.env.example` 与 Docker/运行说明。
- [ ] T133 更新 `docs/ARCHITECTURE.md`、`SYSTEM_DESIGN.md`、`OPERATIONS.md`。
- [ ] T134 更新 `docs/STATUS.md` 与 `docs/README.md`。
- [ ] T135 更新课程与 troubleshooting 中默认入口。
- [ ] T136 CI 新增 MCP 和 DSH job；核心 Python matrix 保持独立。
- [ ] T137 DeerFlow 文档标记 legacy fallback，冻结 DeerFlow-only 新功能。
- [ ] T138 DSH 默认入口通过 `dsh-smoke` cutover gate，不要求 7 天观察窗口。
- [ ] T139 确认 cutover smoke 覆盖 loopback、telemetry、credential path、timeout policy 和默认 preset。
- [ ] T140 产出 G4 cutover report 并决定是否进入 G5。

## 12. G5 · 旧宿主退役

- [x] T150 冻结并保存退役前功能矩阵和最后一份回滚 tag/commit。
- [x] T151 删除 `integrations/deer-flow/`。
- [x] T152 删除 `scripts/deerflow_smoke.py`。
- [x] T153 仅在 65 个旧测试逐用例完成 host-delete/replaced/moved 分类且替代 evidence 通过后删除旧测试。
- [x] T154 从 `pyproject.toml` 删除 `deerflow` extra 和仅供其使用的 LangChain 依赖。
- [x] T155 删除 DeerFlow Make targets、环境变量和 Docker 注释。
- [x] T156 删除或改写运行文档中的 DeerFlow 默认路径。
- [x] T157 新增 ADR-0022 final 状态，将 0008/0015/0020/0021 标记 superseded。
- [x] T158 更新 `docs/README.md` ADR 索引和文档地图。
- [x] T159 运行 `rg -i 'deer.?flow'`，逐项分类为历史记录或残留运行引用。
- [x] T160 运行 migration-owned retrieval、QA/citation、claim、verify-p0、core/MCP/DSH、CUT、secret scan、diff hygiene。
- [x] T161 验证 clean checkout 从零安装和启动。
- [x] T162 更新 `specs/INDEX.md` 状态为 Completed。

## 13. 最终 DoD

- [x] 所有 P0/P1 SDT 通过。
- [x] 没有 DeerFlow 运行依赖。
- [x] 没有 model-visible user/session authority 字段。
- [x] 没有 Base64 deliverable 写入 Session。
- [x] Abstain、citation 和 query resolution 对比无退化。
- [ ] DSH 默认 loopback、telemetry disabled、native tools mode。
- [ ] 文档、代码、测试和实际启动方式一致。
