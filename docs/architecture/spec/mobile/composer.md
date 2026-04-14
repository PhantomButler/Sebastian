---
version: "1.0"
last_updated: 2026-04-11
status: in-progress
---

# Composer 组件

*← [Mobile Spec 索引](INDEX.md)*

---

## 1. 设计原则

Composer 是整个 App 交互密度最高的组件，需要承载当前和未来多种输入能力（文字、语音、附件、全双工语音对话）。

**核心设计原则**：插槽架构（Slot-based）——每种能力是独立的 `@Composable`，通过插槽参数注入主容器。Phase 1 只渲染文字相关插槽，后续能力直接插入，不修改 `Composer.kt` 核心代码。

---

## 2. 组件结构

### 2.1 布局层次

```
Composer（圆角卡片容器）
├── AttachmentPreviewBar（可选，有附件时 AnimatedVisibility 展开）← Phase 2
├── TextInputArea（多行文字输入，可伸缩）
└── ToolBar（工具栏，横向排列）
    ├── ToolSlots（左侧，插槽区）
    │   ├── ThinkButton（Phase 1，思考档位）
    │   ├── VoiceSlot（Phase 2，语音输入）
    │   └── AttachmentSlot（Phase 2，附件选择）
    └── SendButton（右侧，发送/停止）
```

### 2.2 状态机

```kotlin
enum class ComposerState {
    IDLE_EMPTY,     // 输入框为空，发送按钮禁用
    IDLE_READY,     // 有输入内容，可发送
    SENDING,        // 发送中（等待后端确认创建 turn）
    STREAMING,      // 后端流式输出中，显示停止按钮
    CANCELLING,     // 用户点击停止，等待后端确认（5s 超时保护）
}
```

状态由 `ChatViewModel` 持有，`Composer` 通过 `state: ComposerState` prop 接收，自身无状态（纯展示组件）。

---

## 3. Phase 1 实现

### 3.1 Composer.kt（主容器）

```kotlin
@Composable
fun Composer(
    state: ComposerState,
    effort: ThinkingEffort,
    onEffortChange: (ThinkingEffort) -> Unit,
    onSend: (text: String) -> Unit,
    onStop: () -> Unit,
    // Phase 2 插槽预留（默认为空）
    voiceSlot: @Composable (() -> Unit)? = null,
    attachmentSlot: @Composable (() -> Unit)? = null,
    attachmentPreviewSlot: @Composable (() -> Unit)? = null,
)
```

- `voiceSlot`、`attachmentSlot`、`attachmentPreviewSlot` 在 Phase 1 传 `null`，Phase 2 时在 `ChatScreen` 调用处注入，不改 `Composer.kt`
- 附件预览区用 `AnimatedVisibility(visible = attachmentPreviewSlot != null)` 管理，有内容时平滑展开，无内容时高度归零

### 3.2 SendButton.kt

| 状态 | 外观 | 行为 |
|------|------|------|
| `IDLE_EMPTY` | 禁用，灰色发送图标 | 不可点击 |
| `IDLE_READY` | 激活，白/黑发送图标 | 点击触发 `onSend` |
| `SENDING` | `CircularProgressIndicator`（小号）| 不可点击 |
| `STREAMING` | 停止图标（■），激活色 | 点击触发 `onStop` |
| `CANCELLING` | `CircularProgressIndicator`（小号）| 不可点击，5s 超时后强制恢复 |

**停止按钮实现**：停止按钮在 `STREAMING` 态时完全独立于消息列表渲染，`onStop` 直接调用 `ChatViewModel.cancelTurn()`，不经过任何与流式渲染竞争的代码路径。点击响应延迟 < 16ms（一帧内）。

### 3.3 ThinkButton.kt

思考档位按钮，根据当前 Provider 的 `thinking_capability` 渲染不同形态：

| `thinking_capability` | 渲染 |
|-----------------------|------|
| `null`（加载中）| 禁用 pill，半透明 |
| `"none"` | 不渲染（`return`）|
| `"always_on"` | 非交互 badge，显示「思考·自动」 |
| `"toggle"` | 单击切换 on/off |
| `"effort"` / `"adaptive"` | 单击打开 `EffortPickerSheet`（底部弹窗）|

---

## 4. Phase 2 扩展：语音输入与附件

### 4.1 VoiceSlot

```kotlin
@Composable
fun VoiceSlot(
    onVoiceResult: (String) -> Unit,  // STT 识别结果填入输入框
)
```

- 单击打开语音录制 UI（底部弹窗，波形动画）
- 识别完成后将文字填入 `TextInputArea`，由用户确认后发送
- 不打断当前 `ComposerState`（录音期间发送按钮保持原状态）

### 4.2 AttachmentSlot

```kotlin
@Composable
fun AttachmentSlot(
    onAttachmentsSelected: (List<Attachment>) -> Unit,
)
```

- 单击弹出选择器（图片 / 文件 / 拍照）
- 选择后附件加入 `AttachmentPreviewBar`，不立即上传
- 发送时与文字内容一起打包发出

### 4.3 AttachmentPreviewBar

```kotlin
@Composable
fun AttachmentPreviewBar(
    attachments: List<Attachment>,
    onRemove: (Attachment) -> Unit,
)
```

- 横向可滚动列表，图片显示缩略图，文件显示图标+文件名
- 每项右上角有删除按钮
- 整个 Bar 用 `AnimatedVisibility` 包裹，`attachments.isEmpty()` 时高度动画收回

---

## 5. Phase 3 扩展：全双工语音对话

### 5.1 入口

**长按发送键**触发进入全双工语音模式，与 WhatsApp / Telegram 语音消息手势一致，用户零学习成本。

Phase 1 的 `SendButton` 需预留 `onLongPress` 回调，默认传 `null`（不触发），Phase 3 注入实现：

```kotlin
@Composable
fun SendButton(
    state: ComposerState,
    onPress: () -> Unit,
    onLongPress: (() -> Unit)? = null,   // Phase 3 注入
)
```

### 5.2 全双工语音 UI

长按后 Composer 区域过渡动画展开为全屏语音 UI：

```
┌─────────────────────────────────────┐
│                                     │
│         [ 波形动画（呼吸感）]          │
│                                     │
│      「Sebastian 正在聆听…」          │
│                                     │
│   [ 取消 ]            [ 发送 ]       │
└─────────────────────────────────────┘
```

- 波形动画：`InfiniteTransition` 驱动多根 bar 的高度，参数取自 `AnimationTokens`
- 松手（`onRelease`）即发送，保持与 WhatsApp 一致的肌肉记忆
- 向左滑动取消（不发送），向上锁定（持续录音不需要一直按住）

---

## 6. 键盘适配

使用 `WindowInsets.ime` + `Modifier.imePadding()` 处理软键盘顶起，无需第三方库（Compose 原生支持）：

```kotlin
// Composer 父容器
Column(
    modifier = Modifier
        .fillMaxSize()
        .imePadding()   // 键盘弹出时自动推高 Composer
) {
    LazyColumn(modifier = Modifier.weight(1f)) { /* 消息列表 */ }
    Composer(...)
}
```

键盘弹出/收起动画与系统键盘完全同步（API 30+ 原生 `WindowInsetsAnimation`），无抖动。

---

*← [Mobile Spec 索引](INDEX.md)*
