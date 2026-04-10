---
version: "1.0"
last_updated: 2026-04-10
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

### 2.3 per-agent 模型选择

在 `manifest.toml` 中声明（可选，不填则使用全局默认）：

```toml
[llm]
provider_type = "anthropic"
model = "claude-haiku-4-5"
```

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

```
SendTurnRequest.thinking_effort
  ↓
Sebastian.run_streaming(..., thinking_effort=...)
  ↓
BaseAgent._stream_inner(..., thinking_effort=...)
  ↓
AgentLoop.stream(..., thinking_effort=...)
  ↓
LLMProvider.stream(..., thinking_effort=...)
```

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

```python
class LLMProviderRegistry:
    async def get_provider(
        self,
        provider_type: str | None = None,
        model: str | None = None,
    ) -> LLMProvider:
        """
        优先级：
        1. provider_type + model 精确匹配
        2. provider_type 匹配，取 is_default=True
        3. 全局 is_default=True
        4. 抛出 ConfigError
        """
```

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

### 9.1 ThinkButton 形态

按 capability 决定渲染形态：

| capability | 形态 |
|---|---|
| `null`（未配置） | 灰色 disabled |
| `none` | 不渲染 |
| `toggle` | 单点切换 pill（off ↔ on） |
| `effort` | 可点 pill → ActionSheet（off / low / medium / high） |
| `adaptive` | 可点 pill → ActionSheet（off / low / medium / high / max） |
| `always_on` | 不可点徽标"思考·自动" |

### 9.2 Composer Store 改造

```ts
type ThinkingEffort = 'off' | 'on' | 'low' | 'medium' | 'high' | 'max';

interface ComposerStore {
    effortBySession: Record<string, ThinkingEffort>;
    lastUserChoice: ThinkingEffort;  // 新 session 默认，持久化到 AsyncStorage
}
```

### 9.3 Provider 切换时的 clamp 规则

当 `currentThinkingCapability` 变化时，`effortBySession` 中非法档位自动 clamp：

- 降级到不存在的档位 → 取"语义最接近"的一档（max → high 等）
- 升级到无等级模型（→ toggle）→ 任何"开"状态映射为 `on`

Clamp 时触发 toast 提示。

### 9.4 切换时机

- effort 在 `POST /api/v1/turns` 那一刻锁定
- Picker 不在 in-flight 期间禁用（控制的是"下一条消息"）
- Provider 切换不影响 in-flight turn

---

## 10. Gateway 路由

```
GET    /api/v1/llm/providers              # 列表（api_key 返回 "***"）
POST   /api/v1/llm/providers              # 新增
PUT    /api/v1/llm/providers/{id}         # 修改
DELETE /api/v1/llm/providers/{id}         # 删除
POST   /api/v1/llm/providers/{id}/set-default  # 设为全局默认
```

POST/PUT 请求体包含 `thinking_capability` 字段（可选），Settings 页新增对应下拉选择器。

---

*← [Core 索引](INDEX.md) · [Spec 根索引](../INDEX.md)*
