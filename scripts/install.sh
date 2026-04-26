#!/usr/bin/env bash
# Sebastian installer — runs inside an already-extracted source tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

color_red()  { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }
color_dim()  { printf "\033[90m%s\033[0m\n" "$*"; }

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
  color_red "❌ Python 版本过低（当前 ${PY_VERSION}），需要 >= 3.12"
  exit 1
fi
color_grn "✓ Python $PY_VERSION"

# 3. venv
if [[ ! -f .venv/bin/activate ]]; then
  color_ylw "→ 创建/修复虚拟环境 .venv"
  python3 -m venv .venv
fi
if [[ ! -f .venv/bin/activate ]]; then
  color_red "❌ 虚拟环境创建失败：缺少 .venv/bin/activate"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
color_grn "✓ 已激活 .venv"

# 4. 安装依赖
color_ylw "→ 安装依赖（可能需要几分钟）"
pip install --upgrade pip >/dev/null
pip install -e .
color_grn "✓ 依赖安装完成"

# 5. 数据目录定位
DATA_ROOT="${SEBASTIAN_DATA_DIR:-$HOME/.sebastian}"
USER_DATA_DIR="${DATA_ROOT}/data"

# 6. 首启向导（数据库不存在则进）
if [[ ! -f "${USER_DATA_DIR}/sebastian.db" ]]; then
  color_ylw "→ 进入初始化向导..."
  if [[ "$OS" == "Linux" && -z "${DISPLAY:-}" ]]; then
    if ! sebastian init --headless; then
      color_red "❌ 初始化向导未完成，安装已中止"
      exit 1
    fi
  else
    # serve 启动时会唤起 web wizard 并在向导完成后自动退出
    if ! sebastian serve; then
      color_red "❌ 初始化向导未完成，安装已中止"
      exit 1
    fi
  fi
else
  color_grn "✓ 检测到已初始化数据，跳过向导"
fi

# 7. 询问是否注册服务
echo ""
read -r -p "是否注册为开机自启服务（systemd / launchd）？[y/N] " ANS
case "${ANS:-N}" in
  y|Y|yes|YES)
    color_ylw "→ 安装系统服务..."
    sebastian service install
    color_grn "✓ 服务已注册"
    REGISTERED=1
    ;;
  *)
    color_dim "已跳过。稍后可执行：sebastian service install"
    REGISTERED=0
    ;;
esac

# 8. 退出指引
echo ""
color_grn "============================================"
color_grn "  Sebastian 安装完成"
color_grn "============================================"
if [[ "${REGISTERED:-0}" -eq 1 ]]; then
  color_dim "  服务状态:  sebastian service status"
  color_dim "  停止服务:  sebastian service stop"
else
  color_dim "  启动服务:  sebastian serve"
  color_dim "  注册服务:  sebastian service install"
fi
color_dim "  日志目录:  ${DATA_ROOT}/logs/"
color_dim "  Android 配置:"
color_dim "    模拟器:  http://10.0.2.2:8823"
color_dim "    真机:    http://<本机局域网IP>:8823"
color_grn "============================================"
