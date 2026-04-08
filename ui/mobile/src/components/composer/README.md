# composer/

Composer 是主对话输入区组件，负责文本输入、思考档位选择、发送/停止控制。

由 `KeyboardStickyView`（父层）包裹实现键盘跟随，自身无需感知键盘高度。

## 文件职责

| 文件 | 职责 |
|---|---|
| `index.tsx` | 主组件。状态机管理，组合子组件，普通 View 布局 |
| `InputTextArea.tsx` | 多行 TextInput，最多 5 行，超出内部滚动 |
| `ActionsRow.tsx` | 底部按钮容器，左思考右发送布局 |
| `ThinkButton.tsx` | 思考按钮，按 `thinking_capability` 渲染不同形态（禁用 / 隐藏 / toggle / picker / always_on 徽标），选中态按明暗主题做黑白反转 |
| `EffortPicker.tsx` | 底部弹出思考档位选择器（off/low/medium/high/max），选中项仅靠主题黑白配色区分，不显示勾选 |
| `SendButton.tsx` | 圆形按钮，根据 ComposerState 渲染 4 种视觉；发送/停止按钮按明暗主题做黑白反转，禁用态走灰阶 |
| `types.ts` | `ComposerState` 5 状态枚举 |
| `constants.ts` | 行高、最大行数等布局常量（含 `COMPOSER_DEFAULT_HEIGHT`） |

## 状态机

```
idle_empty ──has text──→ idle_ready
idle_ready ──send──────→ sending ──activeTurn──→ streaming ──stop──→ cancelling
streaming  ──turn done→ idle_empty
cancelling ──turn done→ idle_empty
cancelling ──5s timeout→ idle_empty + toast
```

## Props (Composer)

| Prop | 类型 | 说明 |
|---|---|---|
| `sessionId` | `string \| null` | null = draft session |
| `isWorking` | `boolean` | 来自 conversationStore.activeTurn |
| `onSend` | `(text, opts) => Promise<void>` | `opts.effort: ThinkingEffort`，由上层透传给 `sendTurn` / `sendTurnToSession` |
| `onStop` | `() => Promise<void>` | 调用 cancelTurn API |

> **已移除**：~~`bottomInset`~~、~~`onHeightChange`~~。键盘适配完全由外层 `KeyboardStickyView` 处理，Composer 无需上报高度。

## 键盘布局方案（react-native-keyboard-controller）

Composer 本身是普通 `View`（`marginHorizontal: 12, marginBottom: 12`），不做任何键盘感知。
键盘行为由父层控制：

- **`KeyboardStickyView`**（`app/index.tsx`、`app/subagents/session/[id].tsx`）：包裹 Composer，原生帧同步跟随键盘上移/下移，无 Yoga 重排抖动。
- **`stickyOffset = { opened: insets.bottom }`**：SafeAreaView 提供的底部安全区已包含在 `KeyboardStickyView` 基准位置中，`opened` 偏移补偿避免双重叠加。
- 消息列表用 `KeyboardChatScrollView`（通过 `renderScrollComponent` 注入 FlatList），自动通过 contentInset 调整滚动区域，无需手动计算 paddingBottom。

## 思考档位

`ThinkButton` 根据当前默认 provider 的 `thinking_capability`（从 `useSettingsStore` 读）决定渲染形态：

- `null` → 灰色 disabled pill（provider 未拉取到或未配置）
- `none` → 不渲染（模型不支持思考控制）
- `toggle` → 单点切换 pill（off/on），不弹 picker
- `effort` → pill + `EffortPicker`（off/low/medium/high）
- `adaptive` → pill + `EffortPicker`（off/low/medium/high/max）
- `always_on` → 不可点徽标"思考·自动"

档位状态存于 `src/store/composer.ts` 的 `useComposerStore`：

- `effortBySession[sessionId]`：当前 session 的 effort，按 sessionId 隔离
- `lastUserChoice`：全局最近选中的档位（默认 `off`），用 `expo-secure-store` 持久化（`sebastian_composer_v2`）
- 新 session 从 `lastUserChoice` 继承档位
- Draft 用 `__draft__` key，`persistSession` 后调 `migrateDraftToSession(newId)` 迁移

Provider 切换导致 capability 变化时，`syncCurrentThinkingCapability`（`src/api/llm.ts`）会调 `clampAllToCapability(allowedEfforts)` 统一降级/升级档位（例如从 `adaptive` 切到 `effort` 时 `max` → `high`）。`clampAllToCapability` 会返回 `ClampReport | null`（记录第一个发生降级的 from→to），调用方据此弹 Toast/Alert 告知用户档位已调整；入口：

- 应用启动（`app/_layout.tsx` 的 `syncCurrentThinkingCapability`）
- 新建 / 编辑 Provider（`components/settings/LLMProviderConfig.tsx` 的 `handleCreate` / `handleUpdate`）

effort 在 `POST /turns` / `POST /sessions/{id}/turns` / `POST /agents/{agent_type}/sessions`（新 sub-agent 会话首条消息）时锁定（body 的 `thinking_effort` 字段，off 时为 null），in-flight turn 不受中途改档位影响，picker 始终可点。
