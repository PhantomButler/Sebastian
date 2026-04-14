# Changelog

本文件记录 Sebastian 的所有重要变更，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Breaking Changes
- 子代理 `code` 重命名为 `forge`；移除 `manifest.toml` 的 `name` 字段和 `AgentConfig.display_name`，agent 只有一个名字（`agent_type`，等于目录名）。`GET /api/v1/agents` 响应不再返回 `name` 字段，UI 展示名由前端对 `agent_type` 做 capitalize。
- 升级前请处理历史会话数据：

  ```bash
  # 选项 A：保留历史（生产 + 开发数据目录）
  mv ~/.sebastian/sessions/code ~/.sebastian/sessions/forge 2>/dev/null
  mv ~/.sebastian-dev/sessions/code ~/.sebastian-dev/sessions/forge 2>/dev/null
  python3 -c "
  import json, pathlib
  for base in ['.sebastian', '.sebastian-dev']:
      p = pathlib.Path.home() / base / 'sessions/index.json'
      if not p.exists(): continue
      d = json.loads(p.read_text())
      for e in d.get('sessions', []):
          if e.get('agent_type') == 'code':
              e['agent_type'] = 'forge'
      p.write_text(json.dumps(d, ensure_ascii=False, indent=2))
  "

  # 选项 B：放弃历史
  rm -rf ~/.sebastian/sessions/code ~/.sebastian-dev/sessions/code
  python3 -c "
  import json, pathlib
  for base in ['.sebastian', '.sebastian-dev']:
      p = pathlib.Path.home() / base / 'sessions/index.json'
      if not p.exists(): continue
      d = json.loads(p.read_text())
      d['sessions'] = [e for e in d.get('sessions', []) if e.get('agent_type') != 'code']
      p.write_text(json.dumps(d, ensure_ascii=False, indent=2))
  "
  ```

- Gateway 启动时会对 `sessions/` 下的孤儿目录（注册表里没有 agent_type）打 warning 日志。

## [0.2.6] - 2026-04-10

### Added
- 新增自定义 App 图标（发光交叉环设计）与黑色 splash 背景，替换默认 Expo 图标。
- `scripts/dev.sh`：开发环境一键启动脚本，使用独立数据目录 `~/.sebastian-dev` 和端口 8824，避免与生产环境冲突。

### Changed
- 侧边栏导航重构为 `SwipePager` 平铺滑动方案，替换旧 `Sidebar` + `ContentPanGestureArea` 组件，解决导航跳转闪烁与返回状态丢失问题。
- 统一密钥源为 `secret.key` 文件，移除 `SEBASTIAN_JWT_SECRET` 等废弃环境变量 fallback；`crypto.py` / `auth.py` 只从文件读取密钥。
- 流式输出滚动优化：修复上滑被强制拉回底部及跟随无法恢复的问题。

### Fixed
- 修复夜间模式下对话样式与下箭头图标显示异常。
- 修复 Markdown 引用块夜间模式样式。
- `setup` 完成后终端正确输出重启提示。

## [0.2.5] - 2026-04-09

## [0.2.4] - 2026-04-09

### Added
- `sebastian serve -d`：后台 daemon 模式运行，写 PID 到 `~/.sebastian/sebastian.pid`，
  stdout/stderr 重定向到 `~/.sebastian/logs/sebastian.log`。
- `sebastian stop` / `sebastian status` / `sebastian logs`：配套进程管理命令。
- `sebastian serve` 启动时打印版本、数据目录、日志路径、监听地址等关键信息。
- `scripts/setup-https.sh`：一键检测 Tailscale → 申请证书 → 安装 Caddy → 生成
  Caddyfile → 启动反代。

### Fixed
- 修复退出 App 重新打开历史对话时 thinking（思考过程）折叠块不显示的问题。

### Changed
- `docs/DEPLOYMENT.md` 按使用场景重构为三级：局域网（最简）→ Tailscale 组网（推荐）
  → 云服务器公网部署，每个场景独立可跟随操作。macOS 推荐 Tailscale 桌面版，
  引入 `setup-https.sh` 一键脚本。

## [0.2.3] - 2026-04-09

### Added
- 新增 `docs/DEPLOYMENT.md` 生产部署指南，覆盖 Tailscale（首推）/
  Cloudflare Tunnel / 云服务器 + Caddy 三条路径，全部落到真 Let's Encrypt 证书。

### Changed
- **[breaking]** 默认网关端口由 `8000` 改为 `8823`。`8000` 在开发机与容器
  场景下常被 Django / `python -m http.server` 等占用。已部署的用户升级后需把
  手机 App Server URL 里的 `:8000` 改成 `:8823`，或在 `.env` 里显式设置
  `SEBASTIAN_GATEWAY_PORT=8000` 保留旧行为。

### Fixed
- `release.yml` 的 publish job 不再把 CHANGELOG 内容直接拼进
  `gh release create --notes` 的 shell 命令行：改为写入 `RELEASE_NOTES.md` 后走
  `--notes-file`。旧写法把换行替换成 `%0A`（GitHub release body 不解 URL 编码），
  并且当 changelog 里出现反引号时会被 shell 当成命令替换去执行，v0.2.3 发版就是
  卡在这里。顺带把 `inputs.version` 通过 `env:` 传入而非直接 `${{ }}` 插值，
  避免任何 shell interpolation 风险。

## [0.2.2] - 2026-04-09

### Added
- `sebastian update` 子命令：自托管部署一行命令升级到最新 release。复用
  bootstrap.sh 的 302 重定向 + SHA256 校验流程，下载 tarball 后原地替换
  managed entries（`sebastian/`、`pyproject.toml`、`scripts/`、`README.md`、
  `LICENSE`、`CHANGELOG.md`），保留 `.venv` / `.env` / 数据目录不动，
  失败自动回滚。支持 `--check` 仅查询、`--force` 强制重装、`-y` 跳过确认。

## [0.2.1] - 2026-04-09

### Fixed
- 一键安装脚本在 bash `set -u` 下误把中文全角字符当成变量名的一部分导致
  `unbound variable` 报错：`scripts/install.sh` 的 Python 版本检查和
  `bootstrap.sh` 的 release tag 解析错误提示均用 `${VAR}` 显式包裹。
- `bootstrap.sh` 改走 `github.com/<repo>/releases/latest` 的 302 重定向
  解析最新 tag，避免 `api.github.com` 未认证 60/hr 限流导致 403。

## [0.2.0] - 2026-04-09

### Added
- 完整 CI/CD 工作流（质量门禁 + 手动触发发版）
- 一键安装脚本 `bootstrap.sh` 与 `scripts/install.sh`
- 首次启动 Web 初始化向导（`/setup`）与 CLI 兜底 `sebastian init --headless`
- Android release APK 自动构建与签名
- SHA256SUMS 校验文件随 Release 一起发布

### Changed
- Owner 账号从环境变量迁移到数据库 `users` 表
- JWT 签名密钥从环境变量迁移到 `~/.sebastian/secret.key` 单文件
- `main` 分支启用保护规则，只接受 PR squash merge

### Removed
- 手工生成密码 hash 再填 `.env` 的原始初始化流程
