# Sebastian 发布与 CI/CD 工作流设计

> 日期：2026-04-08
> 状态：设计待评审
> 相关：`CLAUDE.md` §11（代码提交与 PR 工作流）

## 1. 背景与目标

### 当前状况
- 仓库无 `.github/` 目录，无 workflow、无 PR/Issue 模板、无 CODEOWNERS
- 无 `CHANGELOG.md`、无版本同步机制
- 版本号已不一致：`pyproject.toml = 0.1.0` vs `ui/mobile/app.json = 1.0.0`
- `main` / `dev` 分支存在但无保护规则
- 首次部署流程不友好：需手动执行脚本生成密码 hash 再写入 `.env`

### 目标
把 Sebastian 从"个人工作仓库"升级为"贴近准开源项目"的标准工程形态，覆盖四块：

1. **一键自部署**：用户 clone / 下载 release → 跑一条命令即可启动
2. **首次配置友好化**：消灭手写 hash / 手填 `.env` 的原始流程
3. **完整 CI/CD**：PR 质量门禁 + tag 触发发版，自动产出后端包 + Android APK
4. **分支权限与 PR 规范**：为未来开源和多人协作铺好制度底座

### 非目标
- ❌ 不做 Windows 支持（systemd/launchd 都没意义）
- ❌ 不做 iOS 构建与分发（等有需求再付 Apple Developer $99/年）
- ❌ 不发布到 PyPI（包名冲突风险 + 对自用零收益，后续可加）
- ❌ 不做 Docker 镜像发布（主线走本机部署，Docker compose 作为开发辅助保留）
- ❌ 不做 PyInstaller / Nuitka 二进制打包（破坏可审计性，见 §11.1）
- ❌ 不做 GPG 签名（本期只做 SHA256 校验，v1.0 再考虑）
- ❌ 不引入 `config.toml` 额外配置层（owner 入 store，jwt_secret 单文件，详见 §3.3）
- ❌ 不自动注册开机自启（稳定后再考虑）
- ❌ 不做 nightly build / PR 自动 code review（先把主线跑通）

---

## 2. 总体设计

四个相对独立、但互相引用的子系统：

```
┌──────────────────────────┐   ┌──────────────────────────┐
│ A. 首次配置 UX           │   │ B. 版本与分发            │
│  - Web setup 向导        │◄──┤  - 统一 SemVer           │
│  - `sebastian init` CLI  │   │  - bootstrap.sh (一键)   │
│  - owner → store         │   │  - install.sh (内部)     │
│  - jwt_secret → 单文件   │   │  - SHA256SUMS 校验       │
└──────────────────────────┘   └──────────────────────────┘
             ▲                              ▲
             │                              │
┌────────────┴──────────────┐   ┌───────────┴──────────────┐
│ C. CI/CD Workflows        │   │ D. 分支保护 + PR 规范    │
│  - ci.yml (质量门禁)      │◄──┤  - main 保护规则         │
│  - release.yml (发版)     │   │  - tag 保护规则          │
│  - workflow_dispatch 触发 │   │  - PR/Issue 模板         │
└───────────────────────────┘   └──────────────────────────┘
```

---

## 3. 子系统 A：首次配置 UX

### 3.1 问题
当前流程：
```bash
python3 -c "from sebastian.gateway.auth import hash_password; print(hash_password('xxx'))"
# 复制输出 → 编辑 .env → 填 SEBASTIAN_OWNER_PASSWORD_HASH=<hash> → 填 JWT_SECRET → 启动
```
对任何非技术用户都是灾难，对技术用户也难用。

### 3.2 方案：Web 向导为主 + CLI 兜底

#### 启动决策逻辑
`sebastian start`（或直接 `uvicorn sebastian.gateway.app:app`）启动时：

```
启动时检查 SEBASTIAN_DATA_DIR（默认 ~/.sebastian）
├── store 中存在 owner 账号 + secret.key 文件？
│   └─ YES → 正常启动
│   └─ NO  → 进入 setup mode
└── setup mode：
    ├── 打印一次性 setup token 到终端（32 字节随机 hex）
    ├── 只挂载 /setup/* 路由，拒绝其他请求（返回 503）
    ├── /setup/* 路由只接受 127.0.0.1 / ::1 来源
    ├── 所有 /setup/* 请求必须带 X-Setup-Token header
    └── 自动尝试 `open http://127.0.0.1:8000/setup?token=<token>`（macOS/Linux）
```

#### Web 向导页面（单页 HTML，内嵌到 gateway）
位置：`sebastian/gateway/setup/`
- `index.html`：表单 UI（owner 名称、密码、确认密码、Anthropic API Key 可选）
- `setup_routes.py`：`GET /setup` + `POST /setup/complete` 两个路由
- 提交成功后：
  1. 对密码调用 `hash_password()`，往 store 的 `users` 表写入 owner 账号记录
  2. 生成 JWT secret（32 字节 urlsafe base64），写入 `${SEBASTIAN_DATA_DIR}/secret.key`（chmod 600）
  3. 可选：若用户在向导里填了 Anthropic API Key，走现有的 "LLM Provider 加密存储" 流程写入 `llm_providers` 表（与现有 [sebastian/gateway/routes/llm_providers.py](sebastian/gateway/routes/llm_providers.py) 一致）
  4. 返回"配置完成"页面
  5. 后端 3 秒后自动 `os._exit(0)`；用户重新启动 `sebastian start`，这一次因 owner 账号已存在而进入正常模式

#### CLI 兜底：`sebastian init --headless`
给 SSH 无头服务器用。交互式问答同 Web 向导的字段，最终落到同样的 store 表 + `secret.key` 文件。

```python
# sebastian/cli/init.py
@app.command()
def init(headless: bool = False) -> None:
    if headless or not _has_display():
        _run_cli_wizard()
    else:
        _print_setup_mode_hint()  # 提示用户跑 sebastian start 用 Web 向导
```

### 3.3 不引入 `config.toml`
**设计决策**：不新增 `config.toml` / `ConfigLoader`，保持现有 `.env` + 环境变量的配置体系不动。

**推导过程**：一度计划把配置统一迁到 `config.toml`，但逐项盘点后发现所有字段都有现成更合适的位置：

| 字段 | 实际去向 | 理由 |
|---|---|---|
| owner.name / password_hash | store 的 `users` 表 | 用户账号本就该在 DB |
| LLM API keys | store 的 `llm_providers` 表（加密） | 现状已如此，见 [sebastian/llm/registry.py:119](sebastian/llm/registry.py#L119) |
| JWT secret | `~/.sebastian/secret.key`（chmod 600，单文件） | 启动前需要，一行内容不值得为它引入 TOML |
| gateway host / port | 环境变量 / 命令行 flag | 启动参数，非持久配置 |
| data dir | `SEBASTIAN_DATA_DIR` 环境变量 | 同上 |

结果：`config.toml` 里"什么都不剩"，引入它纯粹是增加抽象层。

**真正的改动范围**（比原计划小很多）：
- `sebastian/gateway/auth.py`：owner 账号从 "读 `SEBASTIAN_OWNER_PASSWORD_HASH` env" 改为 "读 store `users` 表"；JWT 签名从 "读 `SEBASTIAN_JWT_SECRET` env" 改为 "读 `secret.key` 文件（fallback 到 env，兼容开发模式）"
- `sebastian/gateway/app.py`：启动时检测 owner 是否存在 → 决定是否进入 setup mode
- **其他配置读取逻辑完全不动**，`sebastian/config/__init__.py` 保持现状
- `.env` 的角色不变：开发环境 / CI / 高级用户使用；setup 向导不写 `.env`，它只写 store 和 `secret.key`

---

## 4. 子系统 B：版本管理与分发

### 4.1 版本策略：统一 SemVer
- 后端 `pyproject.toml` 和 `ui/mobile/app.json` 的 `version` 字段始终保持一致
- `0.x` 阶段允许 minor 版本带 breaking change；`1.0` 起严格 SemVer
- **CI 负责同步**：发版 workflow 从 tag 反写两个文件并 commit 回 main

### 4.2 CHANGELOG
- 文件：`CHANGELOG.md`，遵循 [Keep a Changelog](https://keepachangelog.com/) 格式
- 手动维护：PR 合入前作者需在 `[Unreleased]` 段补一行
- 发版时 workflow 自动把 `[Unreleased]` 重命名为 `[X.Y.Z] - YYYY-MM-DD`，并在上方插入新的 `[Unreleased]` 空段

### 4.3 Release 产物
每次 release 在 GitHub Release 页面挂三个 asset：

| 产物 | 文件名 | 内容 |
|---|---|---|
| 后端源码包 | `sebastian-backend-v0.2.0.tar.gz` | `sebastian/` 源码 + `pyproject.toml` + `install.sh` + `README.md` + `LICENSE` + `CHANGELOG.md` |
| Android APK | `sebastian-app-v0.2.0.apk` | 已签名的 release APK |
| 校验文件 | `SHA256SUMS` | 上述两个 asset 的 SHA256 指纹 |

### 4.4 `bootstrap.sh` —— 一键安装入口（推荐路径）

位置：仓库根目录 `bootstrap.sh`，随 `main` 分支发布。用户通过 `raw.githubusercontent.com` 直接 `curl` 到。

职责：
```bash
#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${SEBASTIAN_INSTALL_DIR:-$HOME/.sebastian/app}"
REPO="Jaxton07/Sebastian"

# 1. 环境检查：Python 3.12+ / macOS 或 Linux / curl / tar / shasum
check_prerequisites

# 2. 调 GitHub API 拿最新 release tag
LATEST_TAG=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | jq -r .tag_name)

# 3. 下载 tar.gz 和 SHA256SUMS 到临时目录
TMPDIR=$(mktemp -d)
curl -fsSL "https://github.com/${REPO}/releases/download/${LATEST_TAG}/sebastian-backend-${LATEST_TAG}.tar.gz" \
  -o "${TMPDIR}/sebastian.tar.gz"
curl -fsSL "https://github.com/${REPO}/releases/download/${LATEST_TAG}/SHA256SUMS" \
  -o "${TMPDIR}/SHA256SUMS"

# 4. 强制校验 SHA256
( cd "${TMPDIR}" && shasum -a 256 -c SHA256SUMS --ignore-missing ) \
  || { echo "❌ SHA256 校验失败，疑似供应链污染，已中止"; exit 1; }

# 5. 解压到 INSTALL_DIR
mkdir -p "${INSTALL_DIR}"
tar xzf "${TMPDIR}/sebastian.tar.gz" -C "${INSTALL_DIR}" --strip-components=1

# 6. 运行 install.sh
cd "${INSTALL_DIR}"
exec ./install.sh
```

最终用户体验：
```bash
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
# 浏览器自动打开 http://127.0.0.1:8000/setup?token=xxx
# 用户填表单 → 完成
```

### 4.5 `install.sh` —— 内部步骤 + 手动安装入口

位置：`scripts/install.sh`（随 tar.gz 发布；也在 git 仓库里给 `git clone` 用户用）

职责（在 `bootstrap.sh` 已解压好的目录里运行，或用户手动解压后运行）：
```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. 环境检查
check_python_version >= 3.12  # 否则报错退出
check_os in [macOS, Linux]    # 否则报错退出

# 2. 创建 venv
python3.12 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install --upgrade pip
pip install -e .

# 4. 启动 setup 向导
echo "启动 Sebastian 首次配置向导..."
exec sebastian start  # 进入 setup mode，用户跟浏览器走完 Web 向导
```

**关键约束**：
- 脚本全程只用 bash，不依赖外部 CLI 工具（curl 除外）
- 出错时给出明确中英文提示
- 不做开机自启注册（本版本非目标）
- 脚本结尾执行 `sebastian start` 后直接阻塞在终端，Ctrl-C 停止；生产使用由用户自行 `nohup` / `screen` / `tmux`

### 4.6 用户侧安装流程（最终体验）

**推荐：一键安装**
```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
# 浏览器自动打开 http://127.0.0.1:8000/setup?token=xxx
# 用户填表单 → 后端自动写入 store → 重启 → 正常运行
```

**手动安装**（给偏执型用户，可以逐步校验）
```bash
# 1. 下载 tar.gz 和 SHA256SUMS
curl -LO https://github.com/Jaxton07/Sebastian/releases/download/v0.2.0/sebastian-backend-v0.2.0.tar.gz
curl -LO https://github.com/Jaxton07/Sebastian/releases/download/v0.2.0/SHA256SUMS

# 2. 手动校验指纹
shasum -a 256 -c SHA256SUMS --ignore-missing

# 3. 解压 + 跑 install.sh
tar xzf sebastian-backend-v0.2.0.tar.gz
cd sebastian-backend-v0.2.0
./install.sh
```

**Android**：从同一 Release 页下载 APK → `adb install` 或直接传手机安装

---

## 5. 子系统 C：CI/CD Workflows

### 5.1 `ci.yml` —— 质量门禁
**触发**：
- `pull_request` to `main` 或 `dev`
- `push` to `dev`

**Jobs**（全部 Ubuntu runner，并行）：

```yaml
backend-lint:
  - ruff check sebastian/ tests/
  - ruff format --check sebastian/ tests/

backend-type:
  - mypy sebastian/

backend-test:
  - matrix: python 3.12
  - pip install -e ".[dev,memory]"
  - pytest tests/unit tests/integration -v

mobile-lint:
  - cd ui/mobile
  - npm ci --legacy-peer-deps
  - npx tsc --noEmit
```

所有 job 必须通过才能合并到 `main`。

### 5.2 `release.yml` —— 发版流水线

**触发**：`workflow_dispatch`（手动），输入参数 `version`（如 `0.2.0`）

**Jobs**（有顺序依赖）：

```
sync-version (needs: -)
  ├─ checkout main
  ├─ update pyproject.toml version = ${inputs.version}
  ├─ update ui/mobile/app.json version = ${inputs.version}
  ├─ update CHANGELOG.md：把 [Unreleased] 改成 [X.Y.Z] - $(date)
  ├─ commit: "chore(release): v${inputs.version}"
  ├─ git tag v${inputs.version}
  └─ git push main + tag

build-backend (needs: sync-version)
  ├─ checkout tag v${inputs.version}
  ├─ 打包成 sebastian-backend-v${inputs.version}.tar.gz
  │  (包含 sebastian/ + pyproject.toml + scripts/install.sh + README.md + LICENSE + CHANGELOG.md)
  └─ upload artifact

build-android (needs: sync-version)
  ├─ checkout tag v${inputs.version}
  ├─ setup Java 17 + Android SDK
  ├─ cd ui/mobile && npm ci --legacy-peer-deps
  ├─ 从 GitHub Secrets 恢复 release keystore（base64 解码）
  ├─ cd android && ./gradlew assembleRelease
  ├─ 重命名为 sebastian-app-v${inputs.version}.apk
  └─ upload artifact

publish-release (needs: [build-backend, build-android])
  ├─ download 两个 artifact
  ├─ 生成 SHA256SUMS 文件（对 tar.gz 和 apk 计算 SHA256）
  ├─ 从 CHANGELOG.md 中抽取 [X.Y.Z] 段落作为 release body
  └─ gh release create v${inputs.version} *.tar.gz *.apk SHA256SUMS --notes "${body}"
```

**关键点**：
- `sync-version` 会向 `main` 推送一个 commit + 一个 tag。这要求 workflow 的 GITHUB_TOKEN 能绕过 branch protection（或使用 deploy key）。具体做法：配置 `main` 的 branch protection 时勾选"Allow specified actors to bypass"，把 `github-actions[bot]` 加入例外。
- 版本号单一来源：workflow input 参数。人不直接编辑 `pyproject.toml` 的 version 字段。

### 5.3 GitHub Secrets 所需项

| Secret | 用途 |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | release keystore 的 base64 编码 |
| `ANDROID_KEYSTORE_PASSWORD` | keystore 密码 |
| `ANDROID_KEY_ALIAS` | 签名 alias |
| `ANDROID_KEY_PASSWORD` | alias 密码 |

### 5.4 Android Release Keystore 一次性初始化

作为 spec 落地的一部分，需执行（一次性）：

```bash
keytool -genkeypair -v -storetype PKCS12 \
  -keystore sebastian-release.keystore \
  -alias sebastian -keyalg RSA -keysize 2048 -validity 10000

# base64 编码
base64 -i sebastian-release.keystore | pbcopy

# 通过 GitHub UI 或 gh CLI 上传到 Secrets
gh secret set ANDROID_KEYSTORE_BASE64 < keystore.b64
gh secret set ANDROID_KEYSTORE_PASSWORD --body "<password>"
gh secret set ANDROID_KEY_ALIAS --body "sebastian"
gh secret set ANDROID_KEY_PASSWORD --body "<password>"

# 本地保留一份 keystore 备份（离开仓库，存密码管理器），keystore 丢失 = 永远无法更新已发布的 App
```

⚠️ **安全红线**：keystore 文件绝不进 git，本地备份务必妥善保管。

---

## 6. 子系统 D：分支保护 + PR 规范

### 6.1 分支模型
- **`main`**：稳定分支，只接受 PR 合入，对应已发布或准发布的代码
- **`dev`**：日常开发主阵地，允许直接 push
- **`feature/*` / `fix/*`**：短生命周期分支，PR 合入 `main` 或 `dev` 后删除

### 6.2 `main` 分支保护规则

| 规则 | 值 |
|---|---|
| Require pull request | ✅ |
| Required approvals | 1 |
| Dismiss stale approvals on new commits | ✅ |
| Require status checks before merge | ✅ |
| Required checks | `backend-lint` `backend-type` `backend-test` `mobile-lint` |
| Require branches up to date | ✅ |
| Restrict who can push | Empty（即任何人都不能直接 push） |
| Allow force push | ❌ |
| Allow deletions | ❌ |
| Allow bypass | `Jaxton07`（admin bypass）+ `github-actions[bot]`（发版 workflow 需要） |
| Allowed merge methods | Squash only |

### 6.3 Tag 保护规则
- 模式：`v*.*.*`
- 只有 admin 和 `github-actions[bot]` 可创建此模式的 tag
- 禁止删除 / 强制更新

### 6.4 `.github/` 目录内容

```
.github/
├── workflows/
│   ├── ci.yml
│   └── release.yml
├── ISSUE_TEMPLATE/
│   ├── bug_report.md
│   ├── feature_request.md
│   └── config.yml
├── PULL_REQUEST_TEMPLATE.md
├── CODEOWNERS
└── dependabot.yml          # 周级依赖更新 PR（后端 pip + mobile npm）
```

### 6.5 PR 模板

```markdown
## Summary
<!-- 改了什么、为什么改（1-3 条要点） -->

## Test plan
<!-- 验证步骤 checklist -->
- [ ]
- [ ]

## Related
<!-- 关联的 Issue / Spec / PR -->
```

### 6.6 CODEOWNERS

```
*       @Jaxton07
```

单行即可，未来有 contributor 再细化。

### 6.7 Dependabot
启用 `pip` 和 `npm` 生态，每周一次，自动打 PR。会被 `ci.yml` 门禁过一遍，由 owner 手动审核合入。

---

## 7. 文件落点一览

新增：
```
.github/workflows/ci.yml
.github/workflows/release.yml
.github/ISSUE_TEMPLATE/bug_report.md
.github/ISSUE_TEMPLATE/feature_request.md
.github/ISSUE_TEMPLATE/config.yml
.github/PULL_REQUEST_TEMPLATE.md
.github/CODEOWNERS
.github/dependabot.yml
bootstrap.sh                    # 一键安装入口，放仓库根目录
scripts/install.sh              # 内部安装步骤 + 手动入口
CHANGELOG.md
LICENSE                         # Apache-2.0
sebastian/cli/__init__.py
sebastian/cli/init.py           # sebastian init --headless CLI 向导
sebastian/gateway/setup/__init__.py
sebastian/gateway/setup/setup_routes.py   # /setup/* 路由 + 内嵌 HTML 字符串
```

修改：
```
pyproject.toml                  # version 字段（交给 release workflow 维护）
ui/mobile/app.json              # version 字段同上
sebastian/main.py               # 注册 cli init 子命令、start 启动时检查 setup mode
sebastian/gateway/app.py        # 启动时检测 owner，决定正常模式 / setup mode
sebastian/gateway/auth.py       # owner 从 store 读；JWT secret 从 secret.key 读
CLAUDE.md                       # 更新 §3 启动命令、§6 环境变量、§11 PR 流程
README.md                       # 新增"一键安装"章节 + 手动安装 + 校验说明
.gitignore                      # 增补 secret.key、build 产物
```

---

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Release workflow push 到 main 被 branch protection 拒绝 | 在 bypass 列表加 `github-actions[bot]`，并单独限制其只能做 release commit（通过 commit message 前缀校验） |
| Android keystore 丢失导致无法更新 App | 本地备份 + 密码管理器 + 仓库外的加密云备份 三重冗余 |
| Setup mode 被外网访问绕过 | 三重限制：绑定 127.0.0.1 + 来源 IP 白名单 + 一次性 token |
| `secret.key` 误提交或泄漏 | `.gitignore` 显式排除；默认路径 `~/.sebastian/secret.key` 不在项目内；chmod 600 |
| bootstrap.sh 从 GitHub raw 拉取被中间人篡改 | 全程 HTTPS（GitHub 强制）；下载 tar.gz 后强制校验 SHA256SUMS；`curl -fsSL` 确保 TLS |
| 用户直接 `curl | bash` 的信任问题 | README 并列提供"手动安装"路径；bootstrap.sh 本身开源可读；脚本头部打印即将执行的动作 |
| Dependabot 噪音过大 | 限制每周最多 5 个 PR，只跟 minor/patch，major 手动处理 |
| Squash merge 丢失 feature 分支的细粒度历史 | PR 页面永远保留原 commits；main 历史只看发版单位就够了 |

---

## 9. 实施阶段划分（供 writing-plans 参考）

初步拆分，细节由后续 implementation plan 细化：

1. **Phase 1：基础 CI/CD 骨架**（先能跑起来）
   - 创建 `.github/` 目录结构
   - `ci.yml` 上线：lint / type / test / mobile lint
   - PR 模板、Issue 模板、CODEOWNERS、dependabot
   - `main` 分支保护规则 + tag 保护规则配置
   - 目的：未来每个 PR 都自动跑门禁
2. **Phase 2：首次配置 UX**
   - `auth.py` 改造：owner 从 store 读，JWT secret 从 `secret.key` 读（fallback 到 env 兼容开发）
   - `app.py` 启动时检测 owner → setup mode 分支
   - `/setup/*` 路由 + 内嵌 HTML 单页向导（setup_routes.py 一个文件）
   - `sebastian init --headless` CLI 子命令
   - 安全限制（127.0.0.1 + token）的集成测试
3. **Phase 3：install.sh + bootstrap.sh + 源码包**
   - `scripts/install.sh` 实现
   - `bootstrap.sh` 实现（含 SHA256SUMS 校验）
   - 手动验证 macOS / Linux 全流程
   - README 新增"一键安装 / 手动安装 / 手动校验"章节
4. **Phase 4：Release 流水线**
   - 生成 Android release keystore + 上传 Secrets
   - `release.yml` workflow 实现（含 SHA256SUMS 生成）
   - 第一次手动触发发版（v0.2.0），产出 tar.gz + APK + SHA256SUMS
   - 跑通 `curl ... | bash` 端到端（用真实 release 验证 bootstrap.sh）
5. **Phase 5：文档同步**
   - `CLAUDE.md` 更新（启动命令、环境变量、PR 流程）
   - `CHANGELOG.md` 初始化（`[Unreleased]` + `[0.2.0]`）
   - `LICENSE` 文件添加（Apache-2.0）
   - README 整体重写为面向用户

---

## 10. 开放问题

无。所有关键决策已在 §1–§9 中闭环。

---

## 11. 安全模型与供应链完整性

### 11.1 为什么用源码分发而不是编译二进制
准开源项目的核心价值是"代码可审计"。Sebastian 作为 AI 管家会读写文件、调用工具、访问 LLM API，**用户必须能看到代码才敢让它住进自己的设备**。PyInstaller / Nuitka 之类的"编译"方案：
- 没有实质安全收益 —— Python 字节码逆向非常容易
- 破坏可审计性 —— 用户无法验证二进制和仓库源码一致
- 增加构建复杂度与跨平台问题

**决策：源码分发，不做二进制打包**。

### 11.2 供应链完整性：三道防线
真正的安全风险是"用户下载的 tar.gz 不是官方构建"（中间人 / CDN 劫持 / 恶意镜像）。对策：

1. **HTTPS 下载**：GitHub Release 全程强制 HTTPS，`bootstrap.sh` 用 `curl -fsSL` 保证 TLS 校验
2. **SHA256SUMS 校验**：
   - `release.yml` 的 `publish-release` job 对每个 asset 计算 SHA256 并生成 `SHA256SUMS` 文件一起挂到 Release
   - `bootstrap.sh` 下载 tar.gz 后**强制**校验，不匹配立即 `exit 1`
   - 手动安装路径也在 README 里写明 `shasum -a 256 -c` 命令
3. **本期不做 GPG 签名**：对个人项目是 overkill，维护私钥成本高于收益；v1.0 再考虑

### 11.3 运行时权限：架构层面的事，不是打包格式
Sebastian 跑在用户机器上、以用户身份运行，理论上能做任何用户本人能做的事。这是"个人自托管 AI 管家"架构本身决定的信任模型，和分发格式无关。真正缓解这一层风险靠已规划的架构能力：
- [sebastian/sandbox/](sebastian/sandbox/)：dynamic tool 执行时 Docker 隔离
- Approval 机制：高危操作（文件删除、网络请求、系统命令）需要用户显式授权
- 用户敏感数据（密码 hash / JWT secret / LLM key / 聊天历史）只存本地 `~/.sebastian/`，不外传

### 11.4 用户直接 `curl | bash` 的信任问题
这是个典型争议点。我们的应对：
- **并列提供手动安装路径**：README 同等篇幅给出 `wget` + `shasum` + `tar` + `install.sh` 四步版本，给偏执型用户用
- **bootstrap.sh 本身开源可读**：用户可以在执行前 `curl ... | less` 审视
- **脚本头部打印动作清单**：在执行任何操作前先 echo "I will: 1. download ... 2. verify ... 3. extract ... 4. run install.sh"，允许 Ctrl-C 中止
- **对比业界实践**：这就是 Rust `rustup` / Homebrew / Ollama / `nvm` 等主流工具的通行做法，信任模型已被工业界广泛接受
