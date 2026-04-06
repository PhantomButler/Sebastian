# components/settings/

> 上级：[components/](../README.md)

## 目录职责

设置页的 UI 组件集合，负责 Server 连接配置、LLM Provider 配置、调试日志开关和 Memory 管理入口的渲染与交互，整体向 iOS Settings.app 风格靠拢。

## 目录结构

```
settings/
├── ServerConfig.tsx       # Server URL 配置与连接测试（含登录 / 登出）
├── LLMProviderConfig.tsx  # LLM Provider 增删改查配置表单
├── MemorySection.tsx      # Memory 管理占位入口（预留 Phase 3+）
└── DebugLogging.tsx       # 调试日志开关（llm_stream / sse）
```

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 修改 Server URL 输入 / 连接测试 / 登录登出 | [ServerConfig.tsx](ServerConfig.tsx) |
| 修改 LLM Provider 配置表单或列表 | [LLMProviderConfig.tsx](LLMProviderConfig.tsx) |
| 修改 Memory 管理入口内容 | [MemorySection.tsx](MemorySection.tsx) |
| 修改调试日志开关项 | [DebugLogging.tsx](DebugLogging.tsx) |

---

> 修改本目录后，请同步更新此 README。
