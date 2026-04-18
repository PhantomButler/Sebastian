---
name: release
description: 发布新版本。确认 main 最新、CHANGELOG 完整，通过 GitHub Actions release workflow 自动构建后端 tarball + Android APK 并发布 GitHub Release。
---

# release - 发布新版本

基于 GitHub Flow：main 是唯一长期分支，直接在 main 上触发 release workflow。

## 使用方式

```
/release
```

可选参数：`/release 0.3.0`（直接指定版本号，跳过版本号询问）

## 前置条件

所有改动已通过 PR squash merge 合入 `main`。

## CHANGELOG 机制说明（必读）

Release workflow（`.github/workflows/release.yml`）处理 CHANGELOG 的方式：

```python
# 伪代码，见 release.yml sync-version job
content.replace("## [Unreleased]", "## [Unreleased]\n\n## [0.3.0] - 2026-04-18", 1)
```

即：**在 `## [Unreleased]` 后面插入版本标题，Unreleased 段下面的条目原封不动保留**。

因此正确的 CHANGELOG 格式是：

```markdown
## [Unreleased]

### Added
- 新功能描述...

### Fixed
- 修复描述...
```

**严禁**在 Unreleased 段内自己写 `## [0.3.0]` 这样的版本标题，否则 workflow 运行后会出现重复标题。

### 段落顺序（只保留有内容的分类）

```markdown
## [Unreleased]

<!-- 大版本可加一行概括性描述 -->

### Breaking Changes
- 迁移步骤或注意事项

### Added
### Changed
### Fixed
### Removed
```

### 格式规则

- 每条以 `- ` 开头，写**用户视角的变更**，不搬 commit message
- Breaking Changes 始终放最前，用独立段（比行内标记更显眼）
- 条目粒度：一个用户可感知的变更一条，相关的小改动合并写

### 何时写

每次 PR 合并时同步更新 `[Unreleased]`，不要攒到发版前一次性补。

## 执行步骤

### 步骤 1：环境检查

确认当前在 `main` 分支且工作区干净：

```bash
git branch --show-current
git status
git pull
```

若不在 `main`，切换过去：`git checkout main && git pull`。
若有未提交改动，提示用户先处理。

### 步骤 2：确认 CHANGELOG

读取 `CHANGELOG.md` 的 `[Unreleased]` 段内容：

```bash
awk '/^## \[Unreleased\]/{found=1; next} found && /^## \[/{exit} found{print}' CHANGELOG.md
```

**情况 A：Unreleased 有内容** → 直接进入步骤 3。

**情况 B：Unreleased 为空** → 需要先补充 CHANGELOG：

1. 读取上个版本 tag 之后的所有 commit，归纳用户可感知的变更：
   ```bash
   git log $(git describe --tags --abbrev=0)..HEAD --oneline
   ```
2. 按格式写入 `## [Unreleased]` 段（**只写条目，不写版本号标题**）
3. 从 main 开 feature branch 提交并创建 PR：
   ```bash
   git checkout -b docs/changelog-for-release
   git add CHANGELOG.md
   git commit -m "docs(changelog): 补充 Unreleased 发版记录"
   git push -u origin HEAD
   gh pr create --base main --title "docs(changelog): 补充 Unreleased 发版记录"
   ```
4. CI 全绿后等待用户 squash merge，合并后回到 main：
   ```bash
   git checkout main && git pull && git branch -d docs/changelog-for-release
   ```
5. 重新从步骤 1 开始执行

### 步骤 3：确定版本号

若用户通过参数指定了版本号，直接使用。

否则，读取当前版本：

```bash
grep -m1 '^version' pyproject.toml
```

根据 Unreleased 内容建议版本号：
- 有 `### Added` 或 `### Changed`（含 breaking）→ minor bump
- 仅 `### Fixed` → patch bump

向用户展示建议版本号和 Unreleased 内容摘要，**等待用户确认或修改**。

### 步骤 4：验证 CI 状态

```bash
gh run list --branch main --limit 3 --json status,conclusion,displayTitle,url
```

- 最近一次 `conclusion` 为 `success`：继续
- 其他状态：**警告**用户，展示具体状态，询问是否继续

### 步骤 5：输出确认摘要

打印发布摘要，**暂停并等待用户确认**：

```
即将执行以下操作：

  当前版本：{current_version}
  发布版本：v{version}
  触发方式：gh workflow run release.yml -f version={version} --ref main

  Workflow 将自动：
  - 更新 pyproject.toml + ui/mobile-android/app/build.gradle.kts 版本号
  - 将 CHANGELOG.md [Unreleased] 段插入 [{version}] - YYYY-MM-DD 版本标题
  - commit + tag + push 到 main
  - 构建 backend tarball + 签名 Android APK
  - 发布 GitHub Release

请确认是否继续发布？
```

**等待用户明确确认后再继续。**

### 步骤 6：触发 release workflow

```bash
gh workflow run release.yml -f version={version} --ref main
```

等待 2-3 秒后获取 run ID：

```bash
sleep 3 && gh run list --workflow=release.yml --limit 1 --json databaseId,status,url
gh run watch {run_id} --exit-status
```

Android 构建约 20 分钟，后台跟踪，完成后通知用户。

### 步骤 7：发版后同步本地 main

Workflow 在 main 上产生了新 commit（`chore(release): v{version}`），拉取最新：

```bash
git pull
```

### 步骤 8：输出结果

用 `gh repo view --json nameWithOwner` 获取 `{owner}/{repo}`，然后输出：

```
v{version} 发布成功！

GitHub Release：
https://github.com/{owner}/{repo}/releases/tag/v{version}

产物：
- sebastian-backend-v{version}.tar.gz
- sebastian-app-v{version}.apk
- SHA256SUMS

用户端升级：sebastian update
全新安装：curl -fsSL https://raw.githubusercontent.com/{owner}/{repo}/main/bootstrap.sh | bash
```

## 注意事项

- **严禁** 在非 `main` ref 上触发 release workflow
- **严禁** `git push --force` 到 main
- **严禁** 在 Unreleased 段写版本号标题，workflow 会自动插入
- Release workflow 使用 `RELEASE_TOKEN`（admin PAT）push tag 和 commit，Repository admin 角色可绕过保护规则
- tag `v*.*.*` 只有 admin 和 `github-actions[bot]` 可创建
- 若需要回滚，在 GitHub 上删除 release + tag，然后 revert main 上的版本 commit
