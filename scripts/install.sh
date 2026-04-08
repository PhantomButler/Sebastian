#!/usr/bin/env bash
# Sebastian installer — runs inside an already-extracted source tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

color_red()  { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }

# 1. OS check
OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  *) color_red "❌ 不支持的操作系统: $OS (仅支持 macOS / Linux)"; exit 1 ;;
esac

# 2. Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
  color_red "❌ 未找到 python3。请先安装 Python 3.12 或更高版本。"
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 12 ]]; }; then
  color_red "❌ Python 版本过低（当前 $PY_VERSION），需要 >= 3.12"
  exit 1
fi
color_grn "✓ Python $PY_VERSION"

# 3. venv
if [[ ! -d .venv ]]; then
  color_ylw "→ 创建虚拟环境 .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
color_grn "✓ 已激活 .venv"

# 4. 安装依赖
color_ylw "→ 安装依赖（可能需要几分钟）"
pip install --upgrade pip >/dev/null
pip install -e .
color_grn "✓ 依赖安装完成"

# 5. 启动
color_grn ""
color_grn "============================================"
color_grn "  即将启动 Sebastian（首次启动会进入初始化向导）"
color_grn "============================================"
color_grn ""
exec sebastian serve
