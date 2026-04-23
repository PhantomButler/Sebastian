# navigation 模块

> 上级：[ui/README.md](../README.md)

Type-safe 路由定义，由 `MainActivity.kt` 的 `NavHost` 注册并使用。

## 目录结构

```text
navigation/
└── Route.kt   # sealed class，@Serializable + kotlinx.serialization 实现 type-safe 路由
```

## 路由表

| Route | Screen |
|-------|--------|
| `Chat(sessionId?)` | `ChatScreen`（主对话，agentId=null） |
| `SubAgents` | `AgentListScreen` |
| `AgentChat(agentId, agentName, sessionId?)` | `ChatScreen`（SubAgent 三面板模式） |
| `Settings` | `SettingsScreen` |
| `SettingsConnection` | `ConnectionPage` |
| `SettingsProviders` | `ProviderListPage` |
| `SettingsProvidersNew` | `ProviderFormPage(null)` |
| `SettingsProvidersEdit(providerId)` | `ProviderFormPage(id)` |
| `SettingsAgentBindings` | `AgentBindingsPage` |
| `SettingsMemory` | `MemorySettingsPage` |
| `SettingsAppearance` | `AppearancePage` |
| `SettingsDebugLogging` | `DebugLoggingPage` |

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 新增路由 | `Route.kt` + `MainActivity.kt`（NavHost 注册） |
| 改路由参数 | `Route.kt` + 所有传参调用方 |

---

> 新增或修改路由后，请同步更新本 README 路由表与上级 [ui/README.md](../README.md)。
