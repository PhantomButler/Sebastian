# Composer 组件重构与 Session Cancel 闭环设计

- 日期：2026-04-07
- 范围：`ui/mobile/` 前端 Composer 组件重塑 + `sebastian/core/` 与 `sebastian/gateway/` 后端 session 级取消能力
- 参考对象：DeepSeek App 主对话页输入框视觉与交互

---

## 背景与动机

当前主对话页 [`ui/mobile/app/index.tsx`](../../ui/mobile/app/index.tsx) 使用 [`src/components/chat/MessageInput.tsx`](../../ui/mobile/src/components/chat/MessageInput.tsx) 作为输入区，存在以下问题：

1. **视觉过时**：输入框为贴底带 border 的紧凑样式，跟现代 AI 对话 App（DeepSeek / Claude.ai / ChatGPT）的悬浮卡片风格差距较大
2. **组件无扩展性**：单文件 62 行、单一按钮复用发送与停止，未来要加思考开关、智能搜索、附件、语音等功能会迅速膨胀
3. **停止按钮是死的（关键 Bug）**：前端 `cancelTurn` 调用 `POST /api/v1/sessions/{id}/cancel`，但后端根本没有这个路由。当前只有 task 级的 `POST /sessions/{id}/tasks/{tid}/cancel`。点击停止按钮实际返回 404，UI 上"停下来"的视觉是后端 turn **自然跑完**后 `activeTurn` 被清空，不是取消生效
4. **图标散落**：`src/components/common/Icons.tsx` 只收录了 3 个图标，其他地方混用文本符号与潜在的零散 SVG 引用
5. **键盘遮挡**：`ChatScreen` 没有 `KeyboardAvoidingView`，键盘弹起时 Composer 会被遮挡

本次迭代同时解决上述 5 个问题，一次性建立可持续扩展的 Composer 基础设施。

---

## 设计决策（Q&A 沉淀）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 思考按钮是否联通后端 | **仅 UI 占位** | 避免本次 PR 跨 gateway + LLM provider 层，下一轮单独 spec 接入 extended thinking |
| 停止按钮修复范围 | **完整修复前后端** | 只修前端无法验证闭环；保留 bug 继续欺骗自己违背第一性原理 |
| 取消时 partial text 去向 | **保留 + `[用户中断]` 标记** | 业界标准做法；模型下一轮能看到"自己被打断"，上下文连贯 |
| Cancel 期间 UI 状态机 | **按钮 disabled + spinner 等后端确认 + 5s 超时兜底** | Sebastian 是 agent 系统，乐观清空会导致并发 turn 污染 episodic memory；状态机简单可靠 |
| 输入框样式 | **悬浮卡片（左右留白 + 圆角 + 阴影）** | 符合"参考 DeepSeek"要求；多按钮场景下视觉重量需要留白稀释 |
| 遮挡处理 | **动态 padding 跟随 Composer 高度** | 静态 padding 无论取 min/max 都不能同时满足"折叠态不留空白"和"扩张态能上滑看见"两个约束 |
| 输入框最大扩展 | **5 行，超出内部滚动** | 防止 Composer 无限撑开占满屏幕 |
| 组件目录 | **`src/components/composer/`（与 chat/ 平级）** | 命名精确——本质是 message composer 不是 chat 子组件；Sub-Agent session 详情页也要复用 |
| 思考开关作用域 | **按 sessionId 隔离** | 多 session 并发时不互相串；draft session 用 `__draft__` key，真 session 创建时迁移 |
| 图标统一策略 | **11 个图标全部落 `Icons.tsx`，不拆目录** | 当前文件不会超 500 行；未来超限再拆 |

---

## 1. 总体架构与文件树

```
sebastian/                                           # 后端
├── core/base_agent.py                               # ➕ async def cancel_session(session_id) -> bool
│                                                      取消 self._active_streams[session_id]
│                                                      flush partial buffer 进 episodic
│                                                      发 TURN_CANCELLED + TURN_COMPLETE 事件
├── protocol/events/types.py                         # ➕ EventType.TURN_CANCELLED
└── gateway/routes/sessions.py                       # ➕ POST /sessions/{session_id}/cancel

ui/mobile/src/
├── assets/icons/                                    # 已有 10 + 1 (think_icon) 个 SVG
│
├── components/
│   ├── common/Icons.tsx                             # 🔄 补齐全部 11 个图标
│   ├── chat/MessageInput.tsx                        # ❌ 删除
│   └── composer/                                    # ➕ 新建
│       ├── README.md
│       ├── index.tsx                                 主组件 Composer
│       ├── InputTextArea.tsx
│       ├── ActionsRow.tsx
│       ├── ThinkButton.tsx
│       ├── SendButton.tsx
│       ├── types.ts
│       └── constants.ts
│
├── store/composer.ts                                # ➕ thinkingBySession 按 sessionId 隔离
└── api/turns.ts                                     # 🔄 cancelTurn 改路径 + 错误处理

ui/mobile/app/index.tsx                              # 🔄 替换 MessageInput → Composer
                                                       包 KeyboardAvoidingView
ui/mobile/src/components/conversation/index.tsx     # 🔄 加 bottomPadding prop
ui/mobile/src/api/sse.ts 或 hooks/useSSE.ts          # 🔄 识别 turn_cancelled 事件
ui/mobile/README.md                                  # 🔄 目录树 + 修改导航
ui/mobile/src/components/README.md                   # 🔄 加 composer/ 链接
```

---

## 2. 后端 Cancel 闭环

### 2.1 调用链

```
前端按下停止
  ↓
POST /api/v1/sessions/{session_id}/cancel
  ↓
gateway/routes/sessions.py → cancel_session_post()
  ├── _resolve_session() 找到 session
  ├── 找到对应 agent 实例（sebastian 主管家 or sub-agent）
  ├── await agent.cancel_session(session_id)
  └── 返回 {"ok": true} / 404 / 409
  ↓
BaseAgent.cancel_session(session_id)
  ├── stream = self._active_streams.get(session_id)
  ├── None 或 done() → return False（路由转 404）
  ├── 标记 _cancel_requested.add(session_id)
  ├── stream.cancel() → await stream（吞 CancelledError）
  └── finally 块读取 _partial_buffer → flush + emit events → return True
  ↓
SSE 通道发出 TURN_CANCELLED + TURN_COMPLETE
  ↓
前端 useSSE → conversationStore.onTurnComplete() → activeTurn 清空
  ↓
Composer 状态机：cancelling → idle，按钮回到发送态
```

### 2.2 BaseAgent 改造

新增 instance 字段：

```python
self._cancel_requested: set[str] = set()
self._partial_buffer: dict[str, str] = {}
```

新增方法：

```python
async def cancel_session(self, session_id: str) -> bool:
    stream = self._active_streams.get(session_id)
    if stream is None or stream.done():
        return False
    self._cancel_requested.add(session_id)
    stream.cancel()
    try:
        await stream
    except (asyncio.CancelledError, Exception):
        pass
    return True
```

`_stream_inner` 内部每次收到 `TextDelta` 时同步写 `self._partial_buffer[session_id] = full_text`，确保 cancel 路径能拿到。

`run_streaming` 的 `finally` 块改造：

```python
finally:
    was_cancelled = session_id in self._cancel_requested
    self._cancel_requested.discard(session_id)
    self._active_streams.pop(session_id, None)
    self._current_task_goals.pop(session_id, None)
    self._current_depth.pop(session_id, None)

    if was_cancelled:
        partial = self._partial_buffer.pop(session_id, "")
        if partial:
            partial += "\n\n[用户中断]"
            try:
                await self._episodic.add_turn(
                    session_id, "assistant", partial, agent=agent_context,
                )
            except Exception:
                logger.warning("Failed to flush partial text on cancel", exc_info=True)
        await self._publish(
            session_id,
            EventType.TURN_CANCELLED,
            {"agent_type": agent_context, "had_partial": bool(partial)},
        )
        await self._publish(session_id, EventType.TURN_COMPLETE, {})
    else:
        self._partial_buffer.pop(session_id, None)
```

### 2.3 EventType 新增

`sebastian/protocol/events/types.py`：

```python
class EventType(str, Enum):
    ...
    TURN_CANCELLED = "turn_cancelled"
```

### 2.4 路由

`sebastian/gateway/routes/sessions.py` 新增：

```python
@router.post("/sessions/{session_id}/cancel", response_model=None)
async def cancel_session_post(
    session_id: str,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    agent = state.agent_instances.get(session.agent_type)
    target = agent if agent is not None else state.sebastian
    cancelled = await target.cancel_session(session_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="No active turn for this session")
    return {"ok": True}
```

### 2.5 边界矩阵

| 边界 | 处理 |
|---|---|
| Cancel 在 stream 刚启动 0ms 时进来 | `_active_streams[session_id]` 已 set，能取消 |
| Cancel 在 stream 已自然结束的窗口进来 | `stream.done()` True → 返回 False → 404 |
| 同一 session 并发两个 cancel 请求 | 第二个看到 stream 已取消 → False → 404，幂等无副作用 |
| Cancel 期间又有新 turn 到达 | 新 turn 走 `run_streaming` 开头的"取消旧 stream"分支，已有逻辑 |
| `_cancel_requested` 内存泄漏 | `finally` 里 `discard` 兜底 |
| `_partial_buffer` 内存泄漏 | `finally` 里 `pop` 兜底 |
| episodic flush 失败 | try/except 包住，log warning，不中断 cancel 流程 |

---

## 3. 前端 Composer 状态机

### 3.1 状态枚举

```ts
// composer/types.ts
export type ComposerState =
  | 'idle_empty'      // 输入框空，发送按钮灰色不可按
  | 'idle_ready'     // 有内容，发送按钮可按（蓝色）
  | 'sending'        // sendTurn in-flight，按钮 disabled+spinner
  | 'streaming'      // 后端正在回复，显示停止按钮
  | 'cancelling';    // 已 POST cancel，等 turn_complete，按钮 disabled+spinner
```

### 3.2 状态转移

```
idle_empty ──onChangeText(非空)──→ idle_ready
idle_ready ──onChangeText(空)────→ idle_empty
idle_ready ──onPressSend─────────→ sending
sending    ──sendTurn 成功 + activeTurn 出现→ streaming
sending    ──sendTurn 失败──────→ idle_ready（回填文本，外层 toast/banner）
streaming  ──onPressStop─────────→ cancelling
streaming  ──turn_complete──────→ idle_empty
cancelling ──turn_complete/cancelled→ idle_empty
cancelling ──5s 超时────────────→ idle_empty + 警告 toast"取消可能未生效"
```

### 3.3 派生规则

Composer 本地 state 仅三项：

```ts
const [text, setText] = useState('');
const [isSending, setIsSending] = useState(false);
const [isCancelling, setIsCancelling] = useState(false);
```

`state` 由外部 `isWorking`（来自 `useConversationStore.activeTurn`）+ 本地 state 派生：

```ts
const state: ComposerState = useMemo(() => {
  if (isCancelling) return 'cancelling';
  if (isWorking) return 'streaming';
  if (isSending) return 'sending';
  return text.trim() ? 'idle_ready' : 'idle_empty';
}, [isCancelling, isWorking, isSending, text]);
```

### 3.4 5s 超时兜底

```ts
useEffect(() => {
  if (state !== 'cancelling') {
    if (cancelTimerRef.current) clearTimeout(cancelTimerRef.current);
    return;
  }
  cancelTimerRef.current = setTimeout(() => {
    setIsCancelling(false);
    if (sessionId) {
      useConversationStore.getState().onTurnComplete(sessionId);
    }
    Toast.show('取消可能未生效，请下拉刷新');
  }, 5000);
  return () => {
    if (cancelTimerRef.current) clearTimeout(cancelTimerRef.current);
  };
}, [state, sessionId]);
```

`isWorking` 从 true → false 时自动退出 `cancelling`：

```ts
useEffect(() => {
  if (!isWorking && isCancelling) setIsCancelling(false);
}, [isWorking, isCancelling]);
```

---

## 4. Composer 组件结构

### 4.1 主组件接口

```ts
interface ComposerProps {
  sessionId: string | null;       // 当前 session id，draft 时为 null
  isWorking: boolean;             // 来自 useConversationStore
  onSend: (text: string, opts: { thinking: boolean }) => Promise<void>;
  onStop: () => Promise<void>;
  bottomInset: number;            // safe area 底部
  onHeightChange: (height: number) => void;  // 供 ChatScreen 动态 padding
}
```

### 4.2 子组件职责

| 文件 | 职责 |
|---|---|
| `index.tsx` | 主组件，状态管理，组合子组件，onLayout 上报高度 |
| `InputTextArea.tsx` | 多行 TextInput，`maxHeight = 5 * lineHeight`，超出内部滚动 |
| `ActionsRow.tsx` | 底部按钮容器，`justifyContent: space-between`，左右两 slot |
| `ThinkButton.tsx` | 胶囊按钮，受控 active 态，点击切换 |
| `SendButton.tsx` | 36×36 圆形按钮，根据 state 渲染 4 种视觉 |
| `types.ts` | `ComposerState` 枚举与共享类型 |
| `constants.ts` | `COMPOSER_MIN_HEIGHT`, `COMPOSER_MAX_HEIGHT` |

### 4.3 SendButton 四态

| state | 背景 | 图标 | 可点击 |
|---|---|---|---|
| `idle_empty` | `#E5E5EA` 灰 | `SendIcon` 白 | 否 |
| `idle_ready` | `accent` 蓝 | `SendIcon` 白 | 是 |
| `sending` | `accent` 蓝 | `ActivityIndicator` 白 | 否 |
| `streaming` | `accent` 蓝 | `StopCircleIcon` 白 | 是 |
| `cancelling` | `accent` 蓝 | `ActivityIndicator` 白 | 否 |

### 4.4 ThinkButton 视觉

| 状态 | 背景 | 文字/图标色 |
|---|---|---|
| active | `#E8F0FE` | `#3B82F6` |
| inactive | `colors.surfaceMuted` | `colors.textMuted` |

圆角 18，padH 12，padV 6，图标 16px，图标 + 文字水平排列，间距 6。

---

## 5. 思考开关按 session 隔离

### 5.1 store/composer.ts

```ts
const DRAFT_KEY = '__draft__';

interface ComposerStore {
  thinkingBySession: Record<string, boolean>;
  getThinking: (sessionId: string | null) => boolean;
  setThinking: (sessionId: string | null, v: boolean) => void;
  clearSession: (sessionId: string) => void;
}

export const useComposerStore = create<ComposerStore>((set, get) => ({
  thinkingBySession: {},
  getThinking: (sessionId) => {
    const key = sessionId ?? DRAFT_KEY;
    return get().thinkingBySession[key] ?? false;
  },
  setThinking: (sessionId, v) => {
    const key = sessionId ?? DRAFT_KEY;
    set((s) => ({
      thinkingBySession: { ...s.thinkingBySession, [key]: v },
    }));
  },
  clearSession: (sessionId) => {
    set((s) => {
      const next = { ...s.thinkingBySession };
      delete next[sessionId];
      return { thinkingBySession: next };
    });
  },
}));
```

### 5.2 draft → 真 session 迁移

`app/index.tsx` 的 `handleSend` 在 `persistSession` 后追加：

```ts
if (!currentSessionId) {
  persistSession({ id: sessionId, /* ... */ });

  const composerStore = useComposerStore.getState();
  const draftThinking = composerStore.getThinking(null);
  if (draftThinking) {
    composerStore.setThinking(sessionId, true);
  }
  composerStore.clearSession('__draft__');
  // ...
}
```

### 5.3 session 删除时清理

`handleDeleteSession` 成功后追加：

```ts
useComposerStore.getState().clearSession(id);
```

---

## 6. 视觉规格与 ChatScreen 集成

### 6.1 Composer 浮层规格

```
position: absolute
left: 12, right: 12, bottom: insets.bottom + 8
borderRadius: 24
padding: 12
backgroundColor: composerBg
borderWidth: 1
borderColor: composerBorder
shadow: ios { opacity 0.06, radius 8, offset (0, 2) }
        android { elevation 3 }
```

InputTextArea：`multiline`, `minHeight: 44`, `maxHeight: 110`（约 5 行，具体按 fontSize 调），`paddingTop: 14`, `paddingBottom: 12`。

ActionsRow：`flexDirection: row`, `justifyContent: space-between`, `alignItems: center`, `marginTop: 8`, `height: 36`。

### 6.2 Theme 扩展

`src/theme/ThemeContext.tsx` 新增 token（若已有则复用）：

```ts
composerBg: '#FFFFFF',
composerBorder: '#E5E7EB',
composerShadow: 'rgba(0,0,0,0.06)',
thinkActiveBg: '#E8F0FE',
thinkActiveFg: '#3B82F6',
```

### 6.3 动态高度联动

Composer 容器 onLayout 上报高度：

```tsx
<View
  style={[styles.floating, { bottom: bottomInset + 8 }]}
  onLayout={(e) => {
    const h = Math.min(e.nativeEvent.layout.height, COMPOSER_MAX_HEIGHT);
    onHeightChange(h);
  }}
>
```

`onLayout` 是纯被动回调，仅在容器尺寸真正变化时触发，不依赖任何 React state 读取，因此不会出现"测量→setState→重渲染→再测量"循环。

### 6.4 ChatScreen 集成

```tsx
const [composerHeight, setComposerHeight] = useState(96);
const bottomPadding = composerHeight + 24;

<KeyboardAvoidingView
  style={{ flex: 1 }}
  behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
>
  <View style={[styles.container, { backgroundColor: colors.background }]}>
    {/* header */}

    {isEmpty ? (
      currentBanner ? (
        <View style={{ flex: 1, paddingBottom: bottomPadding }}>
          <ErrorBanner ... />
        </View>
      ) : (
        <EmptyState message="..." bottomPadding={bottomPadding} />
      )
    ) : (
      <ConversationView
        sessionId={currentSessionId}
        errorBanner={currentBanner}
        bottomPadding={bottomPadding}
        onBannerAction={...}
      />
    )}

    <Composer
      sessionId={currentSessionId}
      isWorking={isWorking}
      onSend={handleSend}
      onStop={handleStop}
      bottomInset={insets.bottom}
      onHeightChange={setComposerHeight}
    />

    {/* Sidebar */}
  </View>
</KeyboardAvoidingView>
```

`ConversationView` 新增 `bottomPadding` prop，内部传给 MessageList 的 `contentContainerStyle.paddingBottom`。`EmptyState` 同样接受该 prop。

### 6.5 键盘联动

Android `behavior=height` 在 Expo edge-to-edge 模式下可能异常。实施时真机验证；若不工作回退为 `behavior={undefined}` + 检查 `app.json` 的 `android.softwareKeyboardLayoutMode` 配置。

---

## 7. Icons.tsx 统一

### 7.1 图标清单

| 导出名 | 来源 SVG | 默认 size/color |
|---|---|---|
| `DeleteIcon` | delete.svg（已有） | 16 / `#bbb` |
| `EditIcon` | edit.svg（已有） | 16 / `#fff` |
| `RightArrowIcon` | right_arrow.svg（已有） | 16 / `#bbb` |
| `CloseIcon` | close.svg | 20 / textMuted |
| `CycleProgressIcon` | cycle_progress.svg | 16 / textMuted |
| `EyeOpenIcon` | eye_open.svg | 20 / textMuted |
| `EyeCloseIcon` | eye_close.svg | 20 / textMuted |
| `UpDownIcon` | up_down.svg | 16 / textMuted |
| `SendIcon` | send_msg.svg | 18 / `#fff` |
| `StopCircleIcon` | stop_circle.svg | 18 / `#fff` |
| `ThinkIcon` | think_icon.svg | 16 / 跟随 active 色 |

### 7.2 结构

沿用现有 inline `<Svg><Path>` 模式（避免 svg transformer 不稳定）。按功能分组注释：

```tsx
// ========== 导航/操作 ==========
// CloseIcon, RightArrowIcon, UpDownIcon

// ========== 编辑/删除 ==========
// EditIcon, DeleteIcon

// ========== 状态/进度 ==========
// CycleProgressIcon, EyeOpenIcon, EyeCloseIcon

// ========== Composer 专用 ==========
// SendIcon, StopCircleIcon, ThinkIcon
```

总文件预计 260 行左右，未超 500 行阈值，本轮不拆目录。

### 7.3 复杂 SVG 处理

若 `think_icon.svg` 或 `close.svg` 采用 stroke-based 绘制（非 fill），则在组件中使用 `<Path stroke={color} strokeWidth={...} fill="none" />`。实施时先 `cat` SVG 源码判断。

### 7.4 迁移审计

实施阶段 grep：

```bash
grep -rn "from.*assets/icons" ui/mobile/src/ ui/mobile/app/
grep -rn "import.*\.svg" ui/mobile/src/ ui/mobile/app/
grep -rn "<Svg" ui/mobile/src/ ui/mobile/app/ | grep -v Icons.tsx
```

找到所有零散引用替换为从 `Icons.tsx` 导入。

**本次明确不替换**：`app/index.tsx` header 的 `☰` 文本符号、其他 emoji 图标。避免范围蔓延。

### 7.5 common/README.md 更新

追加图标清单小节，列出导出名 + 来源 SVG + 用法示例。

---

## 8. 前端 API 层改造

### 8.1 src/api/turns.ts

```ts
export async function cancelTurn(sessionId: string): Promise<void> {
  await apiClient.post(`/api/v1/sessions/${sessionId}/cancel`);
}
```

路径从旧的（不存在的）`/cancel` 改为新的 session 级 cancel。保留路径写法，但后端新增此路由后它就真能工作了。

外层 `handleStop` 改造：

```ts
async function handleStop() {
  if (!currentSessionId) return;
  try {
    await cancelTurn(currentSessionId);
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      // 后端已无活跃 stream，静默恢复
      return;
    }
    throw err;  // Composer 状态机会捕获并 toast
  }
}
```

### 8.2 src/api/sse.ts 或 src/hooks/useSSE.ts

增加对 `turn_cancelled` 事件的映射：当前 `turn_complete` 的处理路径上游增加 `turn_cancelled` → 同样调 `onTurnComplete`。如果当前代码用 switch/case 路由 event type，追加一个 case；如果用 map 表，加一个条目。

---

## 9. 测试策略

### 9.1 后端单元（tests/unit/test_base_agent.py）

| 测试 | 断言 |
|---|---|
| `test_cancel_session_returns_false_when_no_active_stream` | 空闲时返回 False |
| `test_cancel_session_cancels_active_stream` | 长跑 stream 被 cancel，`_active_streams` 清空 |
| `test_cancel_session_flushes_partial_text_to_episodic` | 流出 `"你好世界"` 后 cancel，episodic 新增 `"你好世界\n\n[用户中断]"` |
| `test_cancel_session_skips_flush_when_no_partial` | 流出 0 字符就 cancel，episodic 不新增 |
| `test_cancel_session_emits_turn_cancelled_event` | event bus 收到 TURN_CANCELLED + TURN_COMPLETE |
| `test_cancel_session_idempotent` | 连续两次 cancel，第二次返回 False，不抛 |
| `test_new_turn_during_cancel_does_not_race` | cancel in-flight 时启动新 turn，新 stream 正常建立 |

### 9.2 后端集成（tests/integration/test_gateway.py）

| 测试 | 断言 |
|---|---|
| `test_post_session_cancel_404_when_no_stream` | 空闲 session 上 POST cancel → 404 |
| `test_post_session_cancel_ok_during_stream` | 慢 turn 进行时 cancel → 200 `{"ok": true}` |
| `test_post_session_cancel_partial_persisted` | cancel 后 GET `/sessions/{id}` 能看到 `[用户中断]` 后缀消息 |
| `test_post_session_cancel_unknown_session` | 不存在 session → 404 |

### 9.3 前端手工验证 checklist

- [ ] 空输入框，发送按钮灰色不可点
- [ ] 输入一个字符，按钮变蓝色可点
- [ ] 全选删除，按钮回到灰色
- [ ] 点击发送，按钮瞬间变 spinner，成功后切换到停止按钮
- [ ] 点击停止按钮，按钮变 spinner + disabled
- [ ] 后端正常处理 cancel 后按钮回到发送态，最后一条 assistant 消息显示带 `[用户中断]`
- [ ] 断网状态下点停止，5s 后自动恢复 + 警告 toast
- [ ] 点击思考按钮切换高亮
- [ ] 切换 session A → B，A 的思考开关状态保留，B 显示 B 自己的
- [ ] 输入多行文本到 5 行，Composer 扩高，MessageList 最后一条自动上移
- [ ] 超过 5 行，TextInput 内部滚动，Composer 不再变高
- [ ] 键盘弹起，Composer 跟随键盘上移
- [ ] ErrorBanner 显示时不被 Composer 遮挡
- [ ] 新 session（draft）→ 发送 → 成为真 session，思考开关状态保留
- [ ] 删除 session 后 composer store 对应 key 被清理

---

## 10. 风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| Android `KeyboardAvoidingView` edge-to-edge 兼容 | 中 | 真机验证 + fallback 方案 |
| SSE 前端不识别 `turn_cancelled` | 中 | 显式映射到 `onTurnComplete` 路径 |
| 5s 超时误触发 | 低 | Toast 文案用"可能未生效"而非"失败"；强制清 activeTurn 让 UI 恢复可用 |
| partial flush 写入失败 | 中 | try/except + warning log |
| 并发：cancelling 时强发新消息 | 低 | 状态机物理 disabled 输入框和按钮 |
| think_icon.svg 是 stroke-based | 低 | 实施时 cat 源码，用 `stroke` 属性 |
| `_partial_buffer` / `_cancel_requested` 内存泄漏 | 低 | `finally` 兜底 |

---

## 11. 实施顺序

严格按此顺序，每步独立 commit 可独立 revert：

1. **Icons.tsx 统一** — 纯前端零依赖零风险
2. **后端 cancel 闭环** — `EventType` + `BaseAgent.cancel_session` + 路由 + 测试
3. **前端 cancelTurn 修复** — 只改 API 层，用旧 MessageInput 快速验证闭环
4. **Composer 组件骨架** — 新目录全部文件 + store/composer.ts
5. **Composer 接入 + 删除旧 MessageInput** — 切换 ChatScreen + KeyboardAvoidingView + 删旧文件 + 更新 README
6. **SSE turn_cancelled 前端映射** — 收尾

---

## 12. 文件改动汇总

| 文件 | 动作 | 估算行数 |
|---|---|---|
| `sebastian/core/base_agent.py` | 改 | +60 |
| `sebastian/protocol/events/types.py` | 改 | +1 |
| `sebastian/gateway/routes/sessions.py` | 改 | +25 |
| `tests/unit/test_base_agent.py` | 改 | +120 |
| `tests/integration/test_gateway.py` | 改 | +60 |
| `ui/mobile/src/components/common/Icons.tsx` | 改 | +260 |
| `ui/mobile/src/components/common/README.md` | 改 | +30 |
| `ui/mobile/src/components/composer/index.tsx` | 新 | ~180 |
| `ui/mobile/src/components/composer/InputTextArea.tsx` | 新 | ~60 |
| `ui/mobile/src/components/composer/ActionsRow.tsx` | 新 | ~30 |
| `ui/mobile/src/components/composer/ThinkButton.tsx` | 新 | ~60 |
| `ui/mobile/src/components/composer/SendButton.tsx` | 新 | ~100 |
| `ui/mobile/src/components/composer/types.ts` | 新 | ~20 |
| `ui/mobile/src/components/composer/constants.ts` | 新 | ~10 |
| `ui/mobile/src/components/composer/README.md` | 新 | ~80 |
| `ui/mobile/src/store/composer.ts` | 新 | ~50 |
| `ui/mobile/src/api/turns.ts` | 改 | ~15 |
| `ui/mobile/src/components/conversation/index.tsx` | 改 | +5 |
| `ui/mobile/src/api/sse.ts` 或 `hooks/useSSE.ts` | 改 | +10 |
| `ui/mobile/app/index.tsx` | 改 | ~30 |
| `ui/mobile/src/components/chat/MessageInput.tsx` | **删** | -62 |
| `ui/mobile/README.md` | 改 | +10 |
| `ui/mobile/src/components/README.md` | 改 | +5 |

合计约 **+1180 / -62**，每个单文件都在 500 行以下。

---

## 13. 非目标

本次明确**不做**：

- 智能搜索按钮
- 深度思考按钮联通后端（仅 UI 占位）
- header 菜单图标 `☰` 替换
- Sub-Agent session 详情页输入框替换（若存在，留下一轮）
- 前端测试框架引入（若无 jest 则手工验证）
- `sebastian/capabilities/tools/` 或 LLM provider 层改动
