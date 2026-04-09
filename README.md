# Sebastian

一个目标驱动的个人全能 AI 管家系统，灵感来自黑执事的塞巴斯蒂安与 Overlord 的 Sebas Tian，对标钢铁侠贾维斯愿景。

自托管部署，Android App 为主要交互入口，支持个人主用 + 受控多用户（家人/访客）。

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.12+，FastAPI，SQLAlchemy（async），SQLite |
| AI | Anthropic Claude API，多 LLM 提供商适配 |
| 移动端 | React Native（Expo），Android 优先 |
| 通信 | REST + SSE 事件流，A2A 内部协议 |
| 部署 | Docker Compose，自托管 |

## 快速开始

### 一键安装（推荐，macOS / Linux）

```bash
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
```

脚本会：

1. 检查 Python 3.12+ 等依赖
2. 从最新 GitHub Release 下载源码包与 `SHA256SUMS`
3. 校验文件指纹
4. 解压到 `~/.sebastian/app/`
5. 创建 venv、安装依赖、启动首次初始化向导

启动后浏览器会被唤起到 `http://127.0.0.1:8000/setup?token=...`，填入主人名字与登录密码即可。

### 升级到新版本

```bash
sebastian update            # 拉取最新 release，校验、原地替换、自动回滚
sebastian update --check    # 只检查不升级
```

升级流程会保留 `.venv` / `.env` / `~/.sebastian/` 数据目录不动，最近 3 个旧版本会留作备份。

### 手动安装（偏执模式）

```bash
# 1. 下载最新 release
curl -LO https://github.com/Jaxton07/Sebastian/releases/latest/download/SHA256SUMS
TAR=$(grep '\.tar\.gz$' SHA256SUMS | awk '{print $2}')
curl -LO "https://github.com/Jaxton07/Sebastian/releases/latest/download/${TAR}"

# 2. 校验 SHA256
shasum -a 256 -c SHA256SUMS --ignore-missing

# 3. 解压并运行
tar xzf "${TAR}"
cd "${TAR%.tar.gz}"
./scripts/install.sh
```

### 从源码开发

```bash
git clone git@github.com:Jaxton07/Sebastian.git
cd Sebastian
pip install -e ".[dev,memory]"
sebastian serve
```

### Android App

从 [Releases 页面](https://github.com/Jaxton07/Sebastian/releases) 下载 `sebastian-app-v*.apk`，通过 `adb install` 或直接传到手机安装。

首次打开 App → Settings → 填写 Server URL：

- 模拟器（宿主机）：`http://10.0.2.2:8000`
- 同局域网真机：`http://<电脑局域网 IP>:8000`

### iOS

本版本不分发 iOS 构建。开发者可通过 Xcode 自行 build：

```bash
cd ui/mobile
npm install --legacy-peer-deps
npx expo run:ios        # 需要 macOS + Xcode
```

移动端开发详情见 [ui/mobile/README.md](ui/mobile/README.md)。

## 文档

- [CLAUDE.md](CLAUDE.md) — 开发规范、环境配置、工作流指引
- [INDEX.md](INDEX.md) — 代码库模块索引（供 Claude Code 导航用）
- [docs/](docs/) — 架构设计文档与 Spec
