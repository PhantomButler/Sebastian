# composer 模块

> 上级：[ui/README.md](../README.md)

消息输入区，由 `ChatUiState.composerState`（`ComposerState` 枚举）驱动，封装输入框与发送/停止按钮。思考档位已迁移至每个 Sub-Agent 的绑定次级页（见 `ui/settings/AgentBindingEditorPage.kt`），Composer 不再承载 thinking UI。

## 目录结构

```text
composer/
├── Composer.kt             # 输入框容器（插槽架构，GlassSurface 悬浮）
├── SendButton.kt           # 发送/停止按钮（状态机驱动）
├── AttachmentSlot.kt       # 附件选择按钮与文件选择器（图片 / 文本文件）
└── AttachmentPreviewBar.kt # 已选附件预览栏（缩略图 + 删除）
```

## 模块说明

### `Composer`

插槽架构，自身无状态：`ComposerState` 由 `ChatViewModel` 持有并通过 prop 传入。签名：

```kotlin
@Composable
fun Composer(
    state: ComposerState,
    glassState: GlassState,
    onSend: (String) -> Unit,
    onStop: () -> Unit,
    voiceSlot: @Composable (() -> Unit)? = null,
    attachmentSlot: @Composable (() -> Unit)? = null,
    attachmentPreviewSlot: @Composable (() -> Unit)? = null,
    modifier: Modifier = Modifier,
)
```

通过 `GlassSurface` 实现液态玻璃悬浮效果；输入文本为内部 `rememberSaveable` 状态，按 `text.isNotBlank()` 推导实际按钮状态。`voiceSlot` / `attachmentSlot` / `attachmentPreviewSlot` 为 Phase 2 预留插槽，默认 `null`；接入语音或附件时不修改本文件。

### `SendButton`

状态机驱动，四个状态对应不同视觉与行为：

| 状态 | 触发条件 | 视觉 |
|------|---------|------|
| `IDLE_EMPTY` | 输入框为空 | 灰色禁用 |
| `IDLE_READY` | 有输入内容 | 激活发送图标 |
| `STREAMING` | AI 正在响应 | 停止按钮 |
| `CANCELLING` | 已发送停止请求 | 加载中 |

## 修改导航

| 修改场景 | 优先看 |
|---------|--------|
| 改输入框整体布局/悬浮样式 | `Composer.kt` |
| 改发送/停止按钮状态逻辑 | `SendButton.kt` |
| 改附件选择按钮 / 文件选择器 | `AttachmentSlot.kt` |
| 改附件预览栏（缩略图/删除） | `AttachmentPreviewBar.kt`：图片附件（`kind == IMAGE`）使用 Coil `AsyncImage` 渲染本地缩略图，其他类型（文本文件等）渲染文字 chip |
| 改 `ComposerState` 枚举定义 | `viewmodel/ChatViewModel.kt` |
| 改每个 Agent 的思考档位（Provider + Effort） | `ui/settings/AgentBindingEditorPage.kt` → [settings/README.md](../settings/README.md) |

---

> 新增输入区控件后，请同步更新本 README 与上级 [ui/README.md](../README.md)。
