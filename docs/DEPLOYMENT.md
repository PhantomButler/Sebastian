# Sebastian 部署指南

Sebastian 是一个自托管个人 AI 管家，数据敏感度高（对话、记忆、未来的家庭控制）。
本文给三条**都能拿到真 HTTPS 证书**的部署路径，按**推荐程度排序**。

> **为什么不允许明文 HTTP？**
> Release APK 的 Android Manifest **不包含** `usesCleartextTraffic="true"`，
> 即 `http://` 的 Server URL 会被系统直接拒绝（`Cleartext HTTP traffic not permitted`）。
> 这是刻意的安全默认：JWT token、密码、对话内容不应在任何网段上明文传输。
>
> 局域网开发调试可以用 debug APK（`npx expo run:android`），debug manifest 允许明文。
> **生产部署必须走 HTTPS**，按下面任一方案配置即可。

---

## 路径 A：Tailscale + `tailscale cert`（**首推，个人/家庭场景**）

**适合**：只你自己 + 家人用，要最高隐私，不想买域名不想开公网端口。

**优点**：
- 完全免费（个人 plan 100 设备额度）
- 端到端 WireGuard 加密，Tailscale 自己都看不到你的流量
- **零公网暴露**：Sebastian 只在 tailnet 内可见，攻击面为 0
- 真的 Let's Encrypt 证书（通过 `tailscale cert`），App 系统 CA 直接信任
- 跨场景一致：家里、4G、咖啡馆，手机 App 永远连同一个 URL

**缺点**：
- 手机必须常驻 Tailscale 客户端（耗电极小，可忽略）
- 每台要访问的设备都需加入你的 tailnet

### 步骤

#### 1. 服务器端（假设部署在家里 NAS / 一台常开的 Mac / Linux 机器）

```bash
# 1) 安装 Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# 2) 登录并加入你的 tailnet
sudo tailscale up

# 3) 在 Tailscale 管理后台 https://login.tailscale.com/admin/dns 里：
#    - 启用 MagicDNS
#    - 启用 HTTPS Certificates（在 DNS 页面最下面）
#    这两个必须都开，tailscale cert 才能申请证书

# 4) 查看本机在 tailnet 里的域名
tailscale status
# 例如：sebastian-nas.tail1234.ts.net

# 5) 申请证书（首次会生成私钥 + Let's Encrypt 证书）
sudo tailscale cert sebastian-nas.tail1234.ts.net
# 会输出两个文件：
#   sebastian-nas.tail1234.ts.net.crt
#   sebastian-nas.tail1234.ts.net.key

# 6) 安装 Sebastian（如果还没装）
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
```

#### 2. 让 Sebastian 直接用 HTTPS

最简单的办法是用 `caddy` 做终止反代（仅 4 行 Caddyfile）：

```bash
# 安装 Caddy（Debian/Ubuntu）
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo tee /etc/apt/trusted.gpg.d/caddy.asc
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy.list
sudo apt update && sudo apt install caddy

# macOS
brew install caddy
```

创建 `/etc/caddy/Caddyfile`（Linux）或 `~/Caddyfile`（macOS）：

```caddy
sebastian-nas.tail1234.ts.net {
    tls /path/to/sebastian-nas.tail1234.ts.net.crt /path/to/sebastian-nas.tail1234.ts.net.key

    reverse_proxy 127.0.0.1:8823 {
        # SSE 长连接需要关闭 flush buffer
        flush_interval -1
    }
}
```

> 上例让 Caddy 监听 443（默认 HTTPS 端口），反代到 Sebastian 的 `127.0.0.1:8823`。
> Sebastian 本身应该 bind 回环 `127.0.0.1`（设置 `SEBASTIAN_GATEWAY_HOST=127.0.0.1`），
> 不对外暴露明文端口。
> **不要**让 Sebastian 直接 bind `0.0.0.0:8823`：没有 TLS 就等于明文，App 会拒连。

启动 Caddy：

```bash
# Linux
sudo systemctl enable --now caddy

# macOS
caddy run --config ~/Caddyfile
```

#### 3. 手机端

1. 手机装 Tailscale 客户端，登录同一个账号，加入 tailnet
2. 打开 Sebastian App → Settings → Server URL 填 `https://sebastian-nas.tail1234.ts.net`
3. 登录，完事

---

## 路径 B：Cloudflare Tunnel（**适合想给家人朋友临时访问**）

**适合**：你的家人要访问但不想装 Tailscale；或者你就是想要一个公网 URL。

**优点**：
- 免费（Cloudflare 免费套餐足够个人使用）
- 不用开家里路由器任何端口，对 CGNAT 友好
- 域名由 Cloudflare 托管（免费子域名也可，或绑自己的域名）
- HTTPS 自动 + 自动续期

**缺点**：
- **Cloudflare 是你的 TLS 终端，理论上能看到你的明文流量**。对隐私敏感场景这是一个需要显式接受的 trade-off。
- 需要一个 Cloudflare 账号 + 一个由 CF 托管 DNS 的域名

### 步骤

```bash
# 1) 安装 cloudflared（macOS）
brew install cloudflared

# Linux（Debian/Ubuntu）
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# 2) 登录 Cloudflare
cloudflared tunnel login
# 浏览器弹出 → 选一个你的域名授权

# 3) 创建 tunnel
cloudflared tunnel create sebastian
# 会生成一个 <UUID>.json 凭据文件

# 4) 配置 DNS（把 sebastian.yourdomain.com 指到这个 tunnel）
cloudflared tunnel route dns sebastian sebastian.yourdomain.com

# 5) 创建配置文件 ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml <<EOF
tunnel: sebastian
credentials-file: /path/to/<UUID>.json

ingress:
  - hostname: sebastian.yourdomain.com
    service: http://127.0.0.1:8823
  - service: http_status:404
EOF

# 6) 启动 tunnel（前台跑，或装成 systemd service）
cloudflared tunnel run sebastian
```

手机 App Server URL 填：`https://sebastian.yourdomain.com`。

> Sebastian 本身继续 bind `127.0.0.1:8823`（不暴露公网），cloudflared 作为反向隧道把流量打回来。

---

## 路径 C：云服务器 + 自有域名 + Caddy（**传统，适合已有 VPS**）

**适合**：你已经有一台云服务器 + 一个域名，不想再折腾 Tailscale / Cloudflare。

**优点**：
- 全控制，所有组件都是你自己的
- 没有第三方能看到你的流量（证书是你自己机器申请的）

**缺点**：
- 需要付费的云服务器 + 域名
- 要维护服务器、操心安全更新

### 步骤

```bash
# 在云服务器上

# 1) 安装 Sebastian
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash

# 2) 安装 Caddy（同路径 A）

# 3) 把你的域名 A 记录指向这台服务器的公网 IP

# 4) /etc/caddy/Caddyfile
cat > /etc/caddy/Caddyfile <<EOF
sebastian.example.com {
    reverse_proxy 127.0.0.1:8823 {
        flush_interval -1
    }
}
EOF

# 5) 启动
sudo systemctl enable --now caddy
```

Caddy 会自动通过 ACME 协议向 Let's Encrypt 申请证书并续期。**防火墙 / 安全组**
只需开放 `80`（ACME 验证 + HTTPS 跳转）和 `443`，**不要**开放 8823。

手机 App Server URL 填：`https://sebastian.example.com`。

---

## 对比速查

| | Tailscale | Cloudflare Tunnel | Cloud VPS + Caddy |
|---|---|---|---|
| 费用 | 免费 | 免费 | VPS ~¥30-100/月 + 域名 ~¥60/年 |
| 公网暴露面 | **0** | tunnel endpoint | 443 端口 |
| 谁能看明文 | **没有** | Cloudflare 能看 | 没有 |
| 需要域名 | 否（用 `*.ts.net`） | 是 | 是 |
| 需要路由器改配置 | 否 | 否 | 否（云 VPS 不涉及家用路由器） |
| 非我自己设备访问 | 需加入 tailnet | 公网可达 | 公网可达 |
| 手机端额外 app | Tailscale 常驻 | 无 | 无 |

---

## 常见问题

### Q: 我只想本地开发调试，没必要搞这一套
A: `npx expo run:android` 跑 debug build 即可，debug manifest 允许明文，你可以直接用
`http://10.0.2.2:8823`（模拟器）或 `http://192.168.x.x:8823`（真机局域网）。
**Release APK 和生产场景必须走 HTTPS**。

### Q: SSE 长连接在反代下有问题吗
A: Caddy `flush_interval -1` 已关闭缓冲，cloudflared 原生支持流式响应，
Tailscale 只是 L3 网络不涉及反代。所有三条路径都支持 SSE。

### Q: Tailscale 不是还需要"出口节点"吗
A: 不需要。你的手机和 NAS 都在同一个 tailnet 里，直接对点通信（
或 Tailscale DERP relay 加密中转），不走出口节点。出口节点是把整个设备的
流量都通过 tailnet 中某台机器出网的功能，本场景用不到。

### Q: 公司网络封了 WireGuard 怎么办
A: Tailscale 自动 fallback 到 HTTPS over 443 的 DERP relay。99% 的公司网络
不会封 443。

### Q: 我不想每次部署都手动配 Caddy，能不能让 Sebastian 自己起 HTTPS
A: 未来可能会加，但目前建议用 Caddy——因为 ACME / 证书续期 / SSE 流式
响应处理都是 Caddy 的强项，Sebastian 不应该重复造轮子。
