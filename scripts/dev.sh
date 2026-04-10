#!/usr/bin/env bash
# Sebastian 开发环境启动脚本
# 使用独立数据目录 (~/.sebastian-dev)，避免与生产环境冲突
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

color_red()  { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }
color_dim()  { printf "\033[90m%s\033[0m\n" "$*"; }

# ── 开发环境配置 ──
export SEBASTIAN_DATA_DIR="${SEBASTIAN_DATA_DIR:-$HOME/.sebastian-dev}"
export SEBASTIAN_GATEWAY_PORT="${SEBASTIAN_GATEWAY_PORT:-8824}"
export SEBASTIAN_GATEWAY_HOST="${SEBASTIAN_GATEWAY_HOST:-127.0.0.1}"

# 加载 .env 中不冲突的变量（如 ANTHROPIC_API_KEY）
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  while IFS='=' read -r key value; do
    # 跳过注释和空行
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    # 不覆盖已设置的变量（开发配置优先）
    if [[ -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < "${PROJECT_ROOT}/.env"
fi

# ── 检查 venv ──
if [[ -d "${PROJECT_ROOT}/.venv" ]]; then
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.venv/bin/activate"
elif [[ -z "${VIRTUAL_ENV:-}" ]]; then
  color_ylw "⚠ 未检测到 .venv 且未激活虚拟环境，使用系统 Python"
fi

# ── 首次初始化提示 ──
if [[ ! -d "${SEBASTIAN_DATA_DIR}" ]]; then
  color_ylw "→ 首次使用开发数据目录: ${SEBASTIAN_DATA_DIR}"
  color_ylw "  启动后会进入初始化向导，需要设置 owner 账号和 LLM Provider"
  color_dim "  Android 模拟器连接地址: http://10.0.2.2:${SEBASTIAN_GATEWAY_PORT}"
  echo ""
fi

# ── 启动信息 ──
color_grn "━━━ Sebastian DEV 模式 ━━━"
color_dim "  数据目录: ${SEBASTIAN_DATA_DIR}"
color_dim "  端口:     ${SEBASTIAN_GATEWAY_PORT}"
color_dim "  模拟器:   http://10.0.2.2:${SEBASTIAN_GATEWAY_PORT}"
color_grn "━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

exec sebastian serve --reload
