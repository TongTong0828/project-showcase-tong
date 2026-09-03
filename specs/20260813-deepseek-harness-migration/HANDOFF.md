# AI Development Handoff

本文是 DeepSeek Harness 迁移的可移植开发入口。不要假设当前工作目录、用户名或 checkout
绝对路径。

## 1. 定位仓库

如果当前目录位于仓库或其子目录：

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
```

如果命令失败，必须由调用方提供 Paper RAG checkout 路径。不要猜测
`/Users/.../paper-rag-agent`，也不要在当前陌生目录新建另一个同名项目。

确认仓库身份：

```bash
test -f "$REPO_ROOT/pyproject.toml"
test -d "$REPO_ROOT/src/paper_rag"
test -f "$REPO_ROOT/specs/20260813-deepseek-harness-migration/spec.md"
git -C "$REPO_ROOT" status --short --branch
```

任一检查失败时停止，不执行实现或清理操作。

## 2. 权威文件

所有路径都相对于 `$REPO_ROOT`：

```text
specs/20260813-deepseek-harness-migration/README.md
specs/20260813-deepseek-harness-migration/spec.md
specs/20260813-deepseek-harness-migration/plan.md
specs/20260813-deepseek-harness-migration/database-change-plan.md
specs/20260813-deepseek-harness-migration/tasks.md
specs/20260813-deepseek-harness-migration/test/case.md
specs/20260813-deepseek-harness-migration/test/task.md
specs/20260813-deepseek-harness-migration/test/manifest.md
specs/20260813-deepseek-harness-migration/test/test-manifest.json
specs/20260813-deepseek-harness-migration/test/cleanup-plan.md
```

优先级：

```text
spec.md
-> plan.md + database-change-plan.md
-> tasks.md
-> test/case.md + test/test-manifest.json
-> research.md
```

`research.md` 是证据和历史判断，不得覆盖已批准的 SPEC/SDD。

## 3. 代码真值

实现每项任务前读取当前 checkout 的对应代码，不使用旧会话中的绝对路径或代码摘要：

```text
src/paper_rag/
tests/
pyproject.toml
Makefile
.github/workflows/ci.yml
integrations/deer-flow/
```

还要读取目标文件作用域内的 `AGENTS.md`。不同 worktree、branch 或 commit 的实现可能不同。

## 4. 执行位置

命令可以从任意 cwd 发起，但必须显式指定工作目录：

```bash
git -C "$REPO_ROOT" status --short --branch
make -C "$REPO_ROOT" <target>
```

需要进入子项目的命令使用：

```bash
pnpm --dir "$REPO_ROOT/integrations/deepseek-harness" <command>
```

脚本中的运行时目录必须由 repo root 或显式配置解析，不能由启动时 `pwd` 偶然决定。

## 5. 当前起点

规格状态为 `Approved for G0`，但正式 Gate 开始前必须：

1. 将规格文件提交到目标 branch。
2. 确保目标 checkout clean。
3. 完成 `tasks.md` 的 T007。
4. 从 T008 开始执行 G0，不跳到 G1。

G0–G5 的实际状态以 `README.md` Gate Ledger 和 Gate report 为准。

## 6. 外部 DeepSeek Harness 源码

不要依赖 `/tmp/deepseek-harness-eval` 必然存在。G0 应按批准的 exact version 获取官方包
或源码，并记录：

```text
source URL
version
commit or package integrity
local cache path
```

临时源码目录只是调研缓存，不是项目依赖或权威入口。

## 7. 禁止事项

- 不硬编码开发者机器绝对路径。
- 不因 cwd 不正确而在陌生目录创建新项目。
- 不在规格提交前开始正式 G0。
- 不跳过 Gate。
- 不在 G5 前删除 `integrations/deer-flow/`。
- 不把临时源码缓存、credential、Session 或测试数据提交到仓库。
