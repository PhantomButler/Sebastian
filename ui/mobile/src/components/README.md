# components/

> 上级：[src/](../README.md)

## 目录职责

按业务领域分组的 UI 组件目录。每个子目录对应一个业务域，组件不应跨域直接引用（共用组件放 `common/`），保持各域内聚。

## 目录结构

```
components/
├── chat/           # Sebastian 主对话页组件（消息列表、流式气泡、输入框、侧边栏）
├── common/         # 跨域通用组件（侧边栏容器、审批弹窗、空状态、图标、状态徽章）
├── conversation/   # Sub-Agent Session 详情对话视图（Markdown、thinking block、工具调用）
├── settings/       # 设置页组件（Server 配置、LLM Provider、Memory、调试日志）
└── subagents/      # Sub-Agent 浏览链路组件（Agent 列表、Session 列表、Session 详情）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 主对话消息渲染 / 输入框 | [chat/](chat/README.md) |
| 跨域复用的通用组件 | [common/](common/README.md) |
| Sub-Agent Session 详情对话视图 | [conversation/](conversation/README.md) |
| 设置页各配置模块 | [settings/](settings/README.md) |
| Sub-Agent 浏览链路（三级导航） | [subagents/](subagents/README.md) |

## 子模块

- [chat/](chat/README.md) — 主对话页组件
- [common/](common/README.md) — 跨域通用组件
- [conversation/](conversation/README.md) — Session 详情对话视图
- [settings/](settings/README.md) — 设置页组件
- [subagents/](subagents/README.md) — Sub-Agent 浏览组件

---

> 修改本目录后，请同步更新此 README。
