# Sebastian 部署指南

本指南帮你把 Sebastian 后端跑起来并让手机 App 连上。
按你的需求选场景，跟着步骤走就行。

---

## 前置：安装 Sebastian 后端

所有场景都需要先装好后端。在你打算运行 Sebastian 的机器上执行：

### 全新安装

```bash
curl -fsSL https://raw.githubusercontent.com/PhantomButler/Sebastian/main/bootstrap.sh | bash
```

脚本会自动：下载最新 release → SHA256 校验 → 解压 → 创建 Python 虚拟环境 → 安装依赖 → 启动首次初始化向导。

首次启动会打开浏览器让你设置主人名称和密码（至少 6 位）。无图形界面的服务器用：

```bash
sebastian init --headless
```

### 后续升级

```bash
sebastian update
```

### 启动/停止

```bash
# 前台运行（开发调试用，Ctrl+C 停止）
sebastian serve

# 后台运行（推荐生产使用）
sebastian serve -d

# 查看状态
sebastian status

# 查看日志
sebastian logs

# 停止
sebastian stop
```

---

## 场景 A：局域网部署（最简单）

**适合**：只在家里用，手机和服务器连同一个 WiFi。

**限制**：
- 离开家（4G / 公司网络）就连不上
- **只能用 debug APK**（`npx expo run:android` 构建），release APK 禁止 HTTP 明文连接

### 步骤

1. **启动后端**

```bash
sebastian serve -d
```

2. **查看本机局域网 IP**

```bash
# macOS
ipconfig getifaddr en0

# Linux
hostname -I | awk '{print $1}'
```

3. **App 连接**

打开 Sebastian App → Settings → Server URL 填入：
```
http://192.168.x.x:8823
```
（把 `192.168.x.x` 换成上一步查到的 IP）

> **注意**：Android 模拟器访问宿主机用 `http://10.0.2.2:8823`，不是 `127.0.0.1`。

---

## 场景 B：Tailscale 组网（推荐）

**适合**：在家、4G、咖啡馆都能连，零公网暴露，端到端加密。

**优点**：
- 免费（个人 plan 100 设备）
- 端到端 WireGuard 加密，无人能看到你的流量
- 真 Let's Encrypt 证书，release APK 直接信任
- 跨场景 URL 不变

**缺点**：
- 手机需常驻 Tailscale 客户端（耗电极小）
- Android 上 Tailscale VPN 会替换其他 VPN（如 Clash），同时只能开一个

### B.1 安装 Tailscale

**macOS（推荐桌面版）**

从 [Tailscale 官网](https://tailscale.com/download/mac) 下载安装，打开后登录你的账号。

**Linux**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**Android**

从 Google Play 搜索安装 Tailscale，登录同一个账号。

> 安装完后，在 [Tailscale 管理后台](https://login.tailscale.com/admin/dns) 确认：
> - MagicDNS 已启用（默认开启，页面显示 "Disable" 按钮说明已开）
> - HTTPS Certificates 已启用（DNS 页面最下方）

### B.2 一键配置 HTTPS

在运行 Sebastian 的机器上：

```bash
# 下载脚本（如果是 bootstrap.sh 安装的，脚本已在 scripts/ 目录）
cd ~/.sebastian/app
./scripts/setup-https.sh
```

脚本自动完成：检测 Tailscale → 获取 tailnet 域名 → 申请 Let's Encrypt 证书 → 安装 Caddy → 生成 Caddyfile → 启动反向代理。

完成后会输出你的 HTTPS 地址，形如 `https://your-machine.tail1234.ts.net`。

<details>
<summary>手动配置（如果不想用脚本）</summary>

```bash
# 1. 查看 tailnet 域名
tailscale status
# 输出形如: your-machine.tail1234.ts.net

# 2. 申请证书（macOS 桌面版不需要 sudo）
tailscale cert your-machine.tail1234.ts.net
# 输出:
#   Wrote public cert to your-machine.tail1234.ts.net.crt
#   Wrote private key to your-machine.tail1234.ts.net.key

# 3. 安装 Caddy
# macOS
brew install caddy
# Linux (Debian/Ubuntu)
sudo apt install caddy

# 4. 写 Caddyfile
# macOS: ~/Caddyfile    Linux: /etc/caddy/Caddyfile
cat > ~/Caddyfile <<EOF
your-machine.tail1234.ts.net {
    tls /path/to/your-machine.tail1234.ts.net.crt /path/to/your-machine.tail1234.ts.net.key

    reverse_proxy 127.0.0.1:8823 {
        flush_interval -1
    }
}
EOF

# 5. 启动 Caddy
# macOS
caddy start --config ~/Caddyfile
# Linux
sudo systemctl enable --now caddy
```

</details>

### B.3 Caddy 管理命令（macOS）

```bash
# 后台启动（推荐，自动 fork 进程）
caddy start --config ~/Caddyfile

# 修改 Caddyfile 后热重载（不断开连接）
caddy reload --config ~/Caddyfile

# 停止
caddy stop

# 前台运行（调试用，Ctrl+C 停止）
caddy run --config ~/Caddyfile
```

> Linux 上 Caddy 通过 systemd 管理：`sudo systemctl start/stop/reload caddy`。

### B.4 启动 Sebastian

```bash
sebastian serve -d
```

确认 Sebastian 监听在 `127.0.0.1:8823`（默认配置），Caddy 负责 HTTPS 终止。

### B.5 App 连接

打开 Sebastian App → Settings → Server URL 填入：
```
https://your-machine.tail1234.ts.net
```

登录，完成。在家、在外面、在咖啡馆，只要手机开着 Tailscale 就能连。

---

## 场景 C：云服务器公网部署

**适合**：已有云服务器 + 域名，或者想让没装 Tailscale 的家人朋友也能访问。

**优点**：
- 所有设备直接访问，无需额外客户端
- 完全自主控制

**缺点**：
- 需要付费的 VPS + 域名
- 服务器暴露在公网，需要维护安全更新

### 步骤

1. **在云服务器上安装 Sebastian**

```bash
curl -fsSL https://raw.githubusercontent.com/PhantomButler/Sebastian/main/bootstrap.sh | bash
```

2. **安装 Caddy**

```bash
# Debian/Ubuntu
sudo apt install caddy
```

3. **域名 DNS 指向服务器**

在你的域名服务商处添加 A 记录，指向服务器公网 IP。

4. **配置 Caddyfile**

```bash
sudo tee /etc/caddy/Caddyfile <<EOF
sebastian.yourdomain.com {
    reverse_proxy 127.0.0.1:8823 {
        flush_interval -1
    }
}
EOF
```

Caddy 会自动通过 ACME 向 Let's Encrypt 申请证书并续期，不需要手动配 TLS。

5. **防火墙只开 80 和 443**

```bash
sudo ufw allow 80
sudo ufw allow 443
# 不要开放 8823
```

6. **启动**

```bash
sudo systemctl enable --now caddy
sebastian serve -d
```

7. **App 连接**

Settings → Server URL：`https://sebastian.yourdomain.com`

### 可选替代：Cloudflare Tunnel（无需域名绑 IP）

如果你的服务器在 NAT/CGNAT 后面无法直接暴露端口，可以用 Cloudflare Tunnel：

```bash
# 安装
brew install cloudflared  # macOS
# 或 Linux: https://github.com/cloudflare/cloudflared/releases

# 登录 + 创建 tunnel
cloudflared tunnel login
cloudflared tunnel create sebastian
cloudflared tunnel route dns sebastian sebastian.yourdomain.com

# 配置
cat > ~/.cloudflared/config.yml <<EOF
tunnel: sebastian
credentials-file: /path/to/<UUID>.json
ingress:
  - hostname: sebastian.yourdomain.com
    service: http://127.0.0.1:8823
  - service: http_status:404
EOF

# 启动
cloudflared tunnel run sebastian
```

> **注意**：Cloudflare Tunnel 的 TLS 在 Cloudflare 边缘终止，理论上 Cloudflare 可以看到你的明文流量。对隐私敏感场景请使用场景 B（Tailscale）。

---

## 对比速查

| | 局域网 | Tailscale | 云服务器 | Cloudflare Tunnel |
|---|---|---|---|---|
| 费用 | 免费 | 免费 | VPS + 域名 | 免费（需域名） |
| 外出能用 | ❌ | ✅ | ✅ | ✅ |
| 公网暴露 | 无 | **无** | 443 端口 | tunnel |
| 谁能看明文 | 局域网内 | **没有** | 没有 | Cloudflare |
| 需要域名 | 否 | 否 | 是 | 是 |
| 手机额外 app | 无 | Tailscale | 无 | 无 |
| APK 要求 | debug | release | release | release |

---

## 常见问题

### 我只想本地开发调试

源码开发用 `./scripts/dev.sh` 一键启动（独立数据目录 `~/.sebastian-dev`，端口 8824，与生产环境隔离）：

```bash
./scripts/dev.sh
# Android 模拟器: http://10.0.2.2:8824
# 真机: http://192.168.x.x:8824
```

`npx expo run:android` 跑 debug build，不需要配 HTTPS。

### SSE 长连接在反代下有问题吗
Caddy `flush_interval -1` 已关闭缓冲，Cloudflare Tunnel 原生支持流式响应，Tailscale 只是 L3 网络不涉及反代。三种方案都支持 SSE。

### Tailscale 证书会过期吗
`tailscale cert` 申请的 Let's Encrypt 证书有效期 90 天。过期后重新运行 `tailscale cert` 或 `./scripts/setup-https.sh` 即可。

### Android 上 Tailscale 和 Clash/代理 冲突
Android 只允许一个 VPN 服务同时运行。开 Tailscale 会断 Clash，反之亦然。macOS 上两者可以共存。

### 公司网络封了 WireGuard
Tailscale 自动 fallback 到 HTTPS over 443 的 DERP relay，99% 的公司网络不会封 443。

### 能不能让 Sebastian 自己起 HTTPS
暂不支持。用 Caddy 做 HTTPS 终止——ACME 证书申请/续期/SSE 流式处理都是 Caddy 的强项，Sebastian 不重复造轮子。
