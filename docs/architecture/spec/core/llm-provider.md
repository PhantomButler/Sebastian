---
version: "3.0"
last_updated: 2026-04-25
status: implemented
---

# LLM Provider 管理与 Thinking 控制

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*

---

## 1. 架构概览

Sebastian 通过 `sebastian/llm/` 抽象层支持多 LLM Provider。核心设计原则：

- LLM 配置采用三层架构：**Catalog**（内置 Provider/Model 元数据）→ **Account**（用户 API Key 绑定）→ **Binding**（per-agent 模型绑定）
- `LLMProvider` 抽象接口统一 Anthropic / OpenAI 两种 SDK 差异
- AgentLoop 依赖注入 `LLMProvider`，不直接 import 任何 SDK
- API key 使用 Fernet 加密存储
- Thinking Effort 作为 per-turn 参数全链路透传
- 每个模型保存准确的 `context_window_tokens`，供上下文压缩和未来 token 预算逻辑使用

```text
sebastian/llm/
├── provider.py          # LLMProvider 抽象基类
├── anthropic.py         # Anthropic SDK 适配
├── openai_compat.py     # OpenAI /v1/chat/completions 适配
├── registry.py          # 三层 Catalog → Account → Binding 解析
├── crypto.py            # API key Fernet 加密
└── catalog/
    ├── loader.py        # CatalogLoader + LLMModelSpec + LLMProviderSpec
    └── builtin_providers.json  # 内置 Provider/Model catalog
```

三层解析链路：

```text
                     builtin_providers.json
                              |
                              v
                        LLM Catalog
                              |
                              v
Agent / __default__ -> AgentLLMBindingRecord -> LLMAccountRecord
       binding            account_id+model_id      api_key/base_url
                              |
                              v
                       ResolvedProvider
              provider + model + model metadata
                              |
                              v
                   BaseAgent / Context Compaction
```

核心语义：

- Catalog provider 定义服务商默认连接参数和内置模型元数据。
- Account 是用户保存的一条连接实例，不代表模型。
- Binding 是唯一表达"谁使用哪个 account 和哪个 model"的地方。
- `agent_type="__default__"` 是全局默认 binding。普通 agent 无绑定时 fallback 到它。

---

## 2. 数据模型

### 2.1 LLMAccountRecord

替代旧 `LLMProviderRecord` 的连接与凭据部分。

```python
class LLMAccountRecord(Base):
    __tablename__ = "llm_accounts"

    id: Mapped[str]                        # uuid
    name: Mapped[str]                      # 用户命名，如 "OpenAI Personal"
    catalog_provider_id: Mapped[str]       # 内置 provider ID 或 "custom"
    provider_type: Mapped[str]             # "anthropic" | "openai"
    api_key_enc: Mapped[str]               # Fernet 加密存储
    base_url_override: Mapped[str | None]  # 用户覆盖 base URL
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

语义：

- 内置 account 使用 `catalog_provider_id` 指向 catalog provider。
- 内置 account 默认使用 catalog 的 `base_url`，只有用户显式覆盖时写 `base_url_override`。
- 自定义 account 使用 `catalog_provider_id="custom"`，必须保存 `provider_type` 和 `base_url_override`。
- Account 不保存默认模型，也不保存 `is_default`。
- GET API 不返回 API key 明文，只返回 `has_api_key` 或固定占位。

### 2.2 LLMCustomModelRecord

自定义 provider 的模型元数据来自 DB。

```python
class LLMCustomModelRecord(Base):
    __tablename__ = "llm_custom_models"
    __table_args__ = (
        UniqueConstraint("account_id", "model_id", name="uq_llm_custom_models_account_model"),
    )

    id: Mapped[str]                        # uuid
    account_id: Mapped[str]                # FK → llm_accounts.id, ON DELETE CASCADE
    model_id: Mapped[str]                  # provider 内稳定模型 ID
    display_name: Mapped[str]
    context_window_tokens: Mapped[int]
    thinking_capability: Mapped[str | None]
    thinking_format: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

语义：

- 同一 account 下 `model_id` 唯一。
- 自定义 account 必须至少有一个 custom model 才能被 binding 使用。

### 2.3 AgentLLMBindingRecord

统一表达默认配置和 agent 覆盖配置。

```python
class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str]                # PK: "__default__" / "sebastian" / "forge" / ...
    account_id: Mapped[str]                # 指向 llm_accounts.id
    model_id: Mapped[str]                  # 模型 ID
    thinking_effort: Mapped[str | None]    # "off" / "on" / "low" / "medium" / "high" / "max" / null
    updated_at: Mapped[datetime]
```

语义：

- `agent_type="__default__"` 是全局默认模型配置。
- 普通 agent 没有 binding 时 fallback 到 `__default__`。
- `account_id + model_id` 必须能解析成一个有效 account 和一个有效 model spec。
- 切换 account 或 model 时，后端按目标 model 的 `thinking_capability` 钳制或清空 `thinking_effort`。
- binding 指向不存在的 account/model 时返回明确配置错误，不静默 fallback。

> **旧版迁移说明**：旧 `LLMProviderRecord`（`llm_providers` 表，含 `is_default`、`model`、`thinking_capability` 等混合字段）已完全移除。当前没有生产数据，首版按首次部署重写 schema，不实现旧表迁移逻辑。开发环境旧 DB 可通过清空 dev data 或手动 reset 重建。

### 2.4 API Key 加密方案

文件：`sebastian/llm/crypto.py`

使用 Fernet（AES-128-CBC + HMAC）加密。密钥从 JWT secret 派生（`SHA-256(jwt_secret)` → 32 字节 → Base64 编码），无需额外环境变量。

```python
def encrypt(plain: str) -> str: ...
def decrypt(enc: str) -> str: ...
```

GET 接口不返回 `api_key_enc` 明文，固定返回 `"***"`。

---

## 3. Catalog JSON

内置 catalog 放在 `sebastian/llm/catalog/builtin_providers.json`。

首版结构：

```json
{
  "version": 1,
  "providers": [
    {
      "id": "openai",
      "display_name": "OpenAI",
      "provider_type": "openai",
      "base_url": "https://api.openai.com/v1",
      "models": [
        {
          "id": "gpt-5.5",
          "display_name": "GPT-5.5",
          "context_window_tokens": 1047576,
          "thinking_capability": "effort",
          "thinking_format": null
        }
      ]
    }
  ]
}
```

字段语义：

| 字段 | 语义 |
|------|------|
| `provider.id` | 稳定 provider catalog ID，如 `openai`、`anthropic`、`deepseek`、`zhipu` |
| `provider.provider_type` | 运行时 adapter 类型：`anthropic` 或 `openai` |
| `provider.base_url` | 内置 provider 默认 base URL |
| `model.id` | provider 内稳定模型 ID，直接传给 LLM API |
| `model.context_window_tokens` | 模型上下文窗口大小，正整数 |
| `model.thinking_capability` | 请求侧 thinking 能力：`none` / `toggle` / `effort` / `adaptive` / `always_on` |
| `model.thinking_format` | 返回侧 thinking 解析方式：`null` / `reasoning_content` / `think_tags` |

Catalog loader 校验规则：

- provider ID 全局唯一。
- 同一 provider 下 model ID 唯一。
- `provider_type` 在支持列表中。
- `context_window_tokens` 是合理正整数（范围 `1_000..10_000_000`）。
- thinking 字段值合法。

首批 catalog 包含 OpenAI、Anthropic、DeepSeek、智谱。

---

## 4. LLMProvider 抽象接口

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

## 5. Anthropic 适配

文件：`sebastian/llm/anthropic.py`

封装 `anthropic.AsyncAnthropic`，将 `content_block_start/delta/stop` 原始事件映射为 `LLMStreamEvent`。

关键点：
- `ThinkingBlockStop` 和 `TextBlockStop` 携带完整内容字段（`thinking` / `text`），使 AgentLoop 能从事件本身重建 `assistant_content`
- `ThinkingBlockStop` 携带 `signature` 字段（从 `block.signature` 取），用于多轮回填
- Thinking 参数按 `thinking_capability` 翻译（见 §8）
- Token usage 从 `final.usage` 构造 `TokenUsage`，包含 `cache_creation_input_tokens` / `cache_read_input_tokens`

---

## 6. OpenAI 兼容适配

文件：`sebastian/llm/openai_compat.py`

通过 `openai.AsyncOpenAI(base_url=..., api_key=...)` 调用，兼容任何实现 `/v1/chat/completions` 的端点。

### 6.1 thinking_format 字段

控制如何从返回中提取 thinking 内容。与 `thinking_capability`（控制请求侧）正交：

| 值 | 适用场景 | 处理方式 |
|----|---------|---------|
| `None`（默认） | 标准 GPT 系列 | 不提取 thinking |
| `"reasoning_content"` | DeepSeek API | 检测 `delta.reasoning_content` |
| `"think_tags"` | llama.cpp 本地部署 | 缓冲 `...` 标签 |

### 6.2 Token Usage 采集

- 请求 kwargs 中加 `stream_options: {include_usage: True}`，从末尾 chunk 的 `usage` 字段采集。
- `reasoning_tokens` 从 `completion_tokens_details.reasoning_tokens` 取得。

---

## 7. 运行时解析

### 7.1 LLMModelSpec

统一的 model spec 数据类：

```python
@dataclass(frozen=True, slots=True)
class LLMModelSpec:
    id: str
    display_name: str
    context_window_tokens: int
    thinking_capability: str | None
    thinking_format: str | None
```

### 7.2 ResolvedProvider

`get_provider()` 返回 `ResolvedProvider` 数据类：

```python
@dataclass(slots=True)
class ResolvedProvider:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    thinking_effort: str | None      # 已按 capability 钳制过
    capability: str | None           # model 的 thinking_capability
    thinking_format: str | None      # model 的 thinking_format
    account_id: str
    model_display_name: str
```

### 7.3 get_provider 查询优先级

```python
async def get_provider(self, agent_type: str | None = None) -> ResolvedProvider:
    """
    解析链路：
    1. agent_type 对应的 binding 存在 → 用其 account_id + model_id
    2. 否则 fallback 到 __default__ binding
    3. 两者都不存在 → 抛 RuntimeError("No default LLM configured")
    4. 读取 account → 按 catalog_provider_id 判断内置/自定义
    5. 内置 → 从 catalog 按 catalog_provider_id + model_id 读取 model spec
    6. 自定义 → 从 llm_custom_models 按 account_id + model_id 读取 model spec
    7. 按 account 的 provider_type + base URL 实例化 provider
    8. 按 model spec 的 capability 钳制 thinking_effort
    9. 返回 ResolvedProvider
    """
```

Base URL 合成：

```text
effective_base_url =
    account.base_url_override
    or catalog_provider.base_url
```

自定义 account 没有 catalog base URL，所以 `base_url_override` 必填。

### 7.4 thinking 参数钳制

`_coerce_thinking(effort, capability)` 在返回前按 model 的 `thinking_capability` 钳制 effort：
- `NONE` / `ALWAYS_ON` → 强制 `null`
- `TOGGLE` → 仅允许 `off` / `on`
- `EFFORT` → 允许 `off` / `low` / `medium` / `high`
- `ADAPTIVE` → 允许 `off` / `low` / `medium` / `high` / `max`

---

## 8. Thinking Effort 控制

### 8.1 thinking_capability 能力模型

模型级的 thinking 能力枚举（来自 catalog 或 custom model 的 `thinking_capability` 字段）：

| 值 | 含义 | UI 档位 | Provider 请求行为 |
|---|---|---|---|
| `none` | 不支持思考控制 | 隐藏按钮 | 不传 thinking 参数 |
| `toggle` | 只支持开关二态 | off / on（单点切换） | on → `{"type":"enabled"}`；off → 不传 |
| `effort` | 支持 4 档 effort | off / low / medium / high | 见翻译表 |
| `adaptive` | Anthropic 原生 Adaptive | off / low / medium / high / max | 见翻译表 |
| `always_on` | 模型必然思考 | 不可点徽标"思考·自动" | 不传参数 |

### 8.2 典型模型配置矩阵

| 模型 | provider_type | thinking_capability | thinking_format |
|------|--------------|-------------------|----------------|
| Claude Opus 4.7 / Sonnet 4.7 | anthropic | adaptive | None |
| Claude 3.7 Sonnet（旧版） | anthropic | effort | None |
| OpenAI o3 / o4 系列 | openai | effort | None |
| GPT-5.5 / GPT-5.4 | openai | effort | None |
| GPT-4o | openai | none | None |
| DeepSeek V4 Pro / Flash | openai | toggle | reasoning_content |
| DeepSeek-R1 | openai | always_on | reasoning_content |
| GLM-5.1 / GLM-5v-Turbo | anthropic | toggle | None |
| llama.cpp Qwen `` | openai | always_on | think_tags |
| 第三方 Anthropic-format 代理 | anthropic | toggle | None |

### 8.3 Provider 内部 effort 翻译表

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

### 8.4 全链路透传

Thinking effort 从 agent_llm_bindings 表的 `thinking_effort` 字段读取（而非前端请求参数）：

```text
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

### 8.5 多轮 thinking signature 修复

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

## 9. AgentLoop / BaseAgent 集成

### 9.1 AgentLoop 改造

构造器接收 `LLMProvider`，不直接 import SDK：

```python
class AgentLoop:
    def __init__(self, provider: LLMProvider, ...): ...
```

### 9.2 BaseAgent 集成

`BaseAgent` 从 `LLMProviderRegistry` 获取 resolved provider 并注入 AgentLoop：

```python
resolved = await self._llm_registry.get_provider(self.name)
# per-turn live 生效
```

生效时机：per-turn live。用户改绑定 → 正在进行的 turn 保持旧 provider → 下一个 turn 使用新 provider。

---

## 10. 前端 Thinking 控制 UI

### 10.1 架构迁移

Thinking 配置从"对话页 Composer 每次选"迁移为"Agent Binding 编辑页持久化一次配好"。

**已删除组件**：
- `ui/composer/ThinkButton.kt` — 整个文件删除
- `ui/composer/EffortPickerCard.kt` — 整个文件删除
- `ChatViewModel.activeThinkingEffort` / `setEffort()` — 删除
- `SendTurnRequest.thinkingEffort` — 删除

### 10.2 AgentBindingsPage（列表页）

Settings → 默认模型 / Agent 模型绑定列表，分三个区：

- **默认模型**（置顶，对应 `agent_type="__default__"`）
- **Memory Components**（记忆相关组件）
- **Sub-Agents**（按后端返回顺序）

每个 item 显示 agent 名称 + account/model/effort 摘要，点击进入 Editor 次级页。

### 10.3 AgentBindingEditorPage（编辑页）

- **Account 选择**：选择后刷新模型列表（内置 account 来自 catalog，custom 来自 `llm_custom_models`）
- **Model 选择**：按 account 类型展示可用模型，展示 `context_window_tokens`
- **Thinking Effort 滑块**：按 model 的 `effectiveCapability` 渲染

切换 account 时清空不再合法的 model。切换 model 时按目标 model 的 `thinking_capability` 重置或钳制 effort。

### 10.4 EffortSlider

按 capability 渲染不同形态：

| capability | 形态 |
|---|---|
| `NONE` | 思考区不渲染 |
| `TOGGLE` | `SebastianSwitch`（Off/On） |
| `EFFORT` | 4 档 Slider（Off/Low/Medium/High） |
| `ADAPTIVE` | 5 档 Slider（Off/Low/Medium/High/Max） |
| `ALWAYS_ON` | 只读 label `Thinking: Always on` |

### 10.5 即时保存与防抖

`AgentBindingEditorViewModel`：
- 每个 setter debounce 300ms 合并为一次 PUT
- PUT 失败 → snackbar + state 回滚
- 切换 account/model 时本地立即重置 effort
- 越界钳制：初始化时 effort 不在 capability 支持刻度中，钳到最高合法刻度并触发 PUT 纠正

---

## 11. Gateway 路由

### Catalog

```http
GET /api/v1/llm-catalog
```

### Account CRUD

```http
GET    /api/v1/llm-accounts
POST   /api/v1/llm-accounts
PUT    /api/v1/llm-accounts/{account_id}
DELETE /api/v1/llm-accounts/{account_id}
```

内置 account 创建：`{ "name", "catalog_provider_id": "openai", "api_key": "sk-..." }`
自定义 account 创建：`{ "name", "catalog_provider_id": "custom", "provider_type": "openai", "base_url_override": "...", "api_key": "..." }`

API key 语义：
- 创建时 `api_key` 必填且必须非空。
- 更新时省略 `api_key` 保留原 key；非空替换；`null` 或空字符串返回 `400`。

删除 account 时，如果任何 binding 正在引用它，返回 `409`。

### Custom Model CRUD

```http
GET    /api/v1/llm-accounts/{account_id}/models
POST   /api/v1/llm-accounts/{account_id}/models
PUT    /api/v1/llm-accounts/{account_id}/models/{model_record_id}
DELETE /api/v1/llm-accounts/{account_id}/models/{model_record_id}
```

只适用于 custom account。内置 account 的模型列表来自 catalog。

### Binding 管理

三类 binding API：

| 类型 | 路由 | 说明 |
|------|------|------|
| 全局默认 | `GET/PUT /api/v1/llm-bindings/default` | 内部写 `agent_type="__default__"`，不能 DELETE |
| Agent | `GET/PUT/DELETE /api/v1/agents/{agent_type}/llm-binding` | DELETE 清除覆盖配置，fallback 到 `__default__` |
| Memory component | `GET/PUT/DELETE /api/v1/memory/components/{type}/llm-binding` | 同上 |

请求/响应示例：

```json
{
  "agent_type": "forge",
  "account_id": "...",
  "model_id": "deepseek-coder",
  "thinking_effort": "high",
  "resolved": {
    "account_name": "DeepSeek",
    "provider_display_name": "DeepSeek",
    "model_display_name": "DeepSeek Coder",
    "context_window_tokens": 128000,
    "thinking_capability": "always_on"
  }
}
```

### Agent 列表（扩展字段）

```http
GET /api/v1/agents
```

响应每条 agent 包含 `is_orchestrator: bool` 和 `binding: { agent_type, account_id, model_id, thinking_effort } | null`。

---

## 12. 上下文压缩接入

压缩调度器通过 `context_window_resolver(agent_type)` 动态解析每个 agent 的 context window（见 [context-compaction.md](context-compaction.md)），不再使用全局硬编码 200k。

`context_compactor` 自身是一个可绑定的 agent type：summary 生成使用 `get_provider("context_compactor")`，无专属绑定时 fallback 到 `__default__`。

---

## 13. 错误处理

- 没有 `__default__` binding：对话请求返回明确错误，Android 引导先配置默认模型。
- binding 指向不存在的 account/model：返回配置损坏错误，不自动使用其他模型。
- 内置 catalog 删除了被 binding 引用的 model：提示重新选择模型。
- custom account 没有 custom model：绑定页禁用选择并提示先添加模型。
- `context_window_tokens` 非法：后端拒绝保存。
- 删除 custom model 时，如果任何 binding 正在引用它，返回 `409`。
- 更新 custom model 时，被引用的 `model_id` 不允许变更并返回 `409`；其余字段可更新。

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
