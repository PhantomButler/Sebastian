# Changelog

本文件记录 Sebastian 的所有重要变更，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 新增 `docs/DEPLOYMENT.md` 生产部署指南，覆盖 Tailscale（首推）/
  Cloudflare Tunnel / 云服务器 + Caddy 三条路径，全部落到真 Let's Encrypt 证书。

### Changed
- **[breaking]** 默认网关端口由 `8000` 改为 `8823`。`8000` 在开发机与容器
  场景下常被 Django / `python -m http.server` 等占用。已部署的用户升级后需把
  手机 App Server URL 里的 `:8000` 改成 `:8823`，或在 `.env` 里显式设置
  `SEBASTIAN_GATEWAY_PORT=8000` 保留旧行为。

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
