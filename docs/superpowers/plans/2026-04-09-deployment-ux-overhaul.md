# 部署体验优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Sebastian 的部署体验对小白友好：`sebastian serve` 支持后台运行并打印关键信息，DEPLOYMENT.md 按使用场景重构为可复制粘贴的分步指南，HTTPS 配置脚本化。

**Architecture:** 三块改动相互独立——(1) CLI 层 `sebastian serve` 增加 daemon 模式 + 启动 banner + stop/status/logs 子命令，(2) DEPLOYMENT.md 按场景（局域网 → Tailscale → 云服务器）重写，macOS/Linux 分别标注，(3) 新增 `scripts/setup-https.sh` 一键配置 Tailscale + Caddy。

**Tech Stack:** Python (Typer CLI), Bash (setup script), Markdown (docs)

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `sebastian/main.py` | 修改 | 新增 `--daemon/-d` 参数 + 启动 banner + stop/status/logs 子命令 |
| `sebastian/cli/daemon.py` | 创建 | PID 管理 + 进程 fork + 日志重定向 |
| `tests/unit/test_daemon.py` | 创建 | daemon 工具函数单元测试 |
| `docs/DEPLOYMENT.md` | 重写 | 按场景分章，小白友好 |
| `scripts/setup-https.sh` | 创建 | 一键 Tailscale cert + Caddy 配置 |
| `CHANGELOG.md` | 修改 | 记录变更 |

---

## Task 1: daemon 工具模块 `sebastian/cli/daemon.py`

**Files:**
- Create: `sebastian/cli/daemon.py`
- Create: `tests/unit/test_daemon.py`

封装 PID 文件管理和进程状态查询，不含 fork 逻辑（fork 在 serve 命令里做）。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_daemon.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sebastian.cli.daemon import read_pid, write_pid, remove_pid, is_running


def test_write_and_read_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "sebastian.pid"
    write_pid(pid_file, 12345)
    assert read_pid(pid_file) == 12345


def test_read_pid_missing(tmp_path: Path) -> None:
    pid_file = tmp_path / "sebastian.pid"
    assert read_pid(pid_file) is None


def test_remove_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "sebastian.pid"
    write_pid(pid_file, 12345)
    remove_pid(pid_file)
    assert not pid_file.exists()


def test_is_running_current_process() -> None:
    assert is_running(os.getpid()) is True


def test_is_running_nonexistent() -> None:
    # PID 99999 大概率不存在
    assert is_running(99999) is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_daemon.py -v
```

预期：FAIL，`ModuleNotFoundError: No module named 'sebastian.cli.daemon'`

- [ ] **Step 3: 实现 daemon.py**

```python
# sebastian/cli/daemon.py
from __future__ import annotations

import os
import signal
from pathlib import Path


def pid_path(data_dir: Path) -> Path:
    """Return the standard PID file path."""
    return data_dir / "sebastian.pid"


def write_pid(path: Path, pid: int | None = None) -> None:
    """Write current (or given) PID to file."""
    path.write_text(str(pid or os.getpid()))


def read_pid(path: Path) -> int | None:
    """Read PID from file. Returns None if missing or corrupt."""
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_pid(path: Path) -> None:
    """Remove PID file if it exists."""
    path.unlink(missing_ok=True)


def is_running(pid: int) -> bool:
    """Check whether a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_process(path: Path) -> bool:
    """Send SIGTERM to the process recorded in PID file. Returns True if killed."""
    pid = read_pid(path)
    if pid is None or not is_running(pid):
        remove_pid(path)
        return False
    os.kill(pid, signal.SIGTERM)
    remove_pid(path)
    return True
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_daemon.py -v
```

- [ ] **Step 5: Commit**

```bash
git add sebastian/cli/daemon.py tests/unit/test_daemon.py
git commit -m "feat(cli): 新增 daemon PID 管理工具模块"
```

---

## Task 2: `sebastian serve` 增加启动 banner + daemon 模式

**Files:**
- Modify: `sebastian/main.py:9-20`
- Modify: `sebastian/gateway/app.py:181` (在 logger.info 前加一行 print banner)

改动点：
1. `serve` 加 `--daemon/-d` 参数
2. 启动前打印 banner（版本、数据目录、日志目录、监听地址、PID）
3. daemon 模式下 fork + 重定向 stdout/stderr 到日志文件 + 写 PID

- [ ] **Step 1: 修改 `sebastian/main.py` 的 serve 命令**

```python
@app.command()
def serve(
    host: str = typer.Option(None, help="Override gateway host"),
    port: int = typer.Option(None, help="Override gateway port"),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)"),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run in background"),
) -> None:
    """Start the Sebastian gateway server."""
    import importlib.metadata

    from sebastian.config import ensure_data_dir, settings

    ensure_data_dir()
    h = host or settings.sebastian_gateway_host
    p = port or settings.sebastian_gateway_port

    version = importlib.metadata.version("sebastian")
    log_dir = settings.data_dir / "logs"
    log_file = log_dir / "main.log"

    print()
    print("=" * 50)
    print(f"  Sebastian v{version}")
    print(f"  数据目录:  {settings.data_dir}")
    print(f"  日志文件:  {log_file}")
    print(f"  监听地址:  http://{h}:{p}")
    if daemon:
        print(f"  运行模式:  后台 (PID 文件: {settings.data_dir / 'sebastian.pid'})")
    else:
        print("  运行模式:  前台 (Ctrl+C 停止)")
    print("=" * 50)
    print()

    if daemon:
        import sys

        from sebastian.cli.daemon import pid_path, read_pid, is_running, write_pid

        pf = pid_path(settings.data_dir)
        existing = read_pid(pf)
        if existing and is_running(existing):
            typer.echo(f"❌ Sebastian 已在运行 (PID {existing})")
            raise typer.Exit(code=1)

        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = log_dir / "sebastian.log"

        pid = os.fork()
        if pid > 0:
            # Parent: print info and exit
            typer.echo(f"✓ Sebastian 已在后台启动 (PID {pid})")
            typer.echo(f"  查看日志: sebastian logs")
            typer.echo(f"  停止服务: sebastian stop")
            raise typer.Exit(code=0)

        # Child: detach
        os.setsid()
        fd = os.open(str(stdout_log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(fd, sys.stdout.fileno())
        os.dup2(fd, sys.stderr.fileno())
        os.close(fd)
        write_pid(pf)

    uvicorn.run("sebastian.gateway.app:app", host=h, port=p, reload=reload)
```

注意：需要在文件顶部加 `import os`。

- [ ] **Step 2: 本地验证**

```bash
# 前台模式 — 确认 banner 打印
sebastian serve --port 8899
# 看到 banner 后 Ctrl+C

# daemon 模式
sebastian serve -d --port 8899
# 确认输出 PID 并且进程在后台
curl http://127.0.0.1:8899/api/v1/health
kill $(cat ~/.sebastian/sebastian.pid)
```

- [ ] **Step 3: Commit**

```bash
git add sebastian/main.py
git commit -m "feat(cli): serve 启动打印 banner + 支持 -d daemon 后台运行"
```

---

## Task 3: 新增 `sebastian stop` / `sebastian status` / `sebastian logs` 子命令

**Files:**
- Modify: `sebastian/main.py`

三个简单命令，依赖 Task 1 的 daemon 工具。

- [ ] **Step 1: 在 main.py 新增三个命令**

```python
@app.command()
def stop() -> None:
    """Stop the background Sebastian server."""
    from sebastian.cli.daemon import pid_path, stop_process
    from sebastian.config import settings

    pf = pid_path(settings.data_dir)
    if stop_process(pf):
        typer.echo("✓ Sebastian 已停止")
    else:
        typer.echo("Sebastian 未在运行")


@app.command()
def status() -> None:
    """Check whether Sebastian is running."""
    from sebastian.cli.daemon import is_running, pid_path, read_pid
    from sebastian.config import settings

    pf = pid_path(settings.data_dir)
    pid = read_pid(pf)
    if pid and is_running(pid):
        typer.echo(f"✓ Sebastian 正在运行 (PID {pid})")
    else:
        typer.echo("Sebastian 未在运行")
        if pid:
            from sebastian.cli.daemon import remove_pid
            remove_pid(pf)


@app.command()
def logs(
    follow: bool = typer.Option(True, "--follow/--no-follow", "-f", help="实时跟踪"),
    lines: int = typer.Option(50, "--lines", "-n", help="显示最后 N 行"),
) -> None:
    """Tail Sebastian log file."""
    import subprocess

    from sebastian.config import settings

    log_file = settings.data_dir / "logs" / "main.log"
    if not log_file.exists():
        typer.echo(f"日志文件不存在: {log_file}")
        raise typer.Exit(code=1)
    cmd = ["tail", f"-n{lines}"]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_file))
    subprocess.run(cmd)
```

- [ ] **Step 2: 验证**

```bash
sebastian serve -d
sebastian status   # 显示 PID
sebastian logs --no-follow -n 5  # 显示最后 5 行
sebastian stop     # 停止
sebastian status   # 未在运行
```

- [ ] **Step 3: Commit**

```bash
git add sebastian/main.py
git commit -m "feat(cli): 新增 stop/status/logs 子命令"
```

---

## Task 4: 创建 `scripts/setup-https.sh`

**Files:**
- Create: `scripts/setup-https.sh`

一键检测 Tailscale + 申请证书 + 安装/配置 Caddy 的脚本。macOS 和 Linux 分别处理。

- [ ] **Step 1: 编写脚本**

```bash
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
    # 停掉可能存在的旧进程
    pkill -f "caddy run" 2>/dev/null || true
    nohup caddy run --config "$CADDYFILE" >/tmp/caddy.log 2>&1 &
    color_grn "✓ Caddy 已在后台启动 (日志: /tmp/caddy.log)"
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
```

- [ ] **Step 2: 设置可执行权限并测试**

```bash
chmod +x scripts/setup-https.sh
# 在已配好 Tailscale 的 Mac 上运行
./scripts/setup-https.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/setup-https.sh
git commit -m "feat: 新增 setup-https.sh 一键配置 Tailscale + Caddy HTTPS"
```

---

## Task 5: 重写 `docs/DEPLOYMENT.md`

**Files:**
- Modify: `docs/DEPLOYMENT.md`（完整重写）

按场景分章，每个场景独立完整可跟随操作：

### 文档结构

```
# Sebastian 部署指南

## 前置：安装 Sebastian 后端
  （所有场景通用的一步）

## 场景 A：局域网部署（最简单，在家用）
  - 适合谁 / 限制
  - 步骤（启动后端 → App 填局域网 IP → 完事）
  - 注意：只能 debug APK，release APK 不支持 HTTP

## 场景 B：Tailscale 组网（推荐，随时随地访问）
  - 适合谁 / 优缺点
  - 步骤
    - B.1 安装 Tailscale
      - macOS: 推荐官网下载桌面版（附链接）
      - Linux: curl 一行安装
      - Android: Play Store 下载
    - B.2 一键配置 HTTPS: ./scripts/setup-https.sh
    - B.3 启动 Sebastian: sebastian serve -d
    - B.4 App 连接: 填 https://xxx.tail1234.ts.net
  - FAQ (证书续期 / 公司网络 / VPN 冲突)

## 场景 C：云服务器公网部署
  - 适合谁 / 优缺点
  - 步骤（VPS + 域名 + Caddy ACME 自动证书）

## 对比速查表

## 常见问题
```

- [ ] **Step 1: 重写 DEPLOYMENT.md**

完整内容见下方。关键改动：
- "安装 Sebastian"从各场景抽到前置通用步骤
- 场景 A（局域网）是全新内容，覆盖最简单的本地使用
- 场景 B（Tailscale）拆分 macOS / Linux 子步骤，推荐桌面版，引入 `setup-https.sh`
- 场景 C（云服务器）精简，Cloudflare Tunnel 作为"可选替代"附在 C 里而非独立章节
- 所有命令可直接复制粘贴，预期输出写在命令后面

```markdown
# Sebastian 部署指南

本指南帮你把 Sebastian 后端跑起来并让手机 App 连上。
按你的需求选场景，跟着步骤走就行。

---

## 前置：安装 Sebastian 后端

所有场景都需要先装好后端。在你打算运行 Sebastian 的机器上执行：

### 全新安装

\```bash
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
\```

脚本会自动：下载最新 release → SHA256 校验 → 解压 → 创建 Python 虚拟环境 → 安装依赖 → 启动首次初始化向导。

首次启动会打开浏览器让你设置主人名称和密码（至少 6 位）。无图形界面的服务器用：

\```bash
sebastian init --headless
\```

### 后续升级

\```bash
sebastian update
\```

### 启动/停止

\```bash
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
\```

---

## 场景 A：局域网部署（最简单）

**适合**：只在家里用，手机和服务器连同一个 WiFi。

**限制**：
- 离开家（4G / 公司网络）就连不上
- **只能用 debug APK**（`npx expo run:android` 构建），release APK 禁止 HTTP 明文连接

### 步骤

1. **启动后端**

\```bash
sebastian serve -d
\```

2. **查看本机局域网 IP**

\```bash
# macOS
ipconfig getifaddr en0

# Linux
hostname -I | awk '{print $1}'
\```

3. **App 连接**

打开 Sebastian App → Settings → Server URL 填入：
\```
http://192.168.x.x:8823
\```
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

\```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
\```

**Android**

从 Google Play 搜索安装 Tailscale，登录同一个账号。

> 安装完后，在 [Tailscale 管理后台](https://login.tailscale.com/admin/dns) 确认：
> - MagicDNS 已启用（默认开启，页面显示"Disable"按钮说明已开）
> - HTTPS Certificates 已启用（DNS 页面最下方）

### B.2 一键配置 HTTPS

在运行 Sebastian 的机器上：

\```bash
# 下载脚本（如果是 bootstrap.sh 安装的，脚本已在 scripts/ 目录）
cd ~/.sebastian/app
./scripts/setup-https.sh
\```

脚本自动完成：检测 Tailscale → 获取 tailnet 域名 → 申请 Let's Encrypt 证书 → 安装 Caddy → 生成 Caddyfile → 启动反向代理。

完成后会输出你的 HTTPS 地址，形如 `https://your-machine.tail1234.ts.net`。

<details>
<summary>手动配置（如果不想用脚本）</summary>

\```bash
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
caddy run --config ~/Caddyfile
# Linux
sudo systemctl enable --now caddy
\```

</details>

### B.3 启动 Sebastian

\```bash
sebastian serve -d
\```

确认 Sebastian 监听在 `127.0.0.1:8823`（默认配置），Caddy 负责 HTTPS 终止。

### B.4 App 连接

打开 Sebastian App → Settings → Server URL 填入：
\```
https://your-machine.tail1234.ts.net
\```

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

\```bash
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
\```

2. **安装 Caddy**

\```bash
# Debian/Ubuntu
sudo apt install caddy
\```

3. **域名 DNS 指向服务器**

在你的域名服务商处添加 A 记录，指向服务器公网 IP。

4. **配置 Caddyfile**

\```bash
sudo tee /etc/caddy/Caddyfile <<EOF
sebastian.yourdomain.com {
    reverse_proxy 127.0.0.1:8823 {
        flush_interval -1
    }
}
EOF
\```

Caddy 会自动通过 ACME 向 Let's Encrypt 申请证书并续期，不需要手动配 TLS。

5. **防火墙只开 80 和 443**

\```bash
sudo ufw allow 80
sudo ufw allow 443
# 不要开放 8823
\```

6. **启动**

\```bash
sudo systemctl enable --now caddy
sebastian serve -d
\```

7. **App 连接**

Settings → Server URL：`https://sebastian.yourdomain.com`

### 可选替代：Cloudflare Tunnel（无需域名绑 IP）

如果你的服务器在 NAT/CGNAT 后面无法直接暴露端口，可以用 Cloudflare Tunnel：

\```bash
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
\```

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
`npx expo run:android` 跑 debug build，直接用 `http://10.0.2.2:8823`（模拟器）或 `http://192.168.x.x:8823`（真机）。不需要配 HTTPS。

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
```

- [ ] **Step 2: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs: 按场景重写部署指南（局域网/Tailscale/云服务器），小白友好"
```

---

## Task 6: CHANGELOG 记录

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 在 `[Unreleased]` 下添加**

```markdown
### Added
- `sebastian serve -d`：后台 daemon 模式运行，写 PID 到 `~/.sebastian/sebastian.pid`，
  stdout/stderr 重定向到 `~/.sebastian/logs/sebastian.log`。
- `sebastian stop` / `sebastian status` / `sebastian logs`：配套管理命令。
- `sebastian serve` 启动时打印版本、数据目录、日志路径、监听地址等关键信息 banner。
- `scripts/setup-https.sh`：一键检测 Tailscale → 申请证书 → 安装 Caddy → 生成
  Caddyfile → 启动反代。

### Changed
- `docs/DEPLOYMENT.md` 按使用场景重构为三级：局域网（最简）→ Tailscale 组网（推荐）
  → 云服务器公网部署，每个场景独立可跟随操作。macOS 推荐 Tailscale 桌面版，
  引入 `setup-https.sh` 一键脚本。
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG 记录部署体验优化"
```
