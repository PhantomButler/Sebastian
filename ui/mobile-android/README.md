# UI Mobile Android Guide

Sebastian Android 原生 App，Kotlin + Jetpack Compose 重写版本，替代原 React Native (`ui/mobile/`)。以 Android 原生技术栈实现完整的 Sebastian 交互入口。

## 目录定位

`ui/mobile-android/` 是 Sebastian 的 Android 原生主交互入口，当前承担：

- Sebastian 主对话（消息历史、流式响应、思考块、工具调用）
- Sub-Agent 浏览与 Session 管理
- LLM Provider 配置与账户管理
- REST + SSE 与 `sebastian/gateway/` 对接

建议配合阅读：

- [sebastian/gateway/README.md](../../sebastian/gateway/README.md) — 后端网关接口
- `docs/superpowers/specs/2026-04-01-android-app-design.md` — Android App 设计 spec
- [docs/mobile-dev-gotchas.md](../../docs/mobile-dev-gotchas.md) — 平台行为坑记录

## 顶层结构

```text
ui/mobile-android/
├── app/
│   ├── src/main/
│   │   ├── AndroidManifest.xml
│   │   └── java/com/sebastian/android/
│   │       ├── SebastianApp.kt         # Application（@HiltAndroidApp）
│   │       ├── MainActivity.kt         # Activity + NavHost 路由注册
│   │       ├── data/                   → [data/README.md](app/src/main/java/com/sebastian/android/data/README.md)
│   │       ├── di/                     → [di/README.md](app/src/main/java/com/sebastian/android/di/README.md)
│   │       ├── ui/                     → [ui/README.md](app/src/main/java/com/sebastian/android/ui/README.md)
│   │       └── viewmodel/              → [viewmodel/README.md](app/src/main/java/com/sebastian/android/viewmodel/README.md)
│   └── src/test/                       # 单元测试
├── gradle/
│   └── libs.versions.toml              # 版本目录（统一依赖版本）
├── build.gradle.kts
└── settings.gradle.kts
```

## 架构概览

```
UI Layer（Jetpack Compose）
    ChatScreen / SettingsScreen / AgentListScreen / ...
         ↕ collectAsState() / event callbacks
ViewModel Layer（Hilt ViewModel + StateFlow）
    ChatViewModel / SessionViewModel / SettingsViewModel / ...
         ↕ Repository interfaces
Data Layer（Repository Pattern）
    ChatRepositoryImpl / SessionRepositoryImpl / ...
         ↕
  ┌──────────────────┬─────────────────┐
  │  REST（Retrofit） │  SSE（OkHttp）   │  Local（DataStore / EncryptedSharedPrefs）
  │  ApiService.kt   │  SseClient.kt   │  SettingsDataStore / SecureTokenStore
  └──────────────────┴─────────────────┘
         ↕
    sebastian/gateway/（FastAPI HTTP + SSE）
```

### 技术栈

| 分类 | 库 |
|------|----|
| UI | Jetpack Compose + Material3 |
| 自适应布局 | `material3-adaptive`（NavigableListDetailPaneScaffold） |
| 导航 | Navigation Compose（type-safe routes via kotlinx.serialization） |
| DI | Hilt 2.52 |
| 网络 REST | Retrofit 2 + Moshi |
| 网络 SSE | OkHttp SSE（okhttp-sse） |
| 本地存储 | DataStore Preferences + EncryptedSharedPreferences |
| Markdown | Markwon 4.6.2 |
| 异步 | Kotlin Coroutines + Flow |
| 测试 | JUnit4 + Mockito-Kotlin + Turbine |

## 导航信息架构

```
GlobalApprovalBanner（悬浮，覆盖所有页面）
    └── onNavigateToSession → Route.Chat / Route.AgentChat

App 启动 → ChatScreen（主对话，agentId=null）
    ├── List Pane（左栏）：SessionPanel（完整模式）
    │   ├── 历史 Session 列表 → 点击切换 session
    │   ├── 新建对话按钮
    │   ├── → navController.navigate(Route.Settings)
    │   └── → navController.navigate(Route.SubAgents)
    ├── Detail Pane（中栏）：MessageList + Composer + ErrorBanner
    └── Extra Pane（右栏）：TodoPanel

Route.SubAgents → AgentListScreen
    └── → Route.AgentChat(agentId, agentName) → ChatScreen（SubAgent 模式）
            ├── List Pane（左栏）：SessionPanel（精简模式，仅该 agent 的 session 列表）
            ├── Detail Pane（中栏）：MessageList + Composer
            └── Extra Pane（右栏）：TodoPanel

Route.Settings → SettingsScreen
    ├── → Route.SettingsConnection → ConnectionPage
    ├── → Route.SettingsProviders → ProviderListPage
    │       ├── → Route.SettingsProvidersNew → ProviderFormPage(null)
    │       └── → Route.SettingsProvidersEdit(id) → ProviderFormPage(id)
    └── → Route.SettingsAgentBindings → AgentBindingsPage
            └── → Route.SettingsAgentBindingEditor(agentType) → AgentBindingEditorPage
```

手机竖屏：Detail Pane 全屏，点击 Menu 图标滑至 List Pane，点击 Checklist 图标滑至 Extra Pane。
宽屏/折叠屏：自动多栏展示（Material3 Adaptive 处理）。

## 子模块

- [data/](app/src/main/java/com/sebastian/android/data/README.md) — 数据层（Remote / Local / Model / Repository）
- [di/](app/src/main/java/com/sebastian/android/di/README.md) — Hilt 依赖注入模块
- [ui/](app/src/main/java/com/sebastian/android/ui/README.md) — UI 层（Screen / Component / Theme）
- [viewmodel/](app/src/main/java/com/sebastian/android/viewmodel/README.md) — ViewModel 层

## 构建与运行

### 前置条件

- Android Studio（推荐 Meerkat 2024.3.2+）
- JDK 17+
- Android SDK API 26+，AVD 推荐 `Medium_Phone_API_36.1`

### 启动模拟器

```bash
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -no-snapshot-load &
~/Library/Android/sdk/platform-tools/adb wait-for-device shell getprop sys.boot_completed
```

### 构建并安装

```bash
cd ui/mobile-android

# 配置 SDK 路径（仅首次，不提交）
echo "sdk.dir=$HOME/Library/Android/sdk" > local.properties

# 通过 Gradle 构建并安装
./gradlew installDebug
```

或直接在 Android Studio 中点击 Run（▶）。

### 启动 Gateway 供 App 联调

```bash
# 根目录执行
uvicorn sebastian.gateway.app:app --host 127.0.0.1 --port 8823 --reload

# App 内 Settings → Connection 填写 Server URL：
# 模拟器：http://10.0.2.2:8823
# 真机：http://192.168.x.x:8823
```

> 模拟器内访问宿主机 localhost 需用 `10.0.2.2`，不是 `127.0.0.1`。

### 运行单元测试

```bash
./gradlew test
```

## 聊天历史水合（Timeline Hydration）

聊天历史通过 `GET /api/v1/sessions/{id}?include_archived=true` 加载，后端返回 `timeline_items`（按 `seq ASC` 排列）。

- App 以 `timeline_items` 为权威来源；若后端不返回该字段，则回退到旧的 `messages` 字段（兼容旧服务端）
- `TimelineMapper`（`data/remote/dto/`）是唯一将 timeline 行转换为 `Message + ContentBlock` 的入口
- `context_summary` 类型映射为 `ContentBlock.SummaryBlock`，在消息列表中以折叠卡片"Compressed summary"展示
- 新 Session 使用客户端生成的 ID（`UUID`）：App 先开 SSE，再以同一 `session_id` POST 首条 turn，确保流事件不丢失

## SSE 连接机制

App 有两条 SSE 连接：

**Per-session SSE**（`GET /api/v1/sessions/{sessionId}/stream`）：
- 由 `ChatViewModel` 管理，负责当前对话的流式消息
- 进入前台（`ON_START`）→ 启动连接；退入后台（`ON_STOP`）→ 取消 Job
- 网络恢复 → 自动重连；连接失败 → 显示 `connectionFailed` Banner
- Last-Event-ID 跨连接持久化，服务端可断点续传

**全局 SSE**（`GET /api/v1/stream`）：
- 由 `GlobalApprovalViewModel` 管理，接收所有 session 的审批事件
- 生命周期绑定到 `SebastianNavHost`，与页面导航无关
- 审批事件入队，`GlobalApprovalBanner` 显示队首，处理后自动弹出下一条

增量渲染优化：`TextDelta` 事件先缓存到 `pendingDeltas`，每 50ms 批量合并到消息列表，降低 Compose recomposition 频率。

### 状态恢复与本地通知

`GlobalSseDispatcher`（Singleton）持有唯一的全局 SSE 连接并通过 `SharedFlow` 分发给：
- `GlobalApprovalViewModel`（原订阅逻辑迁移至此）
- `NotificationDispatcher`（后台时发本地通知）
- `AppStateReconciler`（监听 `connectionState` 的 `Connected` 转换，触发 reconcile）

`AppStateReconciler` 在 `ProcessLifecycleOwner.ON_START` 或 SSE `onOpen` 时 150ms debounce 拉取：
- `GET /api/v1/approvals` → `GlobalApprovalViewModel.replaceAll`

> 注：chat 消息的一致性由 `switchSession` 全量 `getMessages` + SSE `Last-Event-Id` 回放两条既有路径保证，不走 reconciler。

`NotificationDispatcher` 仅在 App 处于后台时发通知（`ProcessLifecycleOwner.currentState < STARTED`）；通知点击携带 `sebastian://session/{id}` deep link 回到对应 session。

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改主对话三栏布局 | `ui/chat/ChatScreen.kt` |
| 改消息渲染（文本/思考/工具块） | `ui/chat/StreamingMessage.kt`、`ThinkingCard.kt`、`ToolCallCard.kt` |
| 改输入框（Composer） | `ui/composer/Composer.kt`、`SendButton.kt` |
| 改 Agent LLM 绑定次级页 | `ui/settings/AgentBindingEditorPage.kt`、`viewmodel/AgentBindingEditorViewModel.kt`、`ui/settings/components/EffortSlider.kt`、`ui/settings/components/ProviderPickerDialog.kt` |
| 改 Session 列表面板 | `ui/chat/SessionPanel.kt`（UI）+ `ui/chat/SessionGrouping.kt`（按日期分桶纯逻辑，有单测） |
| 改 Todo 面板 | `ui/chat/TodoPanel.kt` |
| 改全局审批横幅 | `ui/common/GlobalApprovalBanner.kt`、`viewmodel/GlobalApprovalViewModel.kt` |
| 改错误 Banner | `ui/common/ErrorBanner.kt` |
| 弹一次性 Toast 提示 | `ui/common/ToastCenter.kt` |
| 新增路由 | `ui/navigation/Route.kt` + `MainActivity.kt` |
| 改设置页 | `ui/settings/` |
| 改 Sub-Agent 列表 | `ui/subagents/AgentListScreen.kt` |
| 改主题/品牌色 | `ui/theme/Color.kt`、`ui/theme/SebastianTheme.kt` |
| 改 SSE 事件处理 | `viewmodel/ChatViewModel.handleEvent()` |
| 改 SSE 重连策略 | `data/remote/SseClient.kt` |
| 改全局 SSE 分发 | `data/remote/GlobalSseDispatcher.kt` |
| 改状态恢复 / reconcile | `data/sync/AppStateReconciler.kt` |
| 改本地通知 | `notification/NotificationDispatcher.kt`、`notification/NotificationChannels.kt` |
| 新增 REST 端点 | `data/remote/ApiService.kt` + DTO + Repository |
| 改本地存储（Token/设置） | `data/local/SecureTokenStore.kt`、`SettingsDataStore.kt` |
| 改 DI 绑定 | `di/` |

## 联调约定

- 模拟器访问宿主机 Gateway：`http://10.0.2.2:8823`（开发环境用 `:8824`）
- 真机用局域网 IP：`http://192.168.x.x:8823`
- API 或 SSE 协议变更时，需同步检查 `sebastian/gateway/` 与对应 spec

## 维护约定

- 导航结构变化时，同步更新本 README 的「导航信息架构」章节
- 新增 Screen 时，同步更新 `ui/navigation/Route.kt`、`MainActivity.kt` 和 `ui/README.md`
- 新增包时，在对应父 README 中补充链接

---

> 修改目录结构或页面导航后，请同步更新本 README 中的目录树与修改导航表。
