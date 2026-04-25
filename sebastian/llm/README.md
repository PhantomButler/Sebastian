# llm — LLM Provider 抽象层

> 上级索引：[sebastian/](../README.md)

## 模块职责

将不同 LLM 服务商的 SDK 差异封装在 Provider 内部，向上暴露统一的流式事件接口（`LLMStreamEvent`）。多轮工具调用循环由 `AgentLoop` 驱动，Provider 只负责单次 API 调用。

LLM 配置采用三层架构：Catalog（内置 Provider/Model 元数据）→ Account（用户 API Key 绑定）→ Binding（per-agent 模型绑定）。`LLMProviderRegistry` 负责从 DB 解析 Account 和 Binding，按 `agent_type → binding → account → model_spec → instantiate` 链条生成 `ResolvedProvider`。无 DB 配置时抛出 `RuntimeError`（不再回退到环境变量），调用方应向用户提示通过 Settings 页面配置 Provider。

## 目录结构

```
llm/
├── __init__.py          # 模块入口（空导出，按需 import 子模块）
├── provider.py          # LLMProvider 抽象基类；定义 stream() 接口和 message_format 属性
├── anthropic.py         # Anthropic SDK 适配，处理 thinking block、tool_use streaming
├── catalog/             # 内置 Provider/Model 元数据目录
│   ├── __init__.py      # catalog 模块入口
│   ├── loader.py        # CatalogLoader：加载内置 + 自定义 provider/model 元数据
│   └── builtin_providers.json  # 内置 Provider/Model catalog（4 providers, 10 models）
├── crypto.py            # Fernet 加密/解密封装，基于 secret.key，用于 API Key 落库前的保护
├── openai_compat.py     # OpenAI /v1/chat/completions 适配，兼容 DeepSeek-R1 等第三方模型
├── registry.py          # 重写：三层 Catalog → Account → Binding 解析
└── README.md
```

## message_format 说明

`LLMProvider.message_format` 决定 `AgentLoop` 如何构建对话历史：

| 值 | 适用 Provider | assistant 消息格式 | tool result 格式 |
|---|---|---|---|
| `"anthropic"` | `AnthropicProvider` | `content: [block...]` | `role:user` 内嵌 `tool_result` block |
| `"openai"` | `OpenAICompatProvider` | `content: null, tool_calls: [...]` | `role:tool` 独立消息 |

新增 Provider 时，**必须**声明 `message_format` 类变量。

## OpenAI 兼容的 thinking_format

`OpenAICompatProvider` 通过 `thinking_format` 参数支持不同推理模型：

| 值 | 适用场景 |
|---|---|
| `None`（默认） | 标准 GPT 模型，无 thinking |
| `"reasoning_content"` | DeepSeek-R1：`delta.reasoning_content` 字段 |
| `"think_tags"` | llama.cpp 等：响应文本内嵌 `<think>...</think>` |

## thinking_capability

与 `thinking_format`（解析返回）正交，`thinking_capability` 描述 Provider 如何**发起**思考请求，值为：

| 值 | 含义 | 可选 effort | 请求行为 |
|---|---|---|---|
| `none` | 不支持思考控制 | — | 不传任何 thinking 参数 |
| `toggle` | 只支持开关二态 | off / on | `thinking={"type":"enabled"}`（Anthropic 路径）；OpenAI 路径 no-op |
| `effort` | 4 档 | off / low / medium / high | Anthropic 旧版 `thinking={"type":"enabled","budget_tokens":N}`；OpenAI `reasoning_effort=...` |
| `adaptive` | Anthropic Adaptive Thinking | off / low / medium / high / max | `thinking={"type":"adaptive"}` + `output_config={"effort":...}` |
| `always_on` | 模型必然思考 | —（UI 固定）| 不传参数，解析侧由 `thinking_format` 决定 |

典型组合：

| 模型 | provider_type | thinking_capability | thinking_format |
|---|---|---|---|
| Claude Opus 4.7 / Sonnet 4.7 | anthropic | adaptive | None |
| Claude 3.7 Sonnet | anthropic | effort | None |
| 第三方 Anthropic-format 代理 | anthropic | toggle | None |
| OpenAI o3 / o4 | openai | effort | None |
| GPT-5.5 / GPT-5.4 | openai | effort | None |
| GPT-4o | openai | none | None |
| DeepSeek V4 Pro / Flash | openai | toggle | reasoning_content |
| DeepSeek-R1 | openai | always_on | reasoning_content |
| GLM-5.1 / GLM-5v-Turbo | anthropic | toggle | None |
| llama.cpp Qwen `<think>` | openai | always_on | think_tags |

**注意**：`OpenAICompatProvider` 收到 `capability=toggle` 时默认 no-op。OpenAI 兼容接口没有统一的"布尔 thinking"字段标准，若将来需要支持具体某个后端，再在 `openai_compat.py` 加分支。

Anthropic 旧版 effort 模式的 budget_tokens 映射写在 `AnthropicProvider.FIXED_EFFORT_TO_BUDGET` 常量表里（low=2048 / medium=8192 / high=24576）。**快速失败原则**：
- `thinking_effort` 不在 low/medium/high 中 → 抛 `ValueError`（不静默兜底）
- `budget_tokens >= max_tokens` → 抛 `ValueError`，要求调用方显式抬高 `max_tokens` 或降档

为保证 `effort=high` 始终可用，`llm_max_tokens` 默认值已设为 **32000**（> 24576）。通过 `SEBASTIAN_LLM_MAX_TOKENS` 下调到 < 24577 时，选择 `high` 档位将稳定触发上述 ValueError。

UI 层需在 clamp 规则中保证传入 Provider 的 effort 始终合法（见 `ui/mobile/src/store/composer.ts` 的 `clampAllToCapability`）。

## Token Usage 采集

- Provider 在 `ProviderCallEnd` 事件中附带 `usage: TokenUsage | None`，由 `sebastian.context.usage.TokenUsage` 定义。
- `AnthropicProvider` 从 `final.usage` 构造 `TokenUsage`，包含 `cache_creation_input_tokens` / `cache_read_input_tokens`。
- `OpenAICompatProvider` 在请求 kwargs 中加 `stream_options: {include_usage: True}`，从末尾 chunk 的 `usage` 字段采集；`reasoning_tokens` 从 `completion_tokens_details.reasoning_tokens` 取得。
- 若 Provider 未返回 usage（如本地模型或旧版 API），`TokenUsage` 为 `None`；后续 Token 估算由 `TokenEstimator`（尚未实现）兜底。

## 三层架构说明

### Catalog 层

`catalog/builtin_providers.json` 定义内置 Provider 元数据和模型规格，包括：

- `provider_id`：内置 Provider 唯一标识（如 `anthropic`、`openai`、`deepseek`、`zhipu`）
- `models`：该 Provider 支持的模型列表，每个模型包含 `model_id`、`display_name`、`context_window_tokens`、`thinking_capability`、`thinking_format`、`message_format` 等字段

`CatalogLoader` 在启动时加载内置 catalog，并支持合并用户自定义模型（通过 `LLMCustomModelRecord`）。

### Account 层

用户通过 Settings 页面创建 Account，绑定到某个 catalog provider（或自定义 provider）：

- `LLMAccountRecord`：存储 `name`、`catalog_provider_id`、加密后的 `api_key`、`base_url`（可选）
- Account 可以拥有多个自定义模型（`LLMCustomModelRecord`），扩展 catalog 模型列表

### Binding 层

每个 `agent_type` 可以绑定到特定的 `account_id + model_id` 组合：

- `AgentLLMBindingRecord`：存储 `agent_type`、`account_id`、`model_id`、`thinking_effort`
- `__default__` 作为 fallback，当 agent_type 没有专属绑定时使用
- `memory_*` 组件也可以通过相同机制绑定（`memory_components.py`）

解析链条：`agent_type → binding → account → model_spec（catalog 或 custom）→ instantiate Provider`

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 Provider SDK 适配（如 Google Gemini） | 继承 [provider.py](provider.py) 的 `LLMProvider`，声明 `message_format`，在 [registry.py](registry.py) 的 `_instantiate()` 注册 `provider_type` |
| 查看/修改内置 Provider 和 Model 元数据 | [catalog/loader.py](catalog/loader.py) + [catalog/builtin_providers.json](catalog/builtin_providers.json) |
| 管理 LLM Account（API Key 绑定） | [registry.py](registry.py) 的 account CRUD（`create_account`、`list_accounts` 等） |
| 管理 per-Agent 模型绑定 | [registry.py](registry.py) 的 binding CRUD（`set_binding`、`get_binding` 等） |
| API Key 加密/解密（落库前保护） | [crypto.py](crypto.py) 的 `encrypt()` / `decrypt()` |
| Anthropic streaming 行为 / thinking block | [anthropic.py](anthropic.py) |
| OpenAI 兼容模型适配 / thinking_format | [openai_compat.py](openai_compat.py) |
| 调整 thinking_capability 翻译规则 / budget 默认值 | [anthropic.py](anthropic.py) 的 `_build_thinking_kwargs` 与 `FIXED_EFFORT_TO_BUDGET` / [openai_compat.py](openai_compat.py) |
| 切换默认模型 | [registry.py](registry.py)，更新 `__default__` binding 的 `account_id + model_id` |
| Provider 抽象接口定义 | [provider.py](provider.py) 的 `stream()` 签名和 `message_format` |
| 调试 Provider 流式输出 | 在 [provider.py](provider.py) 的 `stream()` 加日志，事件由 `AgentLoop` 消费 |

## 公开接口

```python
from sebastian.llm.registry import LLMProviderRegistry

# 获取 Agent 的 Resolved Provider（含 context_window_tokens 等）
resolved = await registry.get_provider(agent_type)

# Account CRUD
await registry.create_account(name="...", catalog_provider_id="anthropic", api_key="...")
accounts = await registry.list_accounts()

# Binding
await registry.set_binding(agent_type="forge", account_id=..., model_id="...")

# 直接实例化（测试或脚本用）
from sebastian.llm.anthropic import AnthropicProvider
from sebastian.llm.openai_compat import OpenAICompatProvider

provider = AnthropicProvider(api_key="sk-ant-...")
provider = OpenAICompatProvider(api_key="...", base_url="...", thinking_format="reasoning_content")
```

---

> 修改本目录或模块后，请同步更新此 README。
