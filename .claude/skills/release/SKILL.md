---
name: release
description: 发布新版本。同步 dev 到 main，通过 GitHub Actions release workflow 自动构建后端 tarball + Android APK 并发布 GitHub Release。
---

# release - 发布新版本

将 dev 分支的改动合入 main，通过 `gh workflow run release.yml` 触发自动发版，产物包含 backend tarball、签名 APK 和 SHA256SUMS。

## 使用方式

```
/release
```

可选参数：`/release 0.2.6`（直接指定版本号，跳过版本号询问）

## 前置条件（人工完成）

1. 相关改动已合并到 `main`（通过 PR squash merge）
2. `CHANGELOG.md` 的 `[Unreleased]` 段有本次变更记录

## CHANGELOG 写法

CHANGELOG.md 遵循 [Keep a Changelog](https://keepachangelog.com/) 格式。Release workflow 会自动将 `[Unreleased]` 段翻为带版本号和日期的段落，因此只需维护 Unreleased 部分。

### 分类

按以下顺序使用三级标题，只保留有内容的分类：

- `### Added` — 新功能、新命令、新文件
- `### Changed` — 现有功能的行为变更、接口调整
- `### Fixed` — Bug 修复
- `### Removed` — 删除的功能或文件

### 格式规则

- 每条以 `- ` 开头，写**用户视角的变更**，不是搬运 commit message
- 多行续写缩进 2 空格对齐
- Breaking change 在条目前加 `**[breaking]**` 标记
- 条目粒度：一个用户可感知的变更一条，相关的小改动合并写

### 示例

```markdown
## [Unreleased]

### Added
- `sebastian serve -d`：后台 daemon 模式运行，写 PID 到 `~/.sebastian/sebastian.pid`，
  stdout/stderr 重定向到 `~/.sebastian/logs/sebastian.log`。
- `sebastian stop` / `sebastian status` / `sebastian logs`：配套进程管理命令。

### Fixed
- 修复退出 App 重新打开历史对话时 thinking 折叠块不显示的问题。

### Changed
- **[breaking]** 默认网关端口由 `8000` 改为 `8823`。已部署的用户升级后需把
  App Server URL 里的 `:8000` 改成 `:8823`，或在 `.env` 里设置
  `SEBASTIAN_GATEWAY_PORT=8000` 保留旧行为。
```

### 何时写

每次向 dev 提交功能/修复时就更新 `[Unreleased]`，不要攒到发版前一次性补。步骤 3 会读取此段内容来建议版本号。

## 执行步骤

### 步骤 1：环境检查

确认当前在 `dev` 分支：

```bash
git branch --show-current
```

若不在 `dev`，切换过去。若有未提交改动，提示用户先处理。

### 步骤 2：同步 dev 到 main

```bash
git fetch origin main
git rebase origin/main
```

若 rebase 有冲突，**终止**并提示用户手动解决。

rebase 成功后推送：

```bash
git push --force-with-lease
```

### 步骤 3：确定版本号

若用户通过参数指定了版本号，直接使用。

否则，读取当前版本：

```bash
grep -m1 '^version' pyproject.toml
```

读取 `CHANGELOG.md` 的 `[Unreleased]` 内容，根据变更类型建议版本号：
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
  - 更新 pyproject.toml + ui/mobile/app.json 版本号
  - 将 CHANGELOG.md [Unreleased] 翻为 [{version}] - YYYY-MM-DD
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

获取 run ID 并开始跟踪：

```bash
gh run watch {run_id} --exit-status
```

Android 构建约 20 分钟，使用后台模式跟踪，完成后通知用户。

### 步骤 7：发版后同步 dev

workflow 完成后，将 dev rebase 到最新 main（release workflow 会在 main 上产生新 commit）：

```bash
git fetch origin main
git rebase origin/main
git push --force-with-lease
```

CHANGELOG 冲突时保留 main 版本（workflow 已正确处理了 Unreleased 段）。

### 步骤 8：输出结果

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

用 `gh repo view --json nameWithOwner` 获取 `{owner}/{repo}`。

## 注意事项

- **严禁** 在非 `main` ref 上触发 release workflow
- **严禁** `git push --force` 到 main
- Release workflow 使用 `RELEASE_TOKEN`（admin PAT）push tag 和 commit，绕过分支保护
- tag `v*.*.*` 只有 admin 和 `github-actions[bot]` 可创建
- 若需要回滚，在 GitHub 上删除 release + tag，然后 revert main 上的版本 commit
- 发版完成后 dev 的 CHANGELOG 可能与 main 冲突，步骤 7 的 rebase 会自动处理
