# composer/

Composer 是主对话输入区组件，负责文本输入、思考开关、发送/停止控制。

## 文件职责

| 文件 | 职责 |
|---|---|
| `index.tsx` | 主组件。状态机管理，组合子组件，onLayout 上报高度 |
| `InputTextArea.tsx` | 多行 TextInput，最多 5 行，超出内部滚动 |
| `ActionsRow.tsx` | 底部按钮容器，左思考右发送布局 |
| `ThinkButton.tsx` | 胶囊式思考开关（UI 占位，未接后端） |
| `SendButton.tsx` | 圆形按钮，根据 ComposerState 渲染 4 种视觉 |
| `types.ts` | `ComposerState` 5 状态枚举 |
| `constants.ts` | 行高、最大行数等布局常量 |

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
| `onSend` | `(text, opts) => Promise<void>` | `opts.thinking` 预留字段 |
| `onStop` | `() => Promise<void>` | 调用 cancelTurn API |
| `bottomInset` | `number` | Safe area 底部 |
| `onHeightChange` | `(h: number) => void` | 供 ChatScreen 动态 padding |

## 思考开关

状态存于 `src/store/composer.ts` 的 `useComposerStore`，按 `sessionId` 隔离。
Draft session 用 `__draft__` key，`persistSession` 后调 `migrateDraftToSession(newId)` 迁移。
