# llm — LLM Provider 抽象层

> 上级索引：[sebastian/](../README.md)

## 模块职责

将不同 LLM 服务商的 SDK 差异封装在 Provider 内部，向上暴露统一的流式事件接口（`LLMStreamEvent`）。多轮工具调用循环由 `AgentLoop` 驱动，Provider 只负责单次 API 调用。注册表支持运行时从 DB 切换 Provider；无 DB 配置时抛出 `RuntimeError`（不再回退到环境变量），调用方应向用户提示通过 Settings 页面配置 Provider。

## 目录结构

```
llm/
├── __init__.py          # 模块入口（空导出，按需 import 子模块）
├── provider.py          # LLMProvider 抽象基类；定义 stream() 接口和 message_format 属性
├── anthropic.py         # Anthropic SDK 适配，处理 thinking block、tool_use streaming
├── openai_compat.py     # OpenAI /v1/chat/completions 适配，兼容 DeepSeek-R1 等第三方模型
└── registry.py          # DB 驱动的 Provider 注册表，支持运行时切换；无配置时抛出 RuntimeError
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
| Claude Opus 4.6 / Sonnet 4.6 | anthropic | adaptive | None |
| Claude 3.7 Sonnet | anthropic | effort | None |
| 第三方 Anthropic-format 代理 | anthropic | toggle | None |
| OpenAI o3 / o4 | openai | effort | None |
| GPT-4o | openai | none | None |
| DeepSeek-R1 | openai | always_on | reasoning_content |
| llama.cpp Qwen `<think>` | openai | always_on | think_tags |

**注意**：`OpenAICompatProvider` 收到 `capability=toggle` 时默认 no-op。OpenAI 兼容接口没有统一的"布尔 thinking"字段标准，若将来需要支持具体某个后端，再在 `openai_compat.py` 加分支。

Anthropic 旧版 effort 模式的 budget_tokens 映射写在 `AnthropicProvider.FIXED_EFFORT_TO_BUDGET` 常量表里（low=2048 / medium=8192 / high=24576）。**快速失败原则**：
- `thinking_effort` 不在 low/medium/high 中 → 抛 `ValueError`（不静默兜底）
- `budget_tokens >= max_tokens` → 抛 `ValueError`，要求调用方显式抬高 `max_tokens` 或降档

UI 层需在 clamp 规则中保证传入 Provider 的 effort 始终合法（见 `ui/mobile/src/store/composer.ts` 的 `clampAllToCapability`）。

## 修改导航

| 如果要修改… | 看这里 |
|------------|--------|
| 新增 Provider（如 Google Gemini） | 继承 [provider.py](provider.py) 的 `LLMProvider`，声明 `message_format`，在 [registry.py](registry.py) 的 `_instantiate()` 注册 `provider_type` |
| Anthropic streaming 行为 / thinking block | [anthropic.py](anthropic.py) |
| OpenAI 兼容模型适配 / thinking_format | [openai_compat.py](openai_compat.py) |
| 调整 thinking_capability 翻译规则 / budget 默认值 | [anthropic.py](anthropic.py) 的 `_build_thinking_kwargs` 与 `FIXED_EFFORT_TO_BUDGET` / [openai_compat.py](openai_compat.py) |
| 切换默认模型 | [registry.py](registry.py)，更新 DB 中 `is_default=True` 的 `LLMProviderRecord`，或修改 `settings.sebastian_model` |
| Provider 抽象接口定义 | [provider.py](provider.py) 的 `stream()` 签名和 `message_format` |
| 调试 Provider 流式输出 | 在 [provider.py](provider.py) 的 `stream()` 加日志，事件由 `AgentLoop` 消费 |

## 公开接口

```python
from sebastian.llm.provider import LLMProvider
from sebastian.llm.registry import LLMProviderRegistry

# 获取当前默认 Provider（DB 必须已配置，否则抛出 RuntimeError）
provider, model = await registry.get_default_with_model()

# 直接实例化（测试或脚本用）
from sebastian.llm.anthropic import AnthropicProvider
from sebastian.llm.openai_compat import OpenAICompatProvider

provider = AnthropicProvider(api_key="sk-ant-...")
provider = OpenAICompatProvider(api_key="...", base_url="...", thinking_format="reasoning_content")
```

---

> 修改本目录或模块后，请同步更新此 README。
