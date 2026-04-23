---
version: "2.0"
last_updated: 2026-04-23
status: implemented
---

# LLM Provider 管理与 Thinking 控制

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 架构概览

Sebastian 通过 `sebastian/llm/` 抽象层支持多 LLM Provider。核心设计原则：

- Provider 配置持久化在 SQLite，运行时可通过 API 增删改切换
- `LLMProvider` 抽象接口统一 Anthropic / OpenAI 两种 SDK 差异
- AgentLoop 依赖注入 `LLMProvider`，不直接 import 任何 SDK
- API key 使用 Fernet 加密存储
- Thinking Effort 作为 per-turn 参数全链路透传

```
sebastian/llm/
├── provider.py          # LLMProvider 抽象基类
├── anthropic.py         # Anthropic SDK 适配
├── openai_compat.py     # OpenAI /v1/chat/completions 适配
├── registry.py          # Provider 注册表（DB 加载 + 缓存）
└── crypto.py            # API key Fernet 加密
```

---

## 2. 数据模型

### 2.1 LLMProviderRecord

文件：`sebastian/store/models.py`

```python
class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str]                        # uuid
    name: Mapped[str]                      # 用户命名，如 "Claude Opus 家用"
    provider_type: Mapped[str]             # "anthropic" | "openai"
    base_url: Mapped[str | None]           # 自定义 base URL（None 则用 SDK 默认）
    api_key_enc: Mapped[str]               # Fernet 加密存储
    model: Mapped[str]                     # "claude-opus-4-6" / "gpt-4o" 等
    thinking_format: Mapped[str | None]    # 返回侧 thinking 解析方式
    thinking_capability: Mapped[str | None]  # 请求侧 thinking 能力档位
    is_default: Mapped[bool]               # 全局默认 provider
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

### 2.2 API Key 加密方案

文件：`sebastian/llm/crypto.py`

使用 Fernet（AES-128-CBC + HMAC）加密。密钥从 JWT secret 派生（`SHA-256(jwt_secret)` → 32 字节 → Base64 编码），无需额外环境变量。

```python
def encrypt(plain: str) -> str: ...
def decrypt(enc: str) -> str: ...
```

GET 接口不返回 `api_key_enc` 明文，固定返回 `"***"`。

### 2.3 per-agent provider 绑定

Sub-agent 与具体 provider record 的绑定存在 `agent_llm_bindings` 表（见 §2.4），由 Settings UI 维护。无绑定则使用全局 `is_default=True` 的 provider。

> 旧版 `manifest.toml [llm]` 段已废弃并从代码中移除；manifest 里的 `[llm]` 段会被忽略。

### 2.4 AgentLLMBindingRecord

文件：`sebastian/store/models.py`

```python
class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str]                 # PK，如 "forge" / "aide" / "sebastian"
    provider_id: Mapped[str | None]         # FK → llm_providers.id, ON DELETE SET NULL
    thinking_effort: Mapped[str | None]     # "off" / "on" / "low" / "medium" / "high" / "max" / null
    updated_at: Mapped[datetime]
```

语义：
- `agent_type` 作主键 → 一个 agent 只有一条绑定（per-turn live 生效）
- `provider_id = NULL` 等价于无绑定 → fallback 全局默认
- 删除 provider 时外键自动置空对应 binding 的 `provider_id`（需要 SQLite `PRAGMA foreign_keys=ON`，已在 `sebastian/store/database.py` 的 `get_engine()` 启用）
- `thinking_effort`：按 `thinking_capability` 钳制（见 §6）；切换 provider 时后端强制重置为 null
- Sebastian orchestrator 纳入绑定体系（`is_orchestrator` 标记），与 sub-agent 走同一路径

> **实现差异**：spec 原文 `Sebastian orchestrator 不写入此表`。实际实现中 Sebastian 已纳入绑定，API 层已移除对 `agent_type == "sebastian"` 的屏蔽（列表、GET、PUT、DELETE 均已放行），响应中 Sebastian 带 `is_orchestrator: true` 字段。

---

## 3. LLMProvider 抽象接口

文件：`sebastian/llm/provider.py`

```python
class LLMProvider(ABC):
    """单次 LLM 调用抽象。多轮循环逻辑在 AgentLoop，不在此处。"""

    @abstractmethod
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

**职责边界**：`stream()` 只负责单次 LLM 调用，将原始 SDK 事件映射为 `LLMStreamEvent`。多轮循环由 AgentLoop 管理。

---

## 4. Anthropic 适配

文件：`sebastian/llm/anthropic.py`

封装 `anthropic.AsyncAnthropic`，将 `content_block_start/delta/stop` 原始事件映射为 `LLMStreamEvent`。

关键点：
- `ThinkingBlockStop` 和 `TextBlockStop` 携带完整内容字段（`thinking` / `text`），使 AgentLoop 能从事件本身重建 `assistant_content`
- `ThinkingBlockStop` 携带 `signature` 字段（从 `block.signature` 取），用于多轮回填
- Thinking 参数按 `thinking_capability` 翻译（见 §6）

---

## 5. OpenAI 兼容适配

文件：`sebastian/llm/openai_compat.py`

通过 `openai.AsyncOpenAI(base_url=..., api_key=...)` 调用，兼容任何实现 `/v1/chat/completions` 的端点。

### 5.1 thinking_format 字段

控制如何从返回中提取 thinking 内容。与 `thinking_capability`（控制请求侧）正交：

| 值 | 适用场景 | 处理方式 |
|----|---------|---------|
| `None`（默认） | 标准 GPT 系列 | 不提取 thinking |
| `"reasoning_content"` | DeepSeek API | 检测 `delta.reasoning_content` |
| `"think_tags"` | llama.cpp 本地部署 | 缓冲 `<think>...</think>` 标签 |

---

## 6. Thinking Effort 控制

### 6.1 thinking_capability 能力模型

`LLMProviderRecord.thinking_capability` 枚举：

| 值 | 含义 | UI 档位 | Provider 请求行为 |
|---|---|---|---|
| `none` | 不支持思考控制 | 隐藏按钮 | 不传 thinking 参数 |
| `toggle` | 只支持开关二态 | off / on（单点切换） | on → `{"type":"enabled"}`；off → 不传 |
| `effort` | 支持 4 档 effort | off / low / medium / high | 见翻译表 |
| `adaptive` | Anthropic 原生 Adaptive | off / low / medium / high / max | 见翻译表 |
| `always_on` | 模型必然思考 | 不可点徽标"思考·自动" | 不传参数 |

### 6.2 典型模型配置矩阵

| 模型 | provider_type | thinking_capability | thinking_format |
|------|--------------|-------------------|----------------|
| Claude Opus 4.6 / Sonnet 4.6 | anthropic | adaptive | None |
| Claude 3.7 Sonnet（旧版） | anthropic | effort | None |
| OpenAI o3 / o4 系列 | openai | effort | None |
| GPT-4o / GPT-4.1 | openai | none | None |
| DeepSeek-R1 | openai | always_on | reasoning_content |
| llama.cpp Qwen `<think>` | openai | always_on | think_tags |
| 第三方 Anthropic-format 代理 | anthropic | toggle | None |

### 6.3 Provider 内部 effort 翻译表

每个 Provider 类持有常量表，把统一 effort 字符串翻译成 SDK 调用参数。

**AnthropicProvider（adaptive）**：

```python
ADAPTIVE_EFFORT_TO_REQUEST = {
    "off":    None,
    "low":    {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}},
    "medium": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}},
    "high":   {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
    "max":    {"thinking": {"type": "adaptive"}, "output_config": {"effort": "max"}},
}
```

**AnthropicProvider（effort，旧版 Extended Thinking）**：

```python
FIXED_EFFORT_TO_BUDGET = {
    "off":    None,
    "low":    2048,
    "medium": 8192,
    "high":   24576,
}
# 请求：thinking={"type": "enabled", "budget_tokens": N}
# 注意：budget_tokens 必须 < max_tokens
```

**OpenAICompatProvider（effort）**：

```python
EFFORT_TO_REASONING_EFFORT = {
    "off":    None,
    "low":    "low",
    "medium": "medium",
    "high":   "high",
}
# 请求 kwargs 中加 reasoning_effort=...
```

`thinking_capability=none / always_on` 的 Provider 直接忽略 effort 参数。

### 6.4 全链路透传

Thinking effort 从 agent_llm_bindings 表的 `thinking_effort` 字段读取（而非前端请求参数）：

```
AgentLLMBindingRecord.thinking_effort
  ↓
LLMProviderRegistry.get_provider(agent_type) → ResolvedProvider(thinking_effort=...)
  ↓
BaseAgent._stream_inner(..., thinking_effort=...)
  ↓
AgentLoop.stream(..., thinking_effort=...)
  ↓
LLMProvider.stream(..., thinking_effort=...)
```

> **迁移说明**：旧版 `SendTurnRequest.thinking_effort` 字段已从 API 中移除。前端不再在对话页传递 effort 参数，改由后端从 binding 表读取。

### 6.5 多轮 thinking signature 修复

`ThinkingBlockStop` 事件携带 `signature` 字段。AgentLoop 回填 assistant_blocks 时：

```python
if isinstance(event, ThinkingBlockStop):
    block_dict = {"type": "thinking", "thinking": event.thinking}
    if event.signature is not None:
        block_dict["signature"] = event.signature
    assistant_blocks.append(block_dict)
```

Anthropic Extended Thinking 在多轮带 tool result 回传时，前一轮的 thinking block 必须原样带 signature，否则 API 拒绝。

---

## 7. LLMProviderRegistry

文件：`sebastian/llm/registry.py`

### 7.1 ResolvedProvider

`get_provider()` 返回 `ResolvedProvider` 数据类，一次性携带 binding 的 thinking 配置：

```python
@dataclass
class ResolvedProvider:
    provider: LLMProvider
    model: str
    thinking_effort: str | None      # 已按 capability 钳制过
    capability: str | None           # provider 的 thinking_capability
```

### 7.2 get_provider 查询优先级

```python
async def get_provider(self, agent_type: str | None = None) -> ResolvedProvider:
    """
    优先级：
    1. agent_type 对应的 binding 存在且 provider_id 非空 → 用对应 record
    2. 否则 fallback 全局 is_default=True
    3. 无默认 → 抛 RuntimeError
    """
```

查询源切换后，`_read_manifest_llm` / `_get_by_type`（按 type 匹配的旧逻辑）已删除。manifest.toml 的 `[llm]` 段不再生效。

### 7.3 thinking 参数钳制

`_coerce_thinking(effort, capability)` 在返回前按 provider 的 `thinking_capability` 钳制 effort：
- `NONE` / `ALWAYS_ON` → 强制 `null`
- `TOGGLE` → 仅允许 `off` / `on`
- `EFFORT` → 允许 `off` / `low` / `medium` / `high`
- `ADAPTIVE` → 允许 `off` / `low` / `medium` / `high` / `max`

### 7.4 BaseAgent 消费

```python
resolved = await self._llm_registry.get_provider(self.name)
thinking_effort_for_llm = resolved.thinking_effort
# ALWAYS_ON provider 由 adapter 内部处理，不传参
response = await resolved.provider.chat(model=resolved.model, ..., thinking_effort=thinking_effort_for_llm)
```

生效时机：per-turn live。用户改绑定 → 正在进行的 turn 保持旧 provider → 下一个 turn 使用新 provider。

启动时从 DB 加载所有 provider 记录，缓存实例（避免重复创建 SDK client）。API 增删改后刷新缓存。

---

## 8. AgentLoop / BaseAgent 集成

### 8.1 AgentLoop 改造

构造器接收 `LLMProvider`，不直接 import SDK：

```python
class AgentLoop:
    def __init__(self, provider: LLMProvider, ...): ...
```

内层循环调用 `provider.stream()` 获取 `LLMStreamEvent`，逻辑不变。

### 8.2 BaseAgent 集成

`BaseAgent.__init__()` 从 `LLMProviderRegistry` 获取 provider 并注入 AgentLoop：

```python
provider = await llm_registry.get_provider(
    provider_type=self._agent_config.llm_provider_type,
    model=self._agent_config.llm_model,
)
self._loop = AgentLoop(provider=provider, ...)
```

---

## 9. 前端 Thinking 控制 UI

### 9.1 架构迁移

Thinking 配置从"对话页 Composer 每次选"迁移为"Agent Binding 编辑页持久化一次配好"。

**已删除组件**：
- `ui/composer/ThinkButton.kt` — 整个文件删除
- `ui/composer/EffortPickerCard.kt` — 整个文件删除
- `ChatViewModel.activeThinkingEffort` / `setEffort()` — 删除
- `SendTurnRequest.thinkingEffort` — 删除
- `ChatRepositoryImpl` 中 effort → 后端字符串的映射逻辑 — 删除

**Composer 改造**：ThinkButton 原占位不收缩 Composer 高度，`onShowEffortPicker` 回调已移除。

### 9.2 AgentBindingsPage（列表页）

Settings → Agent LLM Bindings 列表，分三个区：

- **Orchestrator**（置顶，仅 Sebastian）
- **Memory Components**（记忆相关组件）
- **Sub-Agents**（按后端返回顺序）

每个 item 显示 agent 名称 + provider/effort 摘要，点击进入 Editor 次级页。

> **实现差异**：spec 原文仅分 Orchestrator / Sub-Agents 两个区。实现额外增加了 Memory Components 区。

> **实现文件**：`ui/mobile-android/.../ui/settings/AgentBindingsPage.kt`（179 行）

### 9.3 AgentBindingEditorPage（编辑页）

每个 agent 独立的次级设置页：

- **Provider 卡片**：点击弹 `ProviderPickerDialog`
- **Thinking Depth 滑块**：按 `effectiveCapability` 渲染

> **实现文件**：`ui/mobile-android/.../ui/settings/AgentBindingEditorPage.kt`（190 行）

### 9.4 ProviderPickerDialog

居中浮层选择器（`ModalBottomSheet`），首行 "Use default provider"（代表 null），其余为 provider 池条目。当前选中项打勾。

> **实现差异**：spec 原文用 `AlertDialog` 居中浮层。实现使用 `ModalBottomSheet`。

> **实现文件**：`ui/mobile-android/.../ui/settings/components/ProviderPickerDialog.kt`（183 行）

### 9.5 EffortSlider

按 capability 渲染不同形态：

| capability | 形态 |
|---|---|
| `NONE` | 思考区不渲染 |
| `TOGGLE` | `SebastianSwitch`（Off/On） |
| `EFFORT` | 4 档 Slider（Off/Low/Medium/High） |
| `ADAPTIVE` | 5 档 Slider（Off/Low/Medium/High/Max） |
| `ALWAYS_ON` | 只读 label `Thinking: Always on` |

> **实现文件**：`ui/mobile-android/.../ui/settings/components/EffortSlider.kt`（96 行）

### 9.6 即时保存与防抖

`AgentBindingEditorViewModel`（@AssistedInject，keyed by agentType）：
- 每个 setter debounce 300ms 合并为一次 PUT
- PUT 失败 → snackbar + state 回滚到保存前快照
- Provider 切换时本地立即重置 effort + snackbar 提示
- 越界钳制：初始化时 effort 不在 capability 支持刻度中，钳到最高合法刻度并触发 PUT 纠正

> **实现文件**：`ui/mobile-android/.../viewmodel/AgentBindingEditorViewModel.kt`（184 行）

---

## 10. Gateway 路由

### Provider CRUD（路径保持不变）
```
GET    /api/v1/llm/providers              # 列表（api_key 返回 "***"）
POST   /api/v1/llm/providers              # 新增
PUT    /api/v1/llm/providers/{id}         # 修改
DELETE /api/v1/llm/providers/{id}         # 删除
POST   /api/v1/llm/providers/{id}/set-default  # 设为全局默认
```

POST/PUT 请求体包含 `thinking_capability` 字段（可选），Settings 页新增对应下拉选择器。

### Agent 列表（扩展字段）
```
GET    /api/v1/agents
       响应每条 agent 包含：
       - is_orchestrator: bool  （Sebastian 为 true，其余为 false）
       - binding: { agent_type, provider_id, thinking_effort } | null
```

> **实现差异**：spec 原文用扁平 `bound_provider_id` 字段。实际实现返回嵌套 `binding` 对象，包含完整绑定信息（agent_type、provider_id、thinking_effort）。Android DTO 从 `binding?.providerId` 派生 `boundProviderId`。

> **Sebastian 屏蔽已解除**：`agent_type == "sebastian"` 不再被排除。所有 agent（含 orchestrator）均可查询和设置 binding。

### Agent 绑定管理（新增）
```
PUT    /api/v1/agents/{agent_type}/llm-binding
       body: { "provider_id": str | null }
DELETE /api/v1/agents/{agent_type}/llm-binding
```

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
