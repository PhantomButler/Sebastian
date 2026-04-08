# Thinking Effort 控制设计

**版本**：v1.0
**日期**：2026-04-08
**状态**：待实施
**关联**：
- `2026-04-01-sebastian-architecture-design.md` §7（LLM Provider 管理）
- `2026-04-03-phase1-core-runtime-design.md` §3（流事件）、§4（SSE 协议）

---

## 1. 背景与问题

Phase 1 设计时只覆盖了"思考事件接收链路"——`ThinkingBlockStart/Delta/Stop` 事件类型、SSE 协议、前端折叠 UI 全部就位。但**当时未设计"如何在请求侧开启思考"**：

- [sebastian/llm/anthropic.py:42-49](../../sebastian/llm/anthropic.py#L42-L49) 调 Anthropic SDK 时不传 `thinking` 参数。Claude 3.7+ Extended Thinking 必须显式 opt-in，因此服务端永远收不到 thinking block，前端折叠卡片永远不出现。
- [sebastian/llm/openai_compat.py](../../sebastian/llm/openai_compat.py) 的 `thinking_format` 是 Provider 创建时绑死的 DB 配置，不是 per-turn 控制。OpenAI o 系列的 `reasoning_effort` 完全没有接入。
- 前端 [ui/mobile/src/components/composer/ThinkButton.tsx](../../ui/mobile/src/components/composer/ThinkButton.tsx) 已实现开关，但 [ui/mobile/app/index.tsx:70](../../ui/mobile/app/index.tsx#L70) 的 `handleSend` 把 `_opts` 用下划线前缀直接丢弃，[ui/mobile/src/api/turns.ts](../../ui/mobile/src/api/turns.ts) 的请求体也没有 thinking 字段。

整条"前端开关 → API 请求 → Provider"链路从未被打通。

另一个潜在的副作用：[sebastian/core/agent_loop.py:123-126](../../sebastian/core/agent_loop.py#L123-L126) 在多轮回填 thinking block 时只塞了 `{"type":"thinking","thinking":...}`，**缺 `signature` 字段**。Anthropic Extended Thinking 在多轮带 tool result 回传时，前一轮的 thinking block 必须原样带 signature 才不会被 API 拒。一旦真正开启 thinking + 多轮工具调用，这条路径会立刻挂掉。

---

## 2. 目标与非目标

### 目标

1. 输入框的"思考"按钮真正控制当前 turn 是否开启思考，并支持档位选择（off / low / medium / high / max）。
2. 同时支持 Anthropic Adaptive Thinking、Anthropic 旧版 Extended Thinking、OpenAI `reasoning_effort` 三种请求形态。
3. 对"模型本身就是 reasoning 模型"（DeepSeek-R1、llama.cpp Qwen 等）和"模型不支持思考控制"（GPT-4o）两种边缘情况，UI 给出明确表现。
4. 修复多轮 thinking signature 缺失，让"开启思考 + 多轮工具调用"的链路真正可用。
5. 前端档位选择按 provider 的能力动态显示。

### 非目标

- 不在 Settings UI 暴露 budget_tokens 数值配置。budget 是模型行为参数，不是用户业务参数，写死在 Provider 类常量里即可。
- 不引入 per-agent 的 thinking 默认配置（manifest.toml 的 `[llm]` 部分本期不动）。
- 不实现 thinking-only 的 SSE 子事件流（已有 `thinking_block.*` / `turn.thinking_delta` 即可）。
- 不重写 `thinking_format` 字段——它管"如何解析返回的 reasoning"，与本期新增的 `thinking_capability`（管"如何发起请求"）正交。

---

## 3. 核心设计

### 3.1 Provider 能力模型：新增 `thinking_capability` 字段

`LLMProviderRecord` 新增一个枚举字段，与现有 `thinking_format` **正交并存**：

```python
# sebastian/store/models.py
class LLMProviderRecord(Base):
    ...
    thinking_format: Mapped[str | None]      # 已有：解析返回侧
    thinking_capability: Mapped[str | None]  # 新增：请求侧能力
```

`thinking_capability` 取值：

| 值 | 含义 | UI 档位 | Provider 请求行为 |
|---|---|---|---|
| `none` | 模型不支持思考控制 | 隐藏按钮 | 不传任何 thinking 参数 |
| `effort` | 支持 4 档 effort | off / low / medium / high | 见 §3.2 |
| `adaptive` | Anthropic 原生 Adaptive | off / low / medium / high / max | 见 §3.2 |
| `always_on` | 模型必然思考 | 不可点徽标"思考·自动" | 不传参数（解析侧由 `thinking_format` 决定） |

`thinking_format` 与 `thinking_capability` 的组合矩阵（典型模型）：

| 模型 | provider_type | thinking_capability | thinking_format |
|---|---|---|---|
| Claude Opus 4.6 / Sonnet 4.6 | anthropic | adaptive | None |
| Claude 3.7 Sonnet（旧 Extended Thinking） | anthropic | effort | None |
| OpenAI o3 / o4 系列 | openai | effort | None |
| GPT-4o / GPT-4.1 | openai | none | None |
| DeepSeek-R1 | openai | always_on | reasoning_content |
| llama.cpp Qwen `<think>` | openai | always_on | think_tags |

### 3.2 Provider 内部 effort 翻译表

每个 Provider 类持有一份 `EFFORT_TO_REQUEST` 常量表，把统一的 effort 字符串翻译成 SDK 调用参数。Sebastian 业务层不感知数值。

**`AnthropicProvider`**（`thinking_capability=adaptive`）：

```python
ADAPTIVE_EFFORT_TO_REQUEST = {
    "off":    None,  # 不传 thinking
    "low":    {"thinking": {"type": "adaptive"},
               "output_config": {"effort": "low"}},
    "medium": {"thinking": {"type": "adaptive"},
               "output_config": {"effort": "medium"}},
    "high":   {"thinking": {"type": "adaptive"},
               "output_config": {"effort": "high"}},
    "max":    {"thinking": {"type": "adaptive"},
               "output_config": {"effort": "max"}},
}
```

**`AnthropicProvider`**（`thinking_capability=effort`，旧版 Extended Thinking）：

```python
FIXED_EFFORT_TO_BUDGET = {
    "off":    None,
    "low":    2048,
    "medium": 8192,
    "high":   24576,
}
# 实际请求：thinking={"type": "enabled", "budget_tokens": N}
# 注意：budget_tokens 必须 < max_tokens，调用前需校验/抬升 max_tokens
```

**`OpenAICompatProvider`**（`thinking_capability=effort`）：

```python
EFFORT_TO_REASONING_EFFORT = {
    "off":    None,  # 不传 reasoning_effort
    "low":    "low",
    "medium": "medium",
    "high":   "high",
}
# 实际请求：在 chat.completions.create 调用中加 reasoning_effort=...
```

`thinking_capability=none / always_on` 的 Provider 实例直接忽略 effort 参数。

### 3.3 API 协议变更

**`POST /api/v1/turns` 请求体新增字段**（[sebastian/gateway/routes/turns.py:29-32](../../sebastian/gateway/routes/turns.py#L29-L32)）：

```python
class SendTurnRequest(BaseModel):
    content: str
    session_id: str | None = None
    thinking_effort: str | None = None  # off | low | medium | high | max | None
```

`None` 与 `"off"` 在 Provider 侧等价。保留 `None` 是为了识别"老 client 没传"与"新 client 显式选了 off"两种状态——便于后续日志/灰度。

**`GET /api/v1/llm/providers` 响应字段补充**：

返回的每条 record 必须包含 `thinking_capability`，前端用它决定档位 UI。已有的 `thinking_format` 字段也保留返回（前端可能用于 debug 显示，但不影响档位判断）。

### 3.4 请求链路透传

`thinking_effort` 需要逐层下沉到 Provider。每层签名加一个可选参数：

```
SendTurnRequest.thinking_effort
  ↓
state.sebastian.run_streaming(content, session_id, thinking_effort=...)
  ↓
BaseAgent.run_streaming(..., thinking_effort=...)
  ↓
BaseAgent._stream_inner(..., thinking_effort=...)
  ↓
AgentLoop.stream(..., thinking_effort=...)
  ↓
LLMProvider.stream(..., thinking_effort=...)
```

`LLMProvider.stream` 抽象基类签名（[sebastian/llm/provider.py:23](../../sebastian/llm/provider.py#L23)）改为：

```python
async def stream(
    self,
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    block_id_prefix: str = "",
    thinking_effort: str | None = None,
) -> AsyncGenerator[LLMStreamEvent, None]: ...
```

各 Provider 实现按自身 `thinking_capability` 决定如何使用此参数：
- `none / always_on` → 完全忽略
- `effort / adaptive` → 查表转 SDK 参数；为 `None` 或 `"off"` 时不传

### 3.5 多轮 thinking signature 修复

[sebastian/core/stream_events.py](../../sebastian/core/stream_events.py) 的 `ThinkingBlockStop` 事件新增字段：

```python
@dataclass
class ThinkingBlockStop:
    block_id: str
    thinking: str
    signature: str | None = None  # 仅 Anthropic 有；OpenAI 路径为 None
```

[sebastian/llm/anthropic.py](../../sebastian/llm/anthropic.py) 在 `content_block_stop` 分支取 `block.signature` 一并传出。

[sebastian/core/agent_loop.py:123-126](../../sebastian/core/agent_loop.py#L123-L126) 回填 assistant_blocks 时带上 signature：

```python
if isinstance(event, ThinkingBlockStop):
    if not is_openai:
        block_dict = {"type": "thinking", "thinking": event.thinking}
        if event.signature is not None:
            block_dict["signature"] = event.signature
        assistant_blocks.append(block_dict)
    yield event
```

OpenAI 路径不需要 signature，本身也用不到（OpenAI 兼容格式不回传 thinking 给下一轮）。

### 3.6 前端：档位 UI 与能力来源

#### 能力来源

App 启动后（以及 Settings 页修改 provider 后）调 `GET /api/v1/llm/providers`，找 `is_default=true` 的那条，把 `thinking_capability` 存到 `useSettingsStore`：

```ts
interface SettingsStore {
  ...
  currentThinkingCapability: 'none' | 'effort' | 'adaptive' | 'always_on' | null;
}
```

切换默认 provider 时若当前选中的档位不在新 capability 的可用集合内，自动降级到该 capability 的最高可用档位（adaptive→effort 时 max→high），并通过一次 toast 提示用户。

#### `useComposerStore` 改造

把 `thinkingBySession: Record<string, boolean>` 改成：

```ts
type ThinkingEffort = 'off' | 'low' | 'medium' | 'high' | 'max';

interface ComposerStore {
  effortBySession: Record<string, ThinkingEffort>;
  lastUserChoice: ThinkingEffort;  // 全局最近一次手动选择，作为新 session 默认
  getEffort(sessionId: string | null): ThinkingEffort;
  setEffort(sessionId: string | null, effort: ThinkingEffort): void;
  ...
}
```

新建 session 时默认值 = `lastUserChoice`，首次安装时 `lastUserChoice = 'off'`。`lastUserChoice` 持久化到 AsyncStorage（与现有 settings 持久化机制一致）。

#### `ThinkButton` 改造

按 capability 决定形态：

| capability | ThinkButton 形态 |
|---|---|
| `null`（未加载/未配置 provider） | 灰色 disabled，文案"思考" |
| `none` | **不渲染** |
| `effort` | 可点 pill，文案"思考·{当前档位}"。点击弹出 ActionSheet，选项 = off / low / medium / high |
| `adaptive` | 可点 pill，文案"思考·{当前档位}"。点击弹出 ActionSheet，选项 = off / low / medium / high / max |
| `always_on` | 不可点 pill，文案"思考·自动"，灰色背景 |

ActionSheet 用 `@expo/react-native-action-sheet` 或自己实现一个轻量 BottomSheet 组件（项目已有 BottomSheet 习惯则复用）。每个选项显示档位名称 + 简短说明（如 "low — 少量思考"）。

#### `handleSend` 修复

[ui/mobile/app/index.tsx:70](../../ui/mobile/app/index.tsx#L70)：

```ts
async function handleSend(text: string, opts: { effort: ThinkingEffort }) {
  const { sessionId } = await sendTurn(currentSessionId, text, opts.effort);
  ...
}
```

[ui/mobile/src/api/turns.ts](../../ui/mobile/src/api/turns.ts)：

```ts
export async function sendTurn(
  sessionId: string | null,
  content: string,
  thinkingEffort: ThinkingEffort,
): Promise<{ sessionId: string; ts: string }> {
  const { data } = await apiClient.post('/api/v1/turns', {
    session_id: sessionId,
    content,
    thinking_effort: thinkingEffort === 'off' ? null : thinkingEffort,
  });
  ...
}
```

`'off'` 在前端发送时映射为 `null`，与"老 client 没传"同义，简化后端判断。

### 3.7 Sub-Agent session 的 turns 路由

[sebastian/gateway/routes/sessions.py] 中 sub-agent 的 `POST /api/v1/sessions/{id}/turns` 同样需要接受 `thinking_effort` 字段并透传到对应 agent 的 `run_streaming`。改动与 §3.3 / §3.4 对称。

---

## 4. 数据迁移

`LLMProviderRecord` 新增 `thinking_capability` 字段：

- 字段类型：`String(20), nullable=True`
- 默认值：`None`
- 现存记录的 capability 由用户在 Settings 页面手动补全；未补全时前端按 `null` 处理（按钮 disabled，文案灰显）。
- 不写 SQL 迁移脚本——本项目走 `Base.metadata.create_all` 直建表。已存在的 SQLite 库需要用户手动 ALTER 或删库重建。Sebastian 当前是个人开发期，可接受。

`POST /api/v1/llm/providers` 与 `PUT /api/v1/llm/providers/{id}` 请求体增加 `thinking_capability` 字段（可选），Settings 页面新增一个下拉选择器。

---

## 5. 测试计划

### 单元测试

- `tests/unit/test_anthropic_provider.py`：
  - capability=adaptive，effort=high → 验证 SDK 调用参数包含 `thinking={"type":"adaptive"}` 和 `output_config={"effort":"high"}`
  - capability=adaptive，effort=off → 验证不传 thinking
  - capability=effort，effort=medium → 验证 `thinking={"type":"enabled","budget_tokens":8192}`
  - capability=effort，budget_tokens 超过 max_tokens 时的处理
  - capability=none → 任意 effort 都不影响请求
- `tests/unit/test_openai_compat_provider.py`：
  - capability=effort，effort=high → 验证请求 kwargs 包含 `reasoning_effort="high"`
  - capability=effort，effort=off → 验证不传 reasoning_effort
- `tests/unit/test_agent_loop.py`：
  - 多轮 thinking + tool_use 场景，验证 assistant_blocks 中 thinking block 携带 signature

### 集成测试

- `tests/integration/test_turns_thinking.py`：
  - `POST /api/v1/turns` 带 `thinking_effort=high` → BaseAgent.run_streaming 收到正确参数
  - `POST /api/v1/turns` 不带 thinking_effort → Provider 收到 `None`
- `tests/integration/test_llm_providers_api.py`：
  - 创建 record 时 `thinking_capability` 字段被正确持久化与返回

### 手动验证

1. 用 Claude Opus 4.6 + adaptive，输入框选 high，发送一条复杂问题，验证：
   - SSE 流确实出现 `thinking_block.start` / `turn.thinking_delta` 事件
   - 前端折叠卡片正确出现并展开
2. 切换到 GPT-4o（capability=none），输入框按钮消失
3. 切换到 DeepSeek-R1（capability=always_on），按钮变成不可点徽标
4. 多轮工具调用 + 开启 thinking，验证不会出现 Anthropic API "missing signature" 报错
5. 切换 provider 后，原选中的 max 档位自动降到 high，toast 提示

---

## 6. 影响范围与文件清单

### 后端

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `sebastian/store/models.py` | 修改 | LLMProviderRecord 新增 `thinking_capability` 字段 |
| `sebastian/llm/provider.py` | 修改 | `stream()` 抽象签名加 `thinking_effort` 参数 |
| `sebastian/llm/anthropic.py` | 修改 | 加 EFFORT_TO_REQUEST 常量表，按 capability 翻译并注入请求；ThinkingBlockStop 带 signature |
| `sebastian/llm/openai_compat.py` | 修改 | 加 reasoning_effort 翻译，按 capability 注入请求 |
| `sebastian/llm/registry.py` | 修改 | 实例化 Provider 时把 record.thinking_capability 传入 |
| `sebastian/core/stream_events.py` | 修改 | `ThinkingBlockStop` 加 `signature` 字段 |
| `sebastian/core/agent_loop.py` | 修改 | `stream()` 加 `thinking_effort` 参数透传；多轮回填 thinking block 带 signature |
| `sebastian/core/base_agent.py` | 修改 | `run_streaming()` / `_stream_inner()` 加 `thinking_effort` 透传 |
| `sebastian/orchestrator/sebas.py` | 修改 | run_streaming 透传 |
| `sebastian/gateway/routes/turns.py` | 修改 | SendTurnRequest 加 thinking_effort，调用链透传 |
| `sebastian/gateway/routes/sessions.py` | 修改 | sub-agent 的 turns 端点对称改造 |
| `sebastian/gateway/routes/llm_providers.py` | 修改 | CRUD 接受/返回 thinking_capability |

### 前端

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `ui/mobile/src/types.ts` | 修改 | 新增 `ThinkingEffort` / `ThinkingCapability` 类型 |
| `ui/mobile/src/store/composer.ts` | 重构 | thinkingBySession → effortBySession，加 lastUserChoice |
| `ui/mobile/src/store/settings.ts` | 修改 | 加 currentThinkingCapability 字段 |
| `ui/mobile/src/api/turns.ts` | 修改 | sendTurn 接受 thinkingEffort 参数 |
| `ui/mobile/src/api/llm.ts`（新建或现有） | 修改 | 拉 providers 时存 capability 到 settings store |
| `ui/mobile/src/components/composer/ThinkButton.tsx` | 重构 | 按 capability 渲染不同形态，点击弹 ActionSheet |
| `ui/mobile/src/components/composer/index.tsx` | 修改 | onSend signature 改为 `{ effort }` |
| `ui/mobile/src/components/composer/EffortPicker.tsx` | 新建 | ActionSheet/BottomSheet 选择档位 |
| `ui/mobile/app/index.tsx` | 修改 | handleSend 真正使用 opts.effort |
| `ui/mobile/app/subagents/session/[id].tsx` | 修改 | 同上对称改造 |
| `ui/mobile/src/components/settings/LLMProviderConfig.tsx` | 修改 | 新增/编辑 provider 时增加 thinking_capability 选择器 |

### 文档

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `sebastian/llm/README.md` | 修改 | 补充 thinking_capability 字段说明与组合矩阵 |
| `ui/mobile/README.md` | 修改 | 修改导航表更新 ThinkButton / EffortPicker 路径 |
| `ui/mobile/src/components/composer/README.md` | 修改 | 补充 EffortPicker 与 ThinkButton 行为 |

---

## 7. 已确认决策

- [x] 范围：Anthropic + OpenAI 两条都打通，UI 一步到位用 effort 等级而非布尔
- [x] 数值：写死在 Provider 类常量表里，不进 DB，不进 Settings UI
- [x] Provider 能力建模：新增 `thinking_capability` 字段，与 `thinking_format` 正交并存
- [x] adaptive 模式 "off" 语义：完全不传 thinking 参数
- [x] 默认档位：跟随用户上次选择（持久化），首次安装为 off
- [x] always_on 的 UI：保留位置，显示不可点的"思考·自动"徽标
- [x] 前端档位 UI：点击 ThinkButton 弹出选择栏（ActionSheet/BottomSheet），按当前 provider capability 显示可用档位

---

*本文档 v1.0，2026-04-08。完成 Phase 1 Thinking 链路的请求侧补完，并修复多轮 signature 缺失。*
