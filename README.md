<div align="center">

<!-- TODO: Replace with project logo when ready -->
<!-- <picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
  <img alt="Sebastian" src="docs/assets/logo-light.svg" width="200">
</picture> -->

# Sebastian

**Your self-hosted AI butler — inspired by the indefatigable Sebastian Michaelis.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/Jaxton07/Sebastian/actions/workflows/ci.yml/badge.svg)](https://github.com/Jaxton07/Sebastian/actions/workflows/ci.yml)

[简体中文](README.zh-CN.md)

</div>

---

Sebastian is a goal-driven personal AI butler system. Tell it what you want — it figures out the *how*, decomposes goals, delegates to specialized sub-agents, and keeps working even after you close the app. Self-hosted, private by default, with an Android app as the primary interface.

> [!NOTE]
> Sebastian is designed for **personal and family use** — it's not an enterprise product. Self-hosted on your own machine, your data never leaves your control.

<!-- TODO: Add app screenshots when available -->
<!--
## Screenshots

<div align="center">
  <img src="docs/assets/screenshot-chat.png" width="240" alt="Chat Screen">
  <img src="docs/assets/screenshot-agents.png" width="240" alt="Sub-Agents Screen">
  <img src="docs/assets/screenshot-settings.png" width="240" alt="Settings Screen">
</div>
-->

## ✨ Key Features

- 🏠 **Self-hosted & private** — Runs on your machine. No cloud dependency, no data leaks.
- 🤖 **Three-tier agent architecture** — Sebastian (head butler) delegates to team leads, who dispatch workers. Your goals get executed, not just answered.
- 📱 **Native Android app** — Real-time streaming responses, thinking blocks, tool call cards. Built with Kotlin + Jetpack Compose.
- 🔧 **Zero-config extensibility** — Add tools, MCP servers, skills, and sub-agents by creating files. No core code changes needed.
- 🧠 **Three-layer memory** — Working memory for current tasks, episodic memory for conversation history, semantic memory with vector search (RAG).
- 🔒 **Permission & approval system** — Sensitive operations require your approval. Three-tier risk classification (Low / Model-Decides / High-Risk).
- 🚀 **Dynamic Tool Factory** — When an agent needs a tool that doesn't exist, it can write one, test it in a sandbox, and register it — all autonomously.

## Feature Matrix

| Feature | Android App | Web UI | CLI |
|---------|:-----------:|:------:|:---:|
| Real-time chat with streaming | ✅ | 🔄 | ✅ |
| Sub-agent management | ✅ | 🔄 | — |
| Approval notifications | ✅ | 🔄 | — |
| LLM provider configuration | ✅ | — | — |
| Session & task history | ✅ | 🔄 | — |
| Thinking block display | ✅ | — | — |
| Tool call visualization | ✅ | — | — |
| One-click install / update | — | — | ✅ |
| Headless initialization | — | — | ✅ |

✅ Available · 🔄 Planned · — Not applicable

## ⚡ Quick Start

### Install Server (macOS / Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
```

This installs the Sebastian backend service on your machine — downloads the latest release, verifies SHA256 checksums, installs dependencies, and launches the setup wizard. Open the URL it prints, set your name and password, and you're done.

### Install Android App

Download `sebastian-app-v*.apk` from [Releases](https://github.com/Jaxton07/Sebastian/releases) and install it on your phone.

On first launch, go to **Settings → Connection** and enter your server URL: `http://<your-local-ip>:8823`

### Connect Your AI Provider

After setup, open the Android app and go to **Settings → Providers**. Add your LLM provider (Anthropic, OpenAI, etc.) — API keys are stored encrypted on your machine, never sent to any cloud service.

## 🧭 Common Commands

```bash
sebastian serve              # Start the server (first launch opens setup wizard)
sebastian serve --host 0.0.0.0 --port 8823   # Custom bind address
sebastian init --headless    # Initialize without browser (for headless servers)
sebastian update             # Update to latest release (auto-rollback on failure)
sebastian update --check     # Check for updates without installing
```

## 🏗️ Architecture

```
┌─────────────┐     REST + SSE     ┌──────────────────┐
│  Android App │◄──────────────────►│     Gateway       │
│  (Kotlin)    │                    │  (FastAPI + SSE)  │
└─────────────┘                    └────────┬──────────┘
                                            │
                                   ┌────────▼────────┐
                                   │    Sebastian     │  ← Head Butler (depth 1)
                                   │  (Orchestrator)  │
                                   └────────┬─────────┘
                                            │ delegate_to_agent
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                        ┌──────────┐  ┌──────────┐  ┌──────────┐
                        │  Forge   │  │  Stock   │  │  Life    │  ← Team Leads (depth 2)
                        │  Agent   │  │  Agent   │  │  Agent   │
                        └────┬─────┘  └──────────┘  └──────────┘
                             │ spawn_sub_agent
                        ┌────▼─────┐
                        │ Workers  │                          ← Workers (depth 3)
                        └──────────┘

          ┌─────────────────────────────────────────────┐
          │            Shared Capabilities               │
          │  Tools · MCPs · Skills · Memory · Sandbox    │
          └─────────────────────────────────────────────┘
```

Every agent inherits from `BaseAgent` — same tool system, same streaming loop, same memory access. Sebastian adds goal decomposition and delegation; team leads add domain-specific tools and worker dispatch.

For the full architecture spec, see [docs/architecture/spec/](docs/architecture/spec/).

### The Manor System

Inspired by a traditional butler hierarchy: you are the lord of the manor, Sebastian is the head butler, the second tier is department leads (coding, finance, lifestyle), and the third tier is workers dispatched by leads.

```
You (Lord of the Manor)
│
├── Sebastian (Head Butler)
│     └── Understands your intent, decomposes goals, delegates to leads
│
├── Forge (Coding Lead)
│     ├── Handles simple tasks directly, dispatches workers for complex ones
│     └── Up to 5 workers concurrently
│
├── Stock Agent Lead (Planned)
│     └── ...
└── ...
```

Day-to-day: you only talk to Sebastian — it coordinates leads automatically. As you get started, you can also open direct conversations with any lead or intervene in any active session.

## 🗺️ Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **Phase 1** | Core engine, three-tier agents, Android app, gateway, SSE | ✅ Done |
| **Phase 2** | Memory system, Forge agent, push notifications, skills | 🔄 In progress |
| **Phase 3** | Voice pipeline, iOS app, trigger engine | 📋 Planned |
| **Phase 4** | Advanced triggers, more sub-agents, Web UI | 📋 Planned |
| **Phase 5** | Biometric auth, multi-factor permissions, audit logging | 📋 Planned |

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Architecture Spec](docs/architecture/spec/INDEX.md) | Full system design — data models, protocols, agent hierarchy |
| [Backend Guide](sebastian/README.md) | Python backend module map and development entry points |
| [Android App Guide](ui/mobile-android/README.md) | Kotlin app architecture, navigation, SSE connection details |
| [Changelog](CHANGELOG.md) | Version history and breaking changes |
| [Contributing Guide](CONTRIBUTING.md) | Development setup, code style, PR workflow |

## 📄 License

This project is licensed under the [MIT License](LICENSE).
