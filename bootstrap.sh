#!/usr/bin/env bash
# Sebastian one-line installer.
# Usage: curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
set -euo pipefail

REPO="Jaxton07/Sebastian"
INSTALL_DIR="${SEBASTIAN_INSTALL_DIR:-$HOME/.sebastian/app}"

color_red() { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn() { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw() { printf "\033[33m%s\033[0m\n" "$*"; }

cat <<'BANNER'
============================================
  Sebastian 一键安装脚本
  动作清单：
    1. 检查系统依赖
    2. 从 GitHub 获取最新 release 信息
    3. 下载 sebastian-backend-<ver>.tar.gz 与 SHA256SUMS
    4. 校验 SHA256 指纹
    5. 解压到 $INSTALL_DIR
    6. 运行 ./scripts/install.sh（venv + 依赖 + 首启向导）
  按 Ctrl+C 随时中止
============================================
BANNER

# 1. 依赖检查
for cmd in curl tar shasum python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    color_red "❌ 缺少依赖命令: $cmd"
    exit 1
  fi
done
color_grn "✓ 系统依赖齐全"

# 2. 最新 release tag
color_ylw "→ 查询最新 release..."
LATEST_JSON="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest")"
LATEST_TAG="$(printf '%s' "$LATEST_JSON" | grep -o '"tag_name":[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
if [[ -z "$LATEST_TAG" ]]; then
  color_red "❌ 无法解析最新 release tag"
  exit 1
fi
color_grn "✓ 最新版本: $LATEST_TAG"

TAR_NAME="sebastian-backend-${LATEST_TAG}.tar.gz"
TAR_URL="https://github.com/${REPO}/releases/download/${LATEST_TAG}/${TAR_NAME}"
SUMS_URL="https://github.com/${REPO}/releases/download/${LATEST_TAG}/SHA256SUMS"

# 3. 下载到临时目录
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

color_ylw "→ 下载 $TAR_NAME ..."
curl -fsSL "$TAR_URL" -o "${TMPDIR}/${TAR_NAME}"
color_ylw "→ 下载 SHA256SUMS ..."
curl -fsSL "$SUMS_URL" -o "${TMPDIR}/SHA256SUMS"

# 4. 校验
color_ylw "→ 校验 SHA256 指纹..."
(
  cd "$TMPDIR"
  shasum -a 256 -c SHA256SUMS --ignore-missing 2>&1 | grep -E "^${TAR_NAME}: OK$" >/dev/null \
    || { color_red "❌ SHA256 校验失败，已中止以防供应链污染"; exit 1; }
)
color_grn "✓ SHA256 校验通过"

# 5. 解压
color_ylw "→ 解压到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
  color_ylw "⚠ 目标目录非空，已有内容将被覆盖（仅同名文件）"
fi
tar xzf "${TMPDIR}/${TAR_NAME}" -C "$INSTALL_DIR" --strip-components=1

# 6. 运行 install.sh
cd "$INSTALL_DIR"
if [[ ! -x scripts/install.sh ]]; then
  color_red "❌ 解压后未找到 scripts/install.sh"
  exit 1
fi
color_grn "✓ 开始执行安装脚本"
exec ./scripts/install.sh
