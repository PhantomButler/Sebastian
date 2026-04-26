<div align="center">

<!-- TODO: 替换为项目 Logo -->
<!-- <picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
  <img alt="Sebastian" src="docs/assets/logo-light.svg" width="200">
</picture> -->

# Sebastian

**你的专属 AI 管家 — 灵感来自黑执事的塞巴斯蒂安，对标钢铁侠贾维斯。**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/PhantomButler/Sebastian/actions/workflows/ci.yml/badge.svg)](https://github.com/PhantomButler/Sebastian/actions/workflows/ci.yml)

[English](README.md)

</div>

---

Sebastian 是一个目标驱动的个人全能 AI 管家系统。你只需告诉它**想要什么**，它会自主分解目标、委派专业子代理执行，甚至在你关掉 App 后依然在后台工作。完全自托管，数据不出本机，Android App 为主要交互入口。

> [!NOTE]
> Sebastian 的定位是 **个人与家庭使用** —— 不是企业产品。跑在你自己的机器上，数据永远在你手里。

---

## 演示

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/asset/coding_test.gif" alt="Forge Agent 自主编程演示">
      <br><sub><b>Forge Agent — 自主编程与调试</b></sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/asset/memory_test.gif" alt="记忆系统演示">
      <br><sub><b>记忆系统 — 跨会话记住你的偏好</b></sub>
    </td>
  </tr>
</table>

---

## ✨ 核心特性

- 🏠 **自托管，隐私优先** — 跑在你自己的机器上，不依赖云服务，数据不外泄。
- 🤖 **三层 Agent 架构** — Sebastian（总管家）委派组长，组长分派组员。你的目标被**执行**，而不只是被回复。
- 📱 **Android 原生客户端** — 流式响应实时显示、思考过程可视化、工具调用卡片。Kotlin + Jetpack Compose 构建。
- 🔧 **零配置扩展** — 新增工具、MCP 服务、Skill、子代理只需创建文件并重启，无需改动核心代码。
- 🧠 **持久记忆系统** — 记住你的偏好与历史对话。画像事实、情景记忆、常驻快照每轮固定注入，越用越懂你。
- 🔒 **权限与审批机制** — 敏感操作需要主人批准。三档风险分类（低 / 模型判断 / 高风险）。
- 🚀 **动态工具工厂** — 代理发现缺少工具时，可以自己编写、沙箱测试、注册永久使用 —— 全自动。

## 已实现功能

- ✅ 实时流式对话，思考过程与工具调用可视化
- ✅ 三层 Agent 编排 — 委派、分派、Stalled 检测
- ✅ 子代理管理与 Session 监控
- ✅ 敏感操作审批通知
- ✅ LLM 服务商配置（Anthropic、OpenAI、自定义 base URL）
- ✅ 持久记忆 — 用户画像、情景历史、常驻快照
- ✅ 会话与任务历史，支持 Timeline 历史恢复
- ✅ 一键安装、升级与自动回滚
- ✅ 无头服务器初始化

## ⚡ 快速开始

### 安装服务端（macOS / Linux）

```bash
curl -fsSL https://raw.githubusercontent.com/PhantomButler/Sebastian/main/bootstrap.sh | bash
```

这条命令安装的是 Sebastian 后端服务——自动下载最新 Release、校验 SHA256 指纹、安装依赖、启动首次初始化向导。打开终端显示的 URL，设置主人名字和密码即可。

### 安装 Android App

从 [Releases 页面](https://github.com/PhantomButler/Sebastian/releases) 下载 `sebastian-app-v*.apk`，安装到手机。

首次打开后，进入 **Settings → Connection** 填写服务器地址：`http://<电脑局域网 IP>:8823`

### 配置 AI 服务

安装完成后，打开 Android App 进入 **Settings → Providers**，添加你的 LLM 服务商（Anthropic、OpenAI 等）。API Key 加密存储在本机，不会发送到任何云端服务。

### 手动安装（偏执模式）

```bash
# 1. 下载最新 release 并校验
curl -LO https://github.com/PhantomButler/Sebastian/releases/latest/download/SHA256SUMS
TAR=$(grep '\.tar\.gz$' SHA256SUMS | awk '{print $2}')
curl -LO "https://github.com/PhantomButler/Sebastian/releases/latest/download/${TAR}"
shasum -a 256 -c SHA256SUMS --ignore-missing

# 2. 解压并运行
tar xzf "${TAR}"
cd "${TAR%.tar.gz}"
./scripts/install.sh
```

## 🧭 常用命令

```bash
sebastian serve                              # 启动服务（首次启动会打开初始化向导）
sebastian serve --host 0.0.0.0 --port 8823   # 自定义绑定地址
sebastian init --headless                    # 无头初始化（适用于无图形界面的服务器）
sebastian update                             # 升级到最新版本（失败自动回滚）
sebastian update --check                     # 仅检查更新，不执行升级
```

## 🖥️ 作为系统服务运行

安装完成后，可以注册为开机自启的系统服务：

```bash
sebastian service install   # 注册并启动服务
sebastian service status    # 查看服务状态
sebastian service stop      # 停止服务
sebastian service uninstall # 卸载服务
```

- **macOS**: `~/Library/LaunchAgents/com.sebastian.plist`
- **Linux**: `~/.config/systemd/user/sebastian.service`（用户级，无需 sudo）

Linux 用户如需开机自启，还需要开启 linger：

```bash
sudo loginctl enable-linger $USER
```

### 数据目录结构

```
~/.sebastian/
  app/         # 安装树（sebastian update 只动这里）
  data/        # 用户数据：sebastian.db / secret.key / workspace / extensions
  logs/        # 日志文件
  run/         # PID 文件 + 升级回滚备份
  .layout-v2   # 迁移标记
```

从旧版本升级？`sebastian serve` 启动时会自动将旧版平铺结构迁移到此目录布局。

## 🏗️ 架构

<div align="center">
  <a href="docs/architecture/diagrams/system-overview.html">
    <img src="docs/asset/sebastian_architecture_system-overview.png" alt="Sebastian 系统架构总览">
  </a>
  <p><sub><a href="docs/architecture/diagrams/system-overview.html">↗ 查看完整交互架构图</a></sub></p>
</div>

所有 Agent 继承自 `BaseAgent` — 共享工具系统、流式循环、记忆访问。Sebastian 在此基础上增加目标分解和委派能力；组长增加领域工具和组员分派能力。

### 城堡管理体系

灵感来自管家制度：用户是城堡主人，Sebastian 是总管家，第二层是各部门组长（编码、股票、生活），第三层是组长安排的组员。

```
用户（城堡主人）
│
├── Sebastian（总管家）
│     └── 理解主人意图，分解目标，委派组长
│
├── Forge（编码组长）
│     ├── 简单任务自己干，复杂任务安排组员
│     └── 组员最多 5 个同时工作
│
├── 骑士团长（股票组长，计划中）
│     └── ...
└── ...
```

日常模式：你只和 Sebastian 对话，它自动协调组长执行。磨合期可直接与组长对话或干预任意 session。

完整架构设计见 [docs/architecture/spec/](docs/architecture/spec/)。

## 🗺️ 路线图

| 阶段 | 重点 | 状态 |
|------|------|------|
| **Phase 1** | 核心引擎、三层 Agent、Android App、Gateway、SSE | ✅ 已完成 |
| **Phase 2** | 记忆系统、Forge Agent、推送通知、Skills | 🔄 进行中 |
| **Phase 3** | 语音管道、iOS App、触发器引擎 | 📋 计划中 |
| **Phase 4** | 高级触发器、更多子代理、Web UI 完善 | 📋 计划中 |
| **Phase 5** | 生物识别、多因素权限、审计日志 | 📋 计划中 |

## 📚 文档

| 文档 | 说明 |
|------|------|
| [架构设计](docs/architecture/spec/INDEX.md) | 完整系统设计 — 数据模型、协议、Agent 层级 |
| [后端指南](sebastian/README.md) | Python 后端模块地图与开发入口 |
| [Android App 指南](ui/mobile-android/README.md) | Kotlin App 架构、导航、SSE 连接机制 |
| [更新日志](CHANGELOG.md) | 版本历史与 Breaking Changes |
| [贡献指南](CONTRIBUTING.md) | 开发环境搭建、代码规范、PR 工作流 |

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。
