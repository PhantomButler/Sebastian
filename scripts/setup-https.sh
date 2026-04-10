#!/usr/bin/env bash
# Sebastian HTTPS 一键配置（Tailscale + Caddy）
set -euo pipefail

color_red()  { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }

OS="$(uname -s)"

# 1. 检测 Tailscale
if ! command -v tailscale >/dev/null 2>&1; then
  color_red "❌ 未检测到 Tailscale"
  case "$OS" in
    Darwin) color_ylw "   macOS 请从 https://tailscale.com/download/mac 下载桌面版" ;;
    Linux)  color_ylw "   Linux 安装: curl -fsSL https://tailscale.com/install.sh | sh" ;;
  esac
  exit 1
fi

# 2. 检测 Tailscale 是否已连接
if ! tailscale status >/dev/null 2>&1; then
  color_red "❌ Tailscale 未连接，请先登录: tailscale up"
  exit 1
fi
color_grn "✓ Tailscale 已连接"

# 3. 获取本机 tailnet 域名
HOSTNAME="$(tailscale status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["Self"]["DNSName"].rstrip("."))')"
if [[ -z "$HOSTNAME" ]]; then
  color_red "❌ 无法获取 tailnet 域名，请确认 MagicDNS 已启用"
  exit 1
fi
color_grn "✓ 本机 tailnet 域名: $HOSTNAME"

# 4. 申请证书
CERT_DIR="${HOME}/.sebastian/certs"
mkdir -p "$CERT_DIR"
color_ylw "→ 申请 TLS 证书..."
tailscale cert --cert-file "${CERT_DIR}/${HOSTNAME}.crt" --key-file "${CERT_DIR}/${HOSTNAME}.key" "$HOSTNAME"
color_grn "✓ 证书已保存到 ${CERT_DIR}/"

# 5. 检测/安装 Caddy
if ! command -v caddy >/dev/null 2>&1; then
  color_ylw "→ 安装 Caddy..."
  case "$OS" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install caddy
      else
        color_red "❌ 未检测到 Homebrew，请手动安装 Caddy: https://caddyserver.com/docs/install"
        exit 1
      fi
      ;;
    Linux)
      sudo apt-get update -qq && sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo tee /etc/apt/trusted.gpg.d/caddy.asc >/dev/null
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy.list >/dev/null
      sudo apt-get update -qq && sudo apt-get install -y -qq caddy
      ;;
  esac
fi
color_grn "✓ Caddy 已安装"

# 6. 生成 Caddyfile
SEBASTIAN_PORT="${SEBASTIAN_GATEWAY_PORT:-8823}"
case "$OS" in
  Darwin) CADDYFILE="${HOME}/Caddyfile" ;;
  Linux)  CADDYFILE="/etc/caddy/Caddyfile" ;;
esac

color_ylw "→ 写入 Caddyfile: ${CADDYFILE}"

CADDYFILE_CONTENT="${HOSTNAME} {
    tls ${CERT_DIR}/${HOSTNAME}.crt ${CERT_DIR}/${HOSTNAME}.key

    reverse_proxy 127.0.0.1:${SEBASTIAN_PORT} {
        flush_interval -1
    }
}"

if [[ "$OS" == "Linux" ]]; then
  echo "$CADDYFILE_CONTENT" | sudo tee "$CADDYFILE" >/dev/null
else
  echo "$CADDYFILE_CONTENT" > "$CADDYFILE"
fi
color_grn "✓ Caddyfile 已写入"

# 7. 启动 Caddy
color_ylw "→ 启动 Caddy..."
case "$OS" in
  Linux)
    sudo systemctl enable --now caddy
    color_grn "✓ Caddy 已通过 systemd 启动"
    ;;
  Darwin)
    # 停掉可能存在的旧实例
    caddy stop 2>/dev/null || true
    caddy start --config "$CADDYFILE"
    color_grn "✓ Caddy 已在后台启动 (caddy stop 可停止)"
    ;;
esac

echo ""
echo "============================================"
echo "  HTTPS 配置完成！"
echo ""
echo "  访问地址: https://${HOSTNAME}"
echo "  Sebastian 需要监听 127.0.0.1:${SEBASTIAN_PORT}"
echo ""
echo "  在 App Settings → Server URL 填入:"
echo "  https://${HOSTNAME}"
echo "============================================"
echo ""
