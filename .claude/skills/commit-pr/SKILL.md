---
name: commit-pr
description: 提交代码并创建 PR 的标准流程。包含 rebase 检查、lint 验证、原子提交、PR 创建，防止重复 commit 和冲突。
---

# commit-pr - 提交代码并创建 PR

标准化从提交到 PR 的完整流程，确保 dev 与 main 同步、提交干净、CI 能过。

## 使用方式

```
/commit-pr
```

仅提交不建 PR：`/commit-pr --no-pr`

## 执行步骤

### 步骤 1：分支与同步检查

确认当前在 `dev` 分支：

```bash
git branch --show-current
```

若不在 `dev`，**终止**并提示切换。

**这一步不可跳过。** 这是防止 PR 包含已合并 commit 的关键。

#### 1a. Fetch 并检测已合并旧 commit

```bash
git fetch origin main
git log origin/main..HEAD --oneline   # dev 领先 main 的 commit
```

若 dev 领先 main 有旧 commit（即上次 PR squash merge 后 dev 没有同步回 main），需要特殊处理。

**判断方法**：dev 领先的 commit 不为空，且这些 commit 的内容已被 main 上的 squash merge 包含。典型特征：这些 commit message 与上次已合并 PR 的 commit 一致。

#### 1b. 同步策略（二选一）

**情况 A — dev 没有领先 main 的旧 commit**（干净状态）：

直接 rebase：

```bash
git rebase origin/main
```

**情况 B — dev 有已合并的旧 commit**（上次 PR 合并后未同步）：

此时 `git rebase` 可能因 squash merge 与原始 commit 的文本差异产生无意义冲突。正确做法是先保护新改动，然后将 dev 直接对齐 main：

```bash
# 1. 保护工作区未提交的改动
git stash   # 若有未提交改动

# 2. 直接将 dev 对齐到 main（旧 commit 已通过 squash merge 进入 main）
git reset --hard origin/main

# 3. 恢复新改动
git stash pop   # 若之前 stash 了
```

> **为什么不用 rebase？** squash merge 在 main 上产生的是一个合并 commit，与 dev 上的原始 commit 序列文本结构不同。rebase 逐个 replay 原始 commit 时，即使内容语义相同，也可能因文本差异触发冲突。`reset --hard` 直接跳过这些已无用的旧 commit，干净利落。

#### 1c. 推送

```bash
git push --force-with-lease
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

前端改动（`ui/mobile/` 下有改动时）：

```bash
cd ui/mobile && npx tsc --noEmit
```

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
- 末尾附 `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`（或当前实际模型）

若改动涉及多个不相关主题，拆分为多个 commit。

### 步骤 7：推送

```bash
git push
```

### 步骤 8：创建 PR（除非 `--no-pr`）

创建前再次确认 dev 领先 main 的 commit：

```bash
git log origin/main..HEAD --oneline
```

**关键检查：**
- 若 commit 数量异常多（>10），**暂停**并提示用户确认，可能是 rebase 不彻底
- 若 commit message 中出现已知的 main 上的 squash merge 标题（如 `#xx`），说明有重复，**终止**

确认无误后创建 PR：

```bash
gh pr create --base main --head dev --title "{title}" --body "$(cat <<'EOF'
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
✓ 已提交并推送到 dev

Commits:
{commit list}

PR: {pr_url}
```

### 步骤 10：监控 CI

PR 创建后立即开始监控 CI：

```bash
gh run list --branch dev --limit 5   # 查看最近 run
gh run watch <run-id>                 # 跟随进度（或轮询）
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
2. 提交新 commit 到 dev（同样遵循步骤 4-7 的 lint + commit 规范）
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

（`--delete-branch` 删除 GitHub 上的远程 dev 分支头部引用，不影响本地）

等待合并完成：

```bash
gh pr view <pr-number> --json state -q .state   # 确认 MERGED
```

### 步骤 13：合并后同步 dev

Squash merge 把所有 commit 压成一个新 commit 进入 main，dev 上的原始 commit 序列已无用。**此时不能用 rebase**（会因文本结构不同产生冲突），必须直接将 dev 对齐 main：

```bash
git fetch origin main
git reset --hard origin/main
git push --force-with-lease
```

完成后输出：

```
✓ PR #{pr-number} 已 squash merge 到 main
✓ dev 已对齐 main（{short-sha}）
```

## PR 合并后（手动触发时）

若用户在其他地方完成了合并，只需执行同步步骤：

```bash
git fetch origin main
git stash                      # 若有未提交改动
git reset --hard origin/main   # 直接对齐 main（squash merge 后 rebase 可能冲突）
git stash pop                  # 恢复改动
git push --force-with-lease
```

**这一步防止下次 PR 出现重复 commit 和无意义的 rebase 冲突。** 若在 `/release` 之后执行，release workflow 产生的 version commit 也会在这一步同步进来。

> **为什么用 `reset --hard` 而不是 `rebase`？** squash merge 把多个 commit 压成一个，文本结构与原始 commit 不同。`rebase` 逐个 replay 旧 commit 时可能触发文本冲突（即使语义相同），而 `reset --hard` 直接跳过这些已无用的旧 commit。

## 常见问题

### PR 包含了已合并的 commit

原因：dev 没在上次 PR 合并后同步回 main。

修复：

```bash
git fetch origin main
git stash                      # 若有未提交改动
git reset --hard origin/main
git stash pop
git push --force-with-lease
```

### CHANGELOG 冲突

原因：release workflow 修改了 main 上的 CHANGELOG（翻转 Unreleased 段），而 dev 上也有 CHANGELOG 改动。

处理：`reset --hard origin/main` 后 CHANGELOG 自动对齐 main 版本，在 Unreleased 段重新添加新内容即可。
