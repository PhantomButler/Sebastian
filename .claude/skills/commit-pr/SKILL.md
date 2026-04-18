---
name: commit-pr
description: 提交代码并创建 PR 的标准流程（GitHub Flow）。从 main 开 feature branch，lint 验证，原子提交，PR 创建，CI 监控，squash merge 后删除分支。
---

# commit-pr - 提交代码并创建 PR

基于 GitHub Flow 的标准化流程：feature branch → PR → squash merge → 删除分支。

## 使用方式

```
/commit-pr
```

仅提交不建 PR：`/commit-pr --no-pr`

## 执行步骤

### 步骤 1：确认工作分支

```bash
git branch --show-current
```

- 若在 `main`：说明还没开 feature branch，**先创建**：

  ```bash
  git pull
  git checkout -b <type>/<short-description>
  ```

  分支命名规范：`feat/xxx`、`fix/xxx`、`chore/xxx`、`docs/xxx`、`refactor/xxx`

- 若已在 feature branch：继续步骤 2。

- 若在其他非预期分支：**终止**并提示确认。

#### 1a. 确认 feature branch 基于最新 main

```bash
git fetch origin main
git log origin/main..HEAD --oneline
```

若有多个 commit 且部分已在 main（`git cherry origin/main HEAD` 显示 `-` 前缀），说明 base 不干净，**暂停**提示用户确认后再 rebase：

```bash
git rebase origin/main
```

### 步骤 2：检查工作区状态

```bash
git status
git diff --stat
```

若没有可提交的改动，**终止**并提示。

展示改动摘要，让用户确认哪些文件需要提交。

### 步骤 3：危险文件检查

扫描改动文件，**拒绝**以下文件进入提交：

- `.env`、`*.key`、`credentials.*`、`secret.*` — 密钥/凭证
- `*.bak.*`、`.sebastian.bak.*` — 备份目录
- `node_modules/`、`.venv/`、`__pycache__/` — 依赖/缓存
- `*.pyc`、`.DS_Store` — 系统/编译产物

若发现上述文件在 untracked 中，**警告**用户并建议加入 `.gitignore`。

### 步骤 4：Lint 与格式化

后端改动：

```bash
ruff check sebastian/ tests/
ruff format --check sebastian/ tests/
```

若格式不对，自动修复：

```bash
ruff format sebastian/ tests/
```

前端改动（`ui/mobile-android/` 下有改动时跳过，Kotlin lint 由 CI 验证）。

**Lint 不过不允许提交。**

### 步骤 5：运行测试

后端改动时：

```bash
pytest tests/unit/ -x -q
```

测试失败则**终止**，提示修复。

### 步骤 6：构建 commit

逐文件添加（**严禁** `git add .` 或 `git add -A`）：

```bash
git add <file1> <file2> ...
```

commit message 格式：`类型(范围): 中文摘要`

- 类型：`feat` / `fix` / `docs` / `refactor` / `chore` / `test` / `style` / `ci`
- 可在类型前加 emoji（参考 git log 现有风格）
- 一个 commit 只做一件事，保持原子化
- 末尾附 `Co-Authored-By: Claude <noreply@anthropic.com>`（或当前实际模型）

若改动涉及多个不相关主题，拆分为多个 commit。

### 步骤 7：推送

首次推送 feature branch：

```bash
git push -u origin HEAD
```

后续追加 commit：

```bash
git push
```

### 步骤 8：创建 PR（除非 `--no-pr`）

创建前确认 feature branch 领先 main 的 commit 数量合理：

```bash
git log origin/main..HEAD --oneline
```

若 commit 数量异常多（>10），**暂停**提示用户确认。

确认无误后创建 PR：

```bash
gh pr create --base main --title "{title}" --body "$(cat <<'EOF'
## Summary
{1-3 条要点}

## Test plan
{验证步骤 checklist}

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

PR 规范：
- title 与 commit message 风格一致，控制在 70 字以内
- base 永远是 `main`
- Summary 写改了什么、为什么改
- Test plan 写验证步骤 checklist

### 步骤 9：输出结果

```
✓ 已提交并推送到 <branch-name>

Commits:
{commit list}

PR: {pr_url}
```

### 步骤 10：监控 CI

PR 创建后立即开始监控 CI：

```bash
gh run list --branch <branch-name> --limit 5
gh run watch <run-id>
```

每隔约 30s 检查一次，直到所有 job 完成：

```bash
gh pr checks <pr-number>
```

**若 CI 全绿**：跳到步骤 12。

**若 CI 失败**：进入步骤 11。

### 步骤 11：处理 CI 失败

先读取失败日志判断问题性质：

```bash
gh run view <run-id> --log-failed
```

#### 小问题（直接修复，无需询问）

判断标准：lint/format 错误、import 排序、未使用变量、测试因代码实现与测试期望的细节不一致（非逻辑错误）。

处理方式：
1. 本地修复
2. 提交新 commit 到 feature branch（同样遵循步骤 4-7 的 lint + commit 规范）
3. push 后 CI 自动重新触发，回到步骤 10 继续监控

#### 大问题（先询问用户意见）

判断标准：逻辑回归、核心功能测试失败、类型错误涉及接口变更、CI 配置本身有问题、影响范围不明确。

处理方式：
1. 向用户展示失败摘要和自己的判断
2. 提出 1-2 个修复方案，说明各自影响
3. 等待用户选择后再动手

### 步骤 12：等待 Approve 并 Squash Merge

CI 全绿后，等待用户 approve（或用户明确授权后直接合并）。

确认可以合并后执行：

```bash
gh pr merge <pr-number> --squash --delete-branch
```

等待合并完成：

```bash
gh pr view <pr-number> --json state -q .state   # 确认 MERGED
```

### 步骤 13：合并后回到 main

Feature branch 已被删除，切回 main 拉取最新：

```bash
git checkout main
git pull
git branch -d <branch-name>   # 删除本地 feature branch
```

完成后输出：

```
✓ PR #{pr-number} 已 squash merge 到 main
✓ 已切回 main，当前为最新（{short-sha}）
```

## 常见问题

### PR 包含了不相关的 commit

原因：feature branch 开分支时 base 不是最新 main。

修复：`git rebase origin/main` 整理后 force push。

### CHANGELOG 冲突

原因：release workflow 修改了 main 上的 CHANGELOG，而 feature branch 上也有改动。

处理：`git rebase origin/main` 手动解决冲突，保留两者内容后 force push。
