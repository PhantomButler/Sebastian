# 发版手册（Release Runbook）

面向人工 release 操作员。每次发新版本走一遍这个清单即可。

> **TL;DR**：在 main 上跑一条 `gh workflow run`，等 25 分钟，验收 release 页面，然后把 dev 拉回 main。

---

## 0. 前置条件

第一次发版前确认 GitHub 仓库 Settings 里已经配齐：

- **Secrets**
  - `RELEASE_TOKEN`：admin PAT，用于绕过 main 分支保护推 commit + tag
  - `ANDROID_KEYSTORE_BASE64`：release 签名 keystore 的 base64
  - `ANDROID_KEYSTORE_PASSWORD` / `ANDROID_KEY_ALIAS` / `ANDROID_KEY_PASSWORD`
- **Branch protection (main)**：1 approval + 4 required CI checks（`backend-lint` / `backend-type` / `backend-test` / `mobile-lint`）+ squash merge only + bot bypass
- **Tag protection**：`v*.*.*` 只允许 admin 和 `github-actions[bot]` 创建

---

## 1. 决定新版本号

遵循 [SemVer](https://semver.org/lang/zh-CN/)：

- `MAJOR`：不兼容改动（数据库 schema 破坏 / API 路径调整）
- `MINOR`：新增功能但向后兼容（新增子命令 / 新增 Agent）
- `PATCH`：bug 修复 / 文档同步

```bash
# 看上一个 tag
gh release list --limit 5
```

---

## 2. 检查发版前置状态

```bash
# 1) 确认 main 是绿的
git fetch origin main
gh run list --branch main --limit 5

# 2) 确认 CHANGELOG.md 的 [Unreleased] 段写好了本次内容
sed -n '/## \[Unreleased\]/,/## \[/p' CHANGELOG.md | head -40
```

如果 `[Unreleased]` 是空的，先在 dev 上补 changelog → 提 PR → 合并。**不要发空 changelog 的版本**，release.yml 会把 `[Unreleased]` 直接重命名为新版本号。

---

## 3. 触发 Release Workflow

在 main 分支上手动触发，二选一：

**命令行（推荐）**：

```bash
gh workflow run release.yml -f version=X.Y.Z --ref main
sleep 3
gh run list --workflow=release.yml --limit=1
```

**GitHub UI**：Actions → Release → Run workflow → 选择 `main` → 输入版本号（**不带 `v` 前缀**，例如 `0.3.0`）。

---

## 4. 跟随进度

```bash
# 拿到 run id 之后
gh run watch <run-id> --exit-status
```

整个流程包含 4 个 job，串起来约 **20–25 分钟**：

| Job | 作用 | 时长 |
|---|---|---|
| `sync-version` | 改 pyproject.toml / app.json / CHANGELOG.md，commit + tag + push main | ~30s |
| `build-backend` | 打 `sebastian-backend-vX.Y.Z.tar.gz` | ~30s |
| `build-android` | Expo prebuild + 注入签名 + Gradle assembleRelease + 重命名 APK | **~20min** |
| `publish` | 生成 SHA256SUMS + `gh release create` | ~20s |

> Android 构建是瓶颈。期间不要再触发别的 workflow 抢 runner。

---

## 5. 失败处理

### sync-version 失败

通常是 CHANGELOG 缺 `[Unreleased]` section 或者 RELEASE_TOKEN 过期。

- CHANGELOG 问题：在 dev 上补段落 → PR → 合并 → 重新触发
- token 过期：Settings → Secrets → 更新 `RELEASE_TOKEN`

> sync-version 是这一步出错最常见的环节，且**它已经把 commit + tag push 到 main 了**。失败后必须手工清理：
>
> ```bash
> # 1) 删本地 + 远程 tag
> git tag -d vX.Y.Z
> git push origin :refs/tags/vX.Y.Z
>
> # 2) revert sync-version commit（绝不 force-push main）
> git checkout main && git pull
> git revert <commit-sha>
> git push origin main   # 走 admin / RELEASE_TOKEN
> ```

### build-android 失败

- keystore 解码失败 → 检查 `ANDROID_KEYSTORE_BASE64` 是否完整
- gradle 报签名找不到 → 检查 build.gradle 注入逻辑（`release.yml` 的 inline Python patch）
- npm peer conflict → 已有 `--legacy-peer-deps`，如果重新出现说明依赖有大幅升级，需要先在 dev 上修

修完之后，由于 sync-version 已经把版本号 commit 到 main 了，**不能再用同一个版本号重新触发**。要么：

1. **bump 一个 patch**：直接发 `X.Y.Z+1`（推荐，简单）
2. **手工清理回滚**：参考上面的 sync-version 失败处理，把 commit 和 tag 都删了再重发

### publish 失败

下载 artifact、生成 SHA256SUMS、`gh release create` 出错。这一步幂等性差，但 commit + tag 都已经在 main 了。可以直接手工补发：

```bash
gh release create vX.Y.Z \
  sebastian-backend-vX.Y.Z.tar.gz \
  sebastian-app-vX.Y.Z.apk \
  SHA256SUMS \
  --title "vX.Y.Z" \
  --notes-from-tag
```

artifact 可以从失败 run 的 Summary 页面下载。

---

## 6. 发布后验收

```bash
# 1) Release 页面应该有三个 asset
gh release view vX.Y.Z

# 2) SHA256 校验通过
mkdir -p /tmp/sebastian-verify && cd /tmp/sebastian-verify
gh release download vX.Y.Z
shasum -a 256 -c SHA256SUMS --ignore-missing

# 3) 一键安装在干净环境跑通
SEBASTIAN_INSTALL_DIR=/tmp/sebastian-install-test \
  bash -c 'curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash'

# 4) sebastian update 升级路径跑通（在已安装的旧版本目录里）
sebastian update --check       # 应提示可升级
sebastian update -y            # 走完整升级
sebastian serve                # 验证仍能正常启动
```

Android APK：

```bash
adb install sebastian-app-vX.Y.Z.apk
# 打开 App → Settings → 填 server URL → 用首启向导创建的账号登录
```

---

## 7. 把 dev 拉回 main

release workflow 在 main 上多了一个 `chore(release): vX.Y.Z` commit，dev 落后了：

```bash
git checkout dev
git fetch origin main
git rebase origin/main         # CHANGELOG 可能冲突，按 main 的为准
git push --force-with-lease
```

---

## 8. 通告

- 在 README 顶部 badge 自动更新
- 如有用户群 / issue 公告，附 Release URL：`https://github.com/Jaxton07/Sebastian/releases/tag/vX.Y.Z`
- 已有用户提示一句：`sebastian update` 即可升级

---

## 附：紧急撤回某个版本

不到万不得已不要做。如果某个 release 引入了**严重数据损坏 / 安全漏洞**：

```bash
# 1) 标记 release 为 pre-release / draft，让 sebastian update 不再拉它
gh release edit vX.Y.Z --draft

# 2) 立即发一个 patch 版本（X.Y.Z+1）修复
# 3) 在 README 顶部加 deprecation 提示
```

不要直接 `gh release delete` —— 已经升级的用户会被卡在中间状态。
