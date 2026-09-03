# Specs Index

本目录保存跨子系统、需要分阶段交付和独立验收的 SDD/SDT 规格包。

| Spec | 状态 | 目标 |
|---|---|---|
| [`20260813-deepseek-harness-migration/`](./20260813-deepseek-harness-migration/) | Completed | DeepSeek Harness Agent Runtime 迁移，以 Native Broker + 私有 MCP 连接现有 `paper_rag` Python 内核，完成 Chat-first 本地研究助手切换 |

状态约定：

- `Proposed`：规格已形成，尚未批准实施。
- `Approved for G0`：SPEC/SDD/SDT 已批准；提交规格并获得 clean workspace 后可开始兼容性 Gate。
- `In Progress`：设计与测试计划已批准，正在实现。
- `Cutover Candidate`：新入口已成为候选默认入口，但旧宿主尚未删除。
- `Completed`：切换门禁通过，旧宿主已退役，文档完成收口。
