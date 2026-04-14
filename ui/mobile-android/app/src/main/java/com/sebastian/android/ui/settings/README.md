# settings 模块

> 上级：[ui/README.md](../README.md)

设置页组，包含连接与账户、LLM Provider 管理、外观、高级（Debug 日志）四个入口。

## 目录结构

```text
settings/
├── SettingsScreen.kt     # 设置首页（分类卡片列表）
├── ConnectionPage.kt     # 连接与账户页（Server URL / 登录 / 健康检查）
├── ProviderListPage.kt   # LLM Provider 列表页
├── ProviderFormPage.kt   # LLM Provider 新增/编辑页
├── AppearancePage.kt     # 外观设置页（深色/浅色模式等开关）
└── DebugLoggingPage.kt   # 高级：Debug 日志页（日志级别开关）
```

## 模块说明

### `SettingsScreen`

设置首页，展示分类卡片：连接与账户 / Provider / 外观 / 高级。每张卡片点击跳转对应子页。

### `ConnectionPage`

- Server URL 输入与保存
- 登录/登出（JWT Token 管理）
- 健康检查（连接测试按钮，显示延迟或错误信息）

### `ProviderListPage` / `ProviderFormPage`

LLM Provider 列表与新增/编辑，由 `ProviderFormViewModel` 驱动。支持多 Provider 管理（如 Claude API、OpenAI 等）。

### `AppearancePage`

外观设置，含深色/浅色模式切换等开关，由 `SettingsViewModel` 驱动。

### `DebugLoggingPage`

高级调试页，含日志级别开关，由 `SettingsViewModel` 驱动。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改设置首页分类卡片 | `SettingsScreen.kt` |
| 改连接/账户设置 | `ConnectionPage.kt` |
| 改 Provider 列表 | `ProviderListPage.kt` |
| 改 Provider 新增/编辑表单 | `ProviderFormPage.kt` + `viewmodel/ProviderFormViewModel.kt` |
| 改外观设置开关 | `AppearancePage.kt` + `viewmodel/SettingsViewModel.kt` |
| 改 Debug 日志开关 | `DebugLoggingPage.kt` + `viewmodel/SettingsViewModel.kt` |

---

> 新增设置页后，请同步在 `SettingsScreen.kt` 添加入口卡片、在 `navigation/Route.kt` 注册路由，并更新本 README 与上级 [ui/README.md](../README.md)。
