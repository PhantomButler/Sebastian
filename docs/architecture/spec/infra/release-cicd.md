---
version: "1.0"
last_updated: 2026-04-10
status: implemented
---

# 发布与 CI/CD 工作流

*← [Infra 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 背景与目标

把 Sebastian 从"个人工作仓库"升级为标准工程形态，覆盖四块：

1. **一键自部署**：clone / 下载 release → 跑一条命令即可启动
2. **首次配置友好化**：消灭手写 hash / 手填 `.env` 的原始流程
3. **完整 CI/CD**：PR 质量门禁 + workflow_dispatch 触发发版，自动产出后端包 + Android APK
4. **分支权限与 PR 规范**：为未来开源和多人协作铺好底座

### 非目标

- Windows 支持、iOS 构建、PyPI 发布、Docker 镜像发布
- PyInstaller / Nuitka 二进制打包（破坏可审计性）
- GPG 签名（本期只做 SHA256 校验）
- 开机自启注册、nightly build、自动 code review

---

## 2. 总体设计

```
┌──────────────────────────┐   ┌──────────────────────────┐
│ A. 首次配置 UX           │   │ B. 版本与分发            │
│  - Web setup 向导        │◄──┤  - 统一 SemVer           │
│  - sebastian init CLI    │   │  - bootstrap.sh (一键)   │
│  - owner → store         │   │  - install.sh (内部)     │
│  - jwt_secret → 单文件   │   │  - SHA256SUMS 校验       │
└──────────────────────────┘   └──────────────────────────┘
             ▲                              ▲
┌────────────┴──────────────┐   ┌───────────┴──────────────┐
│ C. CI/CD Workflows        │   │ D. 分支保护 + PR 规范    │
│  - ci.yml (质量门禁)      │◄──┤  - main 保护规则         │
│  - release.yml (发版)     │   │  - tag 保护规则          │
└───────────────────────────┘   └──────────────────────────┘
```

---

## 3. 首次配置 UX

### 3.1 启动决策逻辑

`sebastian serve` 启动时检查 `SEBASTIAN_DATA_DIR`（默认 `~/.sebastian`）：

```
├── store 中存在 owner 账号 + secret.key 文件？
│   └─ YES → 正常启动
│   └─ NO  → 进入 setup mode
└── setup mode：
    ├─ 打印一次性 setup token 到终端（32 字节随机 hex）
    ├─ 只挂载 /setup/* 路由，拒绝其他请求（返回 503）
    ├─ /setup/* 路由只接受 127.0.0.1 / ::1 来源
    ├─ 所有 /setup/* 请求必须带 X-Setup-Token header
    └─ 自动尝试 open http://127.0.0.1:8823/setup?token=<token>
```

> **实现差异**：spec 原写 `sebastian start`，实际 CLI 命令为 `sebastian serve`。

### 3.2 Web 向导

位置：`sebastian/gateway/setup/`

- `setup_routes.py`：`GET /setup` + `POST /setup/complete` 两个路由，内嵌 HTML 单页表单
- 表单字段：owner 名称、密码、确认密码、Anthropic API Key（可选）

提交成功后：
1. 对密码调用 `hash_password()`，往 store `users` 表写入 owner 账号
2. 生成 JWT secret（32 字节 urlsafe base64），写入 `${SEBASTIAN_DATA_DIR}/secret.key`（chmod 600）
3. 若填了 API Key，走现有 LLM Provider 加密存储流程写入 `llm_providers` 表
4. 返回"配置完成"页面
5. 后端 3 秒后自动退出，用户重启进入正常模式

### 3.3 CLI 兜底

`sebastian init --headless`：给 SSH 无头服务器用，交互式问答同 Web 向导字段。

### 3.4 不引入 config.toml

设计决策：不新增 `config.toml`，保持现有 `.env` + 环境变量的配置体系。

| 字段 | 实际去向 | 理由 |
|---|---|---|
| owner.name / password_hash | store `users` 表 | 用户账号本就该在 DB |
| LLM API keys | store `llm_providers` 表（加密） | 现状已如此 |
| JWT secret | `~/.sebastian/secret.key`（chmod 600） | 一行内容不值得引入 TOML |
| gateway host / port | 环境变量 / 命令行 flag | 启动参数，非持久配置 |

auth.py 改动：owner 从 store 读，JWT secret 从 `secret.key` 文件读（fallback 到 env 兼容开发模式）。

---

## 4. 版本管理与分发

### 4.1 版本策略

- `pyproject.toml` 和 `ui/mobile/app.json` 的 `version` 字段始终保持一致
- `0.x` 阶段允许 minor 版本带 breaking change；`1.0` 起严格 SemVer
- 发版 workflow 从 tag 反写两个文件并 commit 回 main

### 4.2 CHANGELOG

- 文件：`CHANGELOG.md`，遵循 [Keep a Changelog](https://keepachangelog.com/) 格式
- 手动维护：PR 合入前在 `[Unreleased]` 段补一行
- 发版时 workflow 自动把 `[Unreleased]` 重命名为 `[X.Y.Z] - YYYY-MM-DD`

### 4.3 Release 产物

| 产物 | 文件名 | 内容 |
|---|---|---|
| 后端源码包 | `sebastian-backend-vX.Y.Z.tar.gz` | `sebastian/` + `pyproject.toml` + `install.sh` + README + LICENSE + CHANGELOG |
| Android APK | `sebastian-app-vX.Y.Z.apk` | 已签名的 release APK |
| 校验文件 | `SHA256SUMS` | 上述两个 asset 的 SHA256 指纹 |

### 4.4 bootstrap.sh

位置：仓库根目录。用户通过 `raw.githubusercontent.com` curl 到。

职责：环境检查 → 调 GitHub API 拿最新 release tag → 下载 tar.gz + SHA256SUMS → 强制校验 SHA256 → 解压 → 运行 `install.sh`。

### 4.5 install.sh

位置：`scripts/install.sh`

职责：检查 Python 3.12+ → 创建 venv → pip install → 启动 `sebastian serve`（进入 setup mode）。

---

## 5. CI/CD Workflows

### 5.1 ci.yml — 质量门禁

触发：`pull_request` to `main` 或 `dev`，`push` to `dev`

| Job | 内容 |
|---|---|
| `backend-lint` | `ruff check` + `ruff format --check` |
| `backend-type` | `mypy sebastian/` |
| `backend-test` | `pytest tests/unit tests/integration -v` |
| `mobile-lint` | `npx tsc --noEmit` |

所有 job 必须通过才能合并到 `main`。

### 5.2 release.yml — 发版流水线

触发：`workflow_dispatch`（手动），输入参数 `version`

```
sync-version
  ├─ update pyproject.toml + app.json version
  ├─ update CHANGELOG.md
  ├─ commit + tag + push main
  │
  ├─→ build-backend (tar.gz)
  ├─→ build-android (签名 APK)
  │
  └─→ publish-release
       ├─ 生成 SHA256SUMS
       └─ gh release create + 三个 asset
```

`sync-version` 向 main 推 commit + tag，需要 `github-actions[bot]` 在 branch protection bypass 列表中。Release workflow 使用 `RELEASE_TOKEN`（admin PAT）推送。

### 5.3 GitHub Secrets

| Secret | 用途 |
|---|---|
| `RELEASE_TOKEN` | admin PAT，用于 push to main + create tag |
| `ANDROID_KEYSTORE_BASE64` | release keystore 的 base64 编码 |
| `ANDROID_KEYSTORE_PASSWORD` | keystore 密码 |
| `ANDROID_KEY_ALIAS` | 签名 alias |
| `ANDROID_KEY_PASSWORD` | alias 密码 |

---

## 6. 分支保护与 PR 规范

### 6.1 分支模型

- `main`：稳定分支，只接受 PR squash merge
- `dev`：日常开发主阵地，允许直接 push
- `feature/* / fix/*`：短生命周期分支，PR 合入后删除

### 6.2 main 分支保护规则

| 规则 | 值 |
|---|---|
| Require pull request | ✅ |
| Required approvals | 1 |
| Required checks | `backend-lint` `backend-type` `backend-test` `mobile-lint` |
| Restrict who can push | 无人可直接 push |
| Allow bypass | `Jaxton07`（admin）+ `github-actions[bot]`（发版） |
| Allowed merge methods | Squash only |

### 6.3 Tag 保护

- 模式：`v*.*.*`
- 只有 admin 和 `github-actions[bot]` 可创建
- 禁止删除 / 强制更新

### 6.4 .github/ 目录

```
.github/
├── workflows/ci.yml
├── workflows/release.yml
├── ISSUE_TEMPLATE/
├── PULL_REQUEST_TEMPLATE.md
├── CODEOWNERS             # * @Jaxton07
└── dependabot.yml         # 周级 pip + npm 依赖更新
```

---

## 7. 安全模型

### 7.1 源码分发

决策：不做二进制打包。Python 字节码逆向容易、破坏可审计性、增加构建复杂度。

### 7.2 供应链完整性

三道防线：
1. **HTTPS 下载**：GitHub Release 全程强制 HTTPS
2. **SHA256SUMS 校验**：`bootstrap.sh` 下载后强制校验
3. **本期不做 GPG 签名**：v1.0 再考虑

### 7.3 Setup Mode 安全

三重限制：绑定 127.0.0.1 + 来源 IP 白名单 + 一次性 token。

---

## 8. CLI 命令

| 命令 | 说明 |
|---|---|
| `sebastian serve` | 启动 Gateway（检测 setup mode） |
| `sebastian init --headless` | 无头服务器初始化 |
| `sebastian update` | 下载最新 release 并更新（保留数据/venv） |

---

*← [Infra 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
