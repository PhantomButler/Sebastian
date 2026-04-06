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

```bash
# 安装后端依赖
pip install -e ".[dev,memory]"

# 配置环境变量（参考 .env.example）
cp .env.example .env

# 启动后端网关
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8000 --reload
```

移动端开发见 [ui/mobile/README.md](ui/mobile/README.md)。

## 文档

- [CLAUDE.md](CLAUDE.md) — 开发规范、环境配置、工作流指引
- [INDEX.md](INDEX.md) — 代码库模块索引（供 Claude Code 导航用）
- [docs/](docs/) — 架构设计文档与 Spec
