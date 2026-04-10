# 未配置 LLM Provider 时的友好错误提示

> 设计日期：2026-04-07
> 关联背景：移除 `ANTHROPIC_API_KEY` env fallback 后，空数据库部署会导致后端启动崩溃

## 1. 问题陈述

最近的改动移除了 `ANTHROPIC_API_KEY` 环境变量 fallback，LLM Provider 现在统一通过 App Settings 页存入数据库。带来的副作用：

1. **后端启动崩溃**：`gateway/app.py` 在 lifespan 里 eager 调用 `llm_registry.get_default_with_model()`，空数据库时抛 `RuntimeError`，FastAPI 起不来。
2. **用户发消息无任何提示**：即使后端能起来，`POST /api/v1/turns` 走的是"立即返回 200 + 后台跑 `run_streaming`" 的模式，错误发生在后台 task 里，前端 `sendTurn` 完全感知不到。

目标：

- 后端在数据库无 Provider 时**正常启动**
- 用户在 App 内发消息时，**对话界面内**显示"未配置 LLM Provider，请前往 Settings 添加"提示，附带跳转 Settings 的按钮
- 错误信号必须**结构化可识别**，不依赖错误 message 字符串匹配

## 2. 设计原则

- **最短路径**：能用 HTTP 400 解决就不引入新 EventType / event bus 改造
- **不加兜底**：禁止"检测到无 provider 就用 env key" 之类的兼容补丁
- **不持久化错误**：错误提示是配置态，不属于对话内容，不写入 episodic store
- **前瞻但不过度设计**：只对未来肯定要做的"per-agent provider 绑定"留一行兼容（用 `get_provider(agent_type)` 而非 `get_default_with_model()`）；其它未来功能（reviewer 专属 provider、LLM 子页、输入框组件化）一律不预留接口

## 3. 整体方案

错误信号通过 **HTTP 400** 在路由层 pre-check 阶段返回，不走 SSE。

```
用户发消息
   │
   ▼
POST /api/v1/turns
   │
   ├─ _ensure_llm_ready("sebastian")  ← 新增 pre-check
   │     │
   │     ├─ ✅ 有 provider → 继续原逻辑（创建 session、调度后台 task）
   │     │
   │     └─ ❌ 无 provider → 抛 HTTPException(400, {code:"no_llm_provider", ...})
   │                          ← 此时尚未创建 session，无副作用
   │
   ▼
前端 sendTurn axios catch
   │
   ├─ error.response.status === 400
   ├─ error.response.data.detail.code === "no_llm_provider"
   │
   ▼
往 conversation store 写 ephemeral errorBanner
   │
   ▼
ConversationView 渲染对话内错误气泡
   │
   └─ 「未配置 LLM Provider，请前往 Settings → 模型 页面添加」
       [前往 Settings] ← 点击 router.push('/settings')
```

启动时的崩溃，通过把 `PermissionReviewer` 改成 lazy 持有 `llm_registry`、删掉 lifespan 里 eager 取 provider 的那行来解决。`BaseAgent`、`AgentLoop`、Event Bus 完全不动。

## 4. 后端改动

### 4.1 `sebastian/permissions/reviewer.py` — Reviewer lazy 化

**为什么改**：lifespan 启动时崩溃的真正源头是 `reviewer = PermissionReviewer(provider=default_provider, model=default_model)`，它要求构造时就拿到一个具体的 `LLMProvider` 实例。

**改成**：reviewer 持有 `llm_registry` 引用，在每次 `review()` 调用时再 lazy 解析 provider。

```python
class PermissionReviewer:
    def __init__(self, llm_registry: LLMProviderRegistry) -> None:
        self._llm_registry = llm_registry

    async def review(self, tool_name, tool_input, reason, task_goal) -> ReviewDecision:
        try:
            provider, model = await self._llm_registry.get_default_with_model()
        except RuntimeError:
            return ReviewDecision(
                decision="escalate",
                explanation="未配置 LLM Provider，无法自动审查工具调用，请人工批准。",
            )
        # ... 原有 LLM 调用逻辑，使用 provider/model
```

**收益**：
- 启动不再依赖 DB 有 provider
- 用户配好 provider 后，下一次 review 自动生效，无需重启
- 无 provider 时 reviewer 默认 escalate（保守安全），对用户表现为"工具调用需要手动批准"

### 4.2 `sebastian/gateway/app.py` — 删 eager 取 provider

**改动**：
- 删除第 78 行 `default_provider, default_model = await llm_registry.get_default_with_model()`
- 第 102 行改为 `reviewer = PermissionReviewer(llm_registry=llm_registry)`

**校验**：lifespan 内不再有任何对 `get_default_with_model()` 的直接调用。

### 4.3 `sebastian/gateway/routes/turns.py` — 新增 pre-check helper

新增模块级 helper：

```python
async def _ensure_llm_ready(agent_type: str) -> None:
    """检查指定 agent_type 是否有可用 LLM provider，无则抛 HTTP 400。"""
    import sebastian.gateway.state as state
    try:
        await state.llm_registry.get_provider(agent_type)
    except RuntimeError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_llm_provider",
                "message": "尚未配置 LLM Provider，请前往 Settings → 模型 页面添加",
            },
        )
```

**关键设计点**：
- 用 `get_provider(agent_type)` 而非 `get_default_with_model()`。前者已经支持 `manifest.toml` 的 per-agent `[llm]` 配置，未来在 DB 加 per-agent binding 时仍然向后兼容。
- pre-check 在 `get_or_create_session` **之前**调用，避免产生 orphan session。

`send_turn` 路由开头加一行：

```python
@router.post("/turns")
async def send_turn(body, _auth):
    import sebastian.gateway.state as state
    await _ensure_llm_ready("sebastian")  # ← 新增
    session = await state.sebastian.get_or_create_session(body.session_id, body.content)
    ...
```

### 4.4 `sebastian/gateway/routes/sessions.py` — 同样加 pre-check

`_ensure_llm_ready` helper 在 `turns.py` 定义后，sessions.py 通过 `from sebastian.gateway.routes.turns import _ensure_llm_ready` 复用（避免重复定义）。

调用点：
- `create_agent_session` 路由开头：`await _ensure_llm_ready(agent_type)`，在 `Session(...)` 构造前
- `send_turn_to_session` 路由：`await _ensure_llm_ready(session.agent_type)`，在 `_resolve_session` 之后、`_schedule_session_turn` 之前

**为什么 send_turn_to_session 在 resolve 之后**：要先知道 session 的 agent_type 才能正确调用 `get_provider(agent_type)`。

## 5. 前端改动

### 5.1 错误识别契约

后端 400 响应体格式（FastAPI 标准）：

```json
{
  "detail": {
    "code": "no_llm_provider",
    "message": "尚未配置 LLM Provider，请前往 Settings → 模型 页面添加"
  }
}
```

前端用 `error.response.status === 400 && error.response.data?.detail?.code === "no_llm_provider"` 判定。**不**依赖 message 字符串匹配。

### 5.2 `ui/mobile/src/api/turns.ts` & `sessions.ts` — 错误透传

axios 默认会把非 2xx 响应转成 throw，response 数据保留在 `error.response`。无需修改 API 函数，**前提**是当前的 axios 实例没有把错误对象吞掉。

**TODO 实现时验证**：检查 `ui/mobile/src/api/client.ts` 的 axios 实例是否有响应拦截器在错误路径上做了破坏性处理；如果有，确保 `detail.code` 能透传出来。

### 5.3 `ui/mobile/src/store/conversation.ts` — 加 ephemeral errorBanner

在 `ConversationState` 的 per-session 状态里增加一个字段：

```ts
type SessionState = {
  // ... 现有字段
  errorBanner: { code: string; message: string } | null;
};
```

新增 action：

```ts
setErrorBanner(sessionId: string, banner: { code: string; message: string } | null): void
```

**生命周期**：
- 用户发消息失败时 set
- 用户成功发出下一条消息时清空（在 `appendUserMessage` 里同步清掉）
- session 切换时不需要主动清，因为是 per-session 状态
- 不持久化，不写 DB

**草稿 session 处理**：`currentSessionId === null` 时（用户首次进入还没建任何 session），errorBanner 不挂在 sessions map 里，而是 conversation store 顶层加一个独立字段 `draftErrorBanner: { code, message } | null`。避免用 `"__draft__"` 这种特殊 key 污染 sessions map。

新增 action：

```ts
setDraftErrorBanner(banner: { code: string; message: string } | null): void
```

### 5.4 `ui/mobile/app/index.tsx` & `app/subagents/session/[id].tsx` — handleSend 错误识别

`handleSend` 的 catch 块改造：

```ts
async function handleSend(text: string) {
  try {
    const { sessionId } = await sendTurn(currentSessionId, text);
    // ... 现有逻辑
  } catch (err: any) {
    const code = err?.response?.data?.detail?.code;
    if (code === 'no_llm_provider') {
      const message = err.response.data.detail.message;
      const store = useConversationStore.getState();
      if (currentSessionId) {
        store.setErrorBanner(currentSessionId, { code, message });
      } else {
        store.setDraftErrorBanner({ code, message });
      }
    } else {
      Alert.alert('发送失败，请重试');
    }
  }
}
```

`subagents/session/[id].tsx` 同样处理。

### 5.5 `ui/mobile/src/components/conversation/` — 错误气泡组件

新增一个组件 `ErrorBanner.tsx`（或就近放在已有目录里）：

```tsx
type Props = {
  message: string;
  onAction: () => void;
};

function ErrorBanner({ message, onAction }: Props) {
  return (
    <View style={styles.banner}>
      <Text style={styles.text}>{message}</Text>
      <TouchableOpacity onPress={onAction}>
        <Text style={styles.action}>前往 Settings</Text>
      </TouchableOpacity>
    </View>
  );
}
```

视觉位置：渲染在 `ConversationView` 内对话气泡列表的**底部**（最近一条消息下方），而非顶部 banner，符合 "对话界面内显示" 的原始描述。

跳转：`onAction = () => router.push('/settings')`。**注**：未来 LLM 设置移到 `/settings/llm-providers` 时改一行即可，本次不预留。

### 5.6 ConversationView 集成

`ConversationView` 从 conversation store 读 errorBanner，存在则在消息列表底部渲染 `<ErrorBanner>`。空 session（草稿态）也要能渲染——这意味着 `app/index.tsx` 的 `isEmpty` 分支也要能展示 errorBanner，或者把 errorBanner 提到 `ChatScreen` 顶层渲染。

**实现选择**：把 `ErrorBanner` 渲染逻辑放在 `ChatScreen` 的 `MessageInput` 上方、`ConversationView` / `EmptyState` 下方。这样无论是空 session 还是已有 session，都能正确显示。

## 6. 错误清除时机

| 触发动作 | 是否清除 errorBanner |
|---|---|
| 用户成功发出新消息（HTTP 200） | ✅ 清除 |
| 用户切换到另一个 session | ✅ 清除（实际是显示新 session 自己的 banner，可能是 null） |
| 用户配好 provider 回到对话 | ❌ 不主动清。下一次发消息成功后自然消失 |
| 用户点击 ErrorBanner 上的"前往 Settings" | ❌ 不清。回来后仍能看见，提醒用户问题没解决 |

## 7. 测试

### 7.1 后端单元测试

- `tests/unit/test_permission_reviewer.py`：reviewer 在 registry 抛 RuntimeError 时返回 escalate
- `tests/integration/test_gateway_no_provider.py`：
  - 空数据库时 lifespan 正常完成（不抛异常）
  - `POST /api/v1/turns` 返回 400 + 正确 code
  - `POST /api/v1/agents/{type}/sessions` 返回 400 + 正确 code
  - `POST /api/v1/sessions/{id}/turns` 返回 400 + 正确 code
  - 有 provider 时上述请求正常通过

### 7.2 前端手动验证

- 空数据库启动后端
- App 内发消息 → 对话区出现红色错误气泡 + "前往 Settings" 按钮
- 点击按钮跳转到 Settings 页
- 在 Settings 加 provider 并设为默认
- 回到对话页，再次发消息 → 成功，错误气泡消失

## 8. 不做的事（YAGNI）

- ❌ 不引入 `EventType.TURN_ERROR`、不改 `BaseAgent` / `AgentLoop` / EventBus
- ❌ 不持久化错误到 episodic store
- ❌ 不为 reviewer 单独配 provider 预留接口（lazy 改造已经为它铺好路）
- ❌ 不为 LLM 设置子页 `/settings/llm-providers` 预留路由
- ❌ 不动输入框组件结构（独立工作）
- ❌ 不加任何 env key fallback 类的兼容补丁

## 9. 改动文件清单

**后端（4 个文件）**

| 文件 | 改动 |
|---|---|
| `sebastian/permissions/reviewer.py` | 构造函数改持有 `llm_registry`；`review()` 内 lazy 解析 |
| `sebastian/gateway/app.py` | 删 eager 取 provider；reviewer 构造改用 registry |
| `sebastian/gateway/routes/turns.py` | 新增 `_ensure_llm_ready` helper；`send_turn` 调用 |
| `sebastian/gateway/routes/sessions.py` | `create_agent_session` + `send_turn_to_session` 加 pre-check |

**前端（5-6 个文件）**

| 文件 | 改动 |
|---|---|
| `ui/mobile/src/store/conversation.ts` | 加 errorBanner 字段 + setErrorBanner action |
| `ui/mobile/app/index.tsx` | handleSend catch 识别 code；渲染 ErrorBanner |
| `ui/mobile/app/subagents/session/[id].tsx` | 同上 |
| `ui/mobile/src/components/conversation/ErrorBanner.tsx` | 新增组件 |
| `ui/mobile/src/components/conversation/index.ts` | 导出 ErrorBanner（如需要） |
| `ui/mobile/src/api/client.ts` | （可能）确认错误透传，无需改动则跳过 |

**测试**

| 文件 | 改动 |
|---|---|
| `tests/unit/test_permission_reviewer.py` | 新增或更新：lazy 解析失败 → escalate |
| `tests/integration/test_gateway_no_provider.py` | 新增：空 DB 启动 + 三个路由的 400 行为 |

## 10. 风险与注意

- **axios 错误透传**：实现时第一步就要确认 `client.ts` 的 axios 实例不会吞 `error.response.data.detail`。如果有响应拦截器破坏了结构，需要先修拦截器。
- **`get_provider(agent_type)` 的 fallback 行为**：当前实现是 manifest 没配 → fallback 到 `get_default_with_model()`。也就是说，未来某个 agent 在 DB 里绑了独立 provider 但没默认 provider 的场景，需要 `get_provider` 内部支持 DB binding 才能正确放行。这是**未来工作的前提**，本次任务不需要做。
- **draft session 的 errorBanner**：草稿态 `currentSessionId === null` 时，errorBanner 需要有处可挂。推荐顶层 state 加 `draftErrorBanner`，不要污染 sessions map。
