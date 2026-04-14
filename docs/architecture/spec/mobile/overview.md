---
version: "1.0"
last_updated: 2026-04-11
status: in-progress
---

# Sebastian Android 原生客户端 — 总览

*← [Mobile Spec 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 定位与背景

### 1.1 为什么重写

React Native 版（`ui/mobile/`）在流式输出场景下触及架构上限：

- JS Thread 同时承担 React reconciler、Zustand 状态更新、所有事件回调，50 token/s 的 SSE delta 会将其打满
- 结果：流式期间停止按钮无响应、思考卡片/工具调用卡片无法展开折叠、列表无法上下滚动
- 这些问题的根因不是 bug，是 RN 单线程架构的约束，通过 `startTransition` + throttle 只能缓解不能根除

原生 Kotlin 的线程模型天然解决上述问题：SSE 解析在 IO 线程，Markdown 解析在 IO 线程，Main Thread 只做 `StateFlow.collect → Compose recomposition`，各线程职责严格隔离。

### 1.2 与旧版的关系

| 项目 | RN 版（`ui/mobile/`）| 原生版（`ui/mobile-android/`）|
|------|---------------------|------------------------------|
| 状态 | 保留，作为功能参考 | 新建，接替为主客户端 |
| 后端 API | 共用，不变 | 共用，不变 |
| 功能参考 | 80% 页面结构已确定 | 在此基础上重新设计，规避已知问题 |
| iOS | 暂用 Web UI | 后续视情况做 SwiftUI 版 |

---

## 2. 技术栈

| 层次 | 选型 | 理由 |
|------|------|------|
| 语言 | Kotlin | 官方首选，协程原生支持 |
| UI 框架 | Jetpack Compose | 声明式，与 React 思维一致；流式状态变更只重组变化部分；动画一等公民 |
| 三面板导航 | `androidx.compose.material3.adaptive` — `ThreePaneScaffold` | 原生内置三面板 + WindowSizeClass 自适应，无需手写手势 |
| 页面路由 | Compose Navigation | 与 Compose 深度集成，类型安全路由 |
| 状态管理 | ViewModel + StateFlow + `collectAsState()` | 单向数据流，Lifecycle-aware，无额外依赖 |
| 网络 / SSE | OkHttp（SSE 在 IO 线程）+ Retrofit（REST）| SSE 完全不占 Main Thread，ConnectivityManager 网络感知重连 |
| 数据流桥接 | Kotlin Flow + `callbackFlow` | OkHttp → Flow → ViewModel → StateFlow → Compose |
| 依赖注入 | Hilt | Jetpack 标准，ViewModel 注入零样板 |
| 本地存储 | DataStore（设置）+ `EncryptedSharedPreferences`（JWT）| 替代 SharedPreferences，协程友好 |
| Markdown 渲染 | Markwon（后台线程解析）| 在 IO 协程解析为 `Spanned`，Main Thread 只调用 `setText`，不阻塞 |
| 图片加载 | Coil（Compose 原生支持）| 轻量，Compose 友好，支持 `AsyncImage` |
| 最低 API | 33（Android 13）| Sebastian 为个人主用，不追求覆盖广度；API 33 带来 Predictive Back 手势原生集成、Material You 完整支持 |

---

## 3. 目录结构

```
ui/mobile-android/
├── app/
│   ├── src/main/
│   │   ├── java/com/sebastian/android/
│   │   │   ├── ui/                          # Composable 页面与组件
│   │   │   │   ├── chat/                    # 主对话页
│   │   │   │   │   ├── ChatScreen.kt        # 三面板根页面
│   │   │   │   │   ├── MessageList.kt       # 消息列表
│   │   │   │   │   ├── StreamingMessage.kt  # 流式消息（块级增量渲染）
│   │   │   │   │   ├── ThinkingCard.kt      # 思考过程折叠卡片
│   │   │   │   │   ├── ToolCallCard.kt      # 工具调用卡片
│   │   │   │   │   ├── SessionPanel.kt      # 左侧历史会话面板
│   │   │   │   │   └── TodoPanel.kt         # 右侧任务进度面板
│   │   │   │   ├── composer/                # 输入框（可扩展插槽架构）
│   │   │   │   │   ├── Composer.kt          # 主容器
│   │   │   │   │   ├── SendButton.kt        # 发送 / 停止按钮
│   │   │   │   │   ├── ThinkButton.kt       # 思考档位选择
│   │   │   │   │   └── slots/               # Phase 2+ 插槽
│   │   │   │   │       ├── VoiceSlot.kt     # 语音输入（Phase 2）
│   │   │   │   │       └── AttachmentSlot.kt # 附件（Phase 2）
│   │   │   │   ├── subagents/               # Sub-Agent 督导页
│   │   │   │   │   ├── AgentListScreen.kt
│   │   │   │   │   ├── SessionListScreen.kt
│   │   │   │   │   └── SessionDetailScreen.kt
│   │   │   │   ├── settings/                # 设置页
│   │   │   │   │   ├── SettingsScreen.kt
│   │   │   │   │   ├── ConnectionPage.kt
│   │   │   │   │   ├── ProviderListPage.kt
│   │   │   │   │   └── ProviderFormPage.kt
│   │   │   │   └── common/                  # 通用组件
│   │   │   │       ├── ApprovalDialog.kt
│   │   │   │       ├── AnimationTokens.kt   # 统一动画参数常量
│   │   │   │       └── ErrorBanner.kt
│   │   │   ├── viewmodel/
│   │   │   │   ├── ChatViewModel.kt
│   │   │   │   ├── SessionViewModel.kt
│   │   │   │   ├── SubAgentViewModel.kt
│   │   │   │   └── SettingsViewModel.kt
│   │   │   ├── data/
│   │   │   │   ├── remote/
│   │   │   │   │   ├── SseClient.kt         # OkHttp SSE，IO 线程
│   │   │   │   │   ├── ApiService.kt        # Retrofit 接口定义
│   │   │   │   │   └── model/               # API 响应数据类
│   │   │   │   │       ├── StreamEvent.kt
│   │   │   │   │       └── ContentBlock.kt
│   │   │   │   ├── local/
│   │   │   │   │   ├── SettingsDataStore.kt
│   │   │   │   │   └── SecureTokenStore.kt  # JWT 加密存储
│   │   │   │   └── repository/
│   │   │   │       ├── ChatRepository.kt
│   │   │   │       ├── SessionRepository.kt
│   │   │   │       └── SettingsRepository.kt
│   │   │   ├── di/
│   │   │   │   ├── NetworkModule.kt         # OkHttp / Retrofit Hilt 模块
│   │   │   │   └── RepositoryModule.kt
│   │   │   └── SebastianApp.kt              # Application，Hilt 入口
│   │   └── res/
│   │       └── values/
│   │           └── themes.xml               # Material 3 主题
│   └── build.gradle.kts
├── build.gradle.kts
└── settings.gradle.kts
```

---

## 4. 页面结构与路由

```
ChatScreen（根，三面板）
  左面板：SessionPanel（历史会话 + Sub-Agents/设置入口）
  中面板：MessageList + Composer
  右面板：TodoPanel（任务进度）

/subagents             → AgentListScreen（Stack push）
/subagents/{agentId}   → SessionListScreen
/subagents/session/{id}→ SessionDetailScreen（也有三面板）
/settings              → SettingsScreen（Stack push）
/settings/connection   → ConnectionPage
/settings/providers    → ProviderListPage
/settings/providers/new    → ProviderFormPage
/settings/providers/{id}   → ProviderFormPage（编辑）
```

---

## 5. 功能 Phase 规划（移动端视角）

### Phase 1 — 核心对话（当前目标）

- 三面板导航（手机覆盖式 / 平板横屏常驻）
- 主对话：消息列表、流式输出、思考卡片、工具调用卡片
- 流式 Markdown 块级增量渲染 + 逐块淡入动画
- Composer：文字输入 + 思考档位 + 发送/停止按钮
- SSE 稳定连接（OkHttp IO 线程 + 网络感知自动重连）
- Sub-Agent 督导页（Agent 列表 → Session 列表 → Session 详情）
- 审批弹窗（Approval Dialog）
- 设置页（连接与账户、模型与 Provider）
- 动画状态语言（idle / thinking / streaming / working 四态）
- FCM 推送接收（设备注册 + 通知跳转）

### Phase 2 — 媒体与语音输入

- Composer 语音输入插槽（STT，麦克风按钮）
- Composer 附件插槽（图片 / 文件，附件预览条）
- 消息内容模型扩展：`ImageBlock` / `FileBlock`
- `tool.executed` 结果支持图片 URL，工具卡片渲染图片
- 记忆模块后端对接（前端暂不展示 UI）

### Phase 3 — 语音输出与全双工

- 语音输出（TTS API 或多模态模型原生音频）
- 长按发送键 → 全屏语音对话模式（波形动画 + 松手发送）
- 视频文件附件支持
- 流式 Markdown 升级：逐块淡入 → 左→右梯度遮罩扫描（`drawWithContent`）

### 预留（后续规划）

- 平板横屏三栏常驻精调（右侧 Todo 栏宽度 / 自动展开逻辑）
- 记忆可视化（语义记忆 / 情景记忆浏览）
- 主屏 Widget / 快捷方式
- Foldable 设备（Z Fold）适配验证

---

## 6. 与后端协议对接约定

后端 API 与 SSE 协议不因客户端重写而变化，约定如下：

| 协议 | 路径/格式 | 说明 |
|------|----------|------|
| REST | `/api/v1/*` | 与 RN 版完全一致，Retrofit 定义 |
| SSE 全局流 | `GET /api/v1/stream` | 全局事件（task.*、approval.*、todo.*） |
| SSE 会话流 | `GET /api/v1/sessions/{id}/stream` | 单会话流式事件（turn.*、tool.*） |
| 断线重连 | `Last-Event-ID` header | 服务端 500 条缓冲，带 ID 重连自动补偿 |
| 认证 | `Authorization: Bearer <jwt>` | JWT 存 `EncryptedSharedPreferences` |
| 取消流式 | `POST /api/v1/sessions/{id}/cancel` | 返回 `{"ok": true}` 或 404（已结束） |

> 详细事件类型见 [core/runtime.md](../core/runtime.md)

---

*← [Mobile Spec 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
