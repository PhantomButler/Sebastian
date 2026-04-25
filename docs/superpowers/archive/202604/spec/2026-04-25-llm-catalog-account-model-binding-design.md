---
version: "1.0"
last_updated: 2026-04-25
status: planned
integrated_to: core/llm-provider.md
integrated_at: 2026-04-25
---

# LLM Catalog、Account 与模型绑定设计

## 背景

上下文自动压缩已经接入 token 阈值判断，但当前运行时仍使用固定的 `ContextTokenMeter(context_window=200_000)`。这会让不同模型共享同一个上下文窗口假设，无法准确决定何时压缩。

同时，现有 `llm_providers` 表把服务商连接、API Key、base URL、模型、thinking 元数据和默认配置混在一行。结果是：用户每添加或切换一个模型，都需要重新创建一条 Provider 配置并重复输入连接信息。这不是 UI 小问题，而是数据边界不清。

本设计把 LLM 配置拆成三层：

- 内置 catalog：随版本发布的 provider 与 model 元数据。
- Account：用户在 Sebastian 中保存的连接和凭据。
- Binding：默认配置或某个 Agent 选择的 account + model + thinking effort。

## 目标

- 为每个模型保存准确的 `context_window_tokens`，供上下文压缩和未来 token 预算逻辑使用。
- 内置常见 provider 和模型，减少用户输入 base URL、provider type、thinking 元数据等重复信息。
- 保留自定义 OpenAI-compatible / Anthropic-compatible provider 能力。
- 支持不同 Agent 使用不同 provider account 和不同模型。
- 用 `__default__` binding 表达全局默认模型，避免 account 自身携带默认模型。
- 首版仅使用本地 JSON catalog，不实现远程热更新。
- 当前没有生产数据，按首次部署重写 schema，不实现旧 `llm_providers` 迁移逻辑。

## 非目标

- 不从 `/v1/models` 自动发现模型。
- 不实现远程 catalog 拉取、签名校验或缓存失效。
- 不为 account 设置默认模型。
- 不兼容旧 `/llm-providers` API 语义。
- 不实现旧开发数据库的自动迁移；开发者可清空 dev data 后重建。

## 架构概览

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
- Binding 是唯一表达“谁使用哪个 account 和哪个 model”的地方。
- `agent_type="__default__"` 是全局默认 binding。普通 agent 无绑定时 fallback 到它。

## Catalog JSON

内置 catalog 放在：

```text
sebastian/llm/catalog/builtin_providers.json
```

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
          "id": "gpt-4.1",
          "display_name": "GPT-4.1",
          "context_window_tokens": 1047576,
          "thinking_capability": "none",
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
| `provider.provider_type` | 运行时 adapter 类型，首版仍为 `anthropic` 或 `openai` |
| `provider.base_url` | 内置 provider 默认 base URL |
| `model.id` | provider 内稳定模型 ID，直接传给 LLM API |
| `model.context_window_tokens` | 模型上下文窗口大小，正整数 |
| `model.thinking_capability` | 请求侧 thinking 能力：`none` / `toggle` / `effort` / `adaptive` / `always_on` |
| `model.thinking_format` | 返回侧 thinking 解析方式：`null` / `reasoning_content` / `think_tags` |

Catalog loader 必须校验：

- provider ID 全局唯一。
- 同一 provider 下 model ID 唯一。
- `provider_type` 在支持列表中。
- `context_window_tokens` 是合理正整数，建议范围 `1_000..10_000_000`。
- thinking 字段值合法。

首批 catalog 可包含常见 provider：OpenAI、Anthropic、DeepSeek、智谱。具体模型列表按实现时的本地 JSON 固化；后续新增模型只需要更新 JSON。

## 数据模型

### `LLMAccountRecord`

替代旧 `LLMProviderRecord` 的连接与凭据部分。

```python
class LLMAccountRecord(Base):
    __tablename__ = "llm_accounts"

    id: Mapped[str]
    name: Mapped[str]
    catalog_provider_id: Mapped[str]          # 内置 provider ID 或 "custom"
    provider_type: Mapped[str]                # "anthropic" | "openai"
    api_key_enc: Mapped[str]
    base_url_override: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

语义：

- 内置 account 使用 `catalog_provider_id` 指向 catalog provider。
- 内置 account 默认使用 catalog 的 `base_url`，只有用户显式覆盖时写 `base_url_override`。
- 自定义 account 使用 `catalog_provider_id="custom"`，必须保存 `provider_type` 和 `base_url_override`。
- Account 不保存默认模型，也不保存 `is_default`。
- GET API 不返回 API key 明文，只返回 `has_api_key` 或固定占位。

### `LLMCustomModelRecord`

自定义 provider 的模型元数据来自 DB。

```python
class LLMCustomModelRecord(Base):
    __tablename__ = "llm_custom_models"

    id: Mapped[str]
    account_id: Mapped[str]
    model_id: Mapped[str]
    display_name: Mapped[str]
    context_window_tokens: Mapped[int]
    thinking_capability: Mapped[str | None]
    thinking_format: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

语义：

- `account_id` 指向 custom account。
- 同一 account 下 `model_id` 唯一。
- 自定义 account 必须至少有一个 custom model 才能被 binding 使用。
- 首版自定义模型全部手动填写，不做自动发现。

### `AgentLLMBindingRecord`

统一表达默认配置和 agent 覆盖配置。

```python
class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str]                   # "__default__" / "sebastian" / "forge" / ...
    account_id: Mapped[str]
    model_id: Mapped[str]
    thinking_effort: Mapped[str | None]
    updated_at: Mapped[datetime]
```

语义：

- `agent_type="__default__"` 是全局默认模型配置。
- 普通 agent 没有 binding 时 fallback 到 `__default__`。
- `account_id + model_id` 必须能解析成一个有效 account 和一个有效 model spec。
- 切换 account 或 model 时，后端按目标 model 的 `thinking_capability` 钳制或清空 `thinking_effort`。钳制规则沿用 `docs/architecture/spec/core/llm-provider.md §7.3`。
- binding 指向不存在的 account/model 时返回明确配置错误，不静默 fallback。

## 运行时解析

新增统一的 model spec：

```python
@dataclass(slots=True)
class LLMModelSpec:
    id: str
    display_name: str
    context_window_tokens: int
    thinking_capability: str | None
    thinking_format: str | None
```

扩展 `ResolvedProvider`：

```python
@dataclass(slots=True)
class ResolvedProvider:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    thinking_effort: str | None
    capability: str | None
    thinking_format: str | None
    account_id: str
    model_display_name: str
```

`LLMProviderRegistry.get_provider(agent_type)`：

1. 查询 `agent_type` binding。
2. 如果不存在，查询 `__default__` binding。
3. 如果默认 binding 不存在，抛出 “No default LLM configured”。
4. 读取 account。
5. 如果 account 是内置 provider，从 catalog 中按 `catalog_provider_id + model_id` 读取 model spec。
6. 如果 account 是 custom，从 `llm_custom_models` 中按 `account_id + model_id` 读取 model spec。
7. 按 account 的 `provider_type` 和 base URL 实例化 provider。
8. 按 model spec 的 capability 钳制 `thinking_effort`，规则沿用 `docs/architecture/spec/core/llm-provider.md §7.3`。
9. 返回 `ResolvedProvider`。

Base URL 合成：

```text
effective_base_url =
    account.base_url_override
    or catalog_provider.base_url
```

自定义 account 没有 catalog base URL，所以 `base_url_override` 必填。

## 上下文压缩接入

当前自动压缩调度使用全局 `ContextTokenMeter(context_window=200_000)`。新设计改为 per-turn 解析窗口：

1. turn 完成后，调度器根据 `agent_type` 调用 registry 读取 `ResolvedProvider.context_window_tokens`。
2. 使用该窗口计算 soft/hard/estimate 阈值。
3. provider usage 优先，估算兜底的规则不变。
4. 触发压缩后仍由 `SessionContextCompactionWorker` 后台运行。

`context_compactor` 自身也是一个可绑定的 agent type：

- summary 生成使用 `get_provider("context_compactor")`。
- 没有专门绑定时 fallback 到 `__default__`。
- 生成 summary 使用的模型窗口不替代被压缩 session agent 的窗口；自动触发判断使用当前 turn 所属 agent 的模型窗口。

## API 设计

废弃旧 `/llm-providers` 语义，首版直接改为新 API。

### Catalog

```http
GET /api/v1/llm-catalog
```

返回本地 JSON catalog 的规范化结果。

### Accounts

```http
GET    /api/v1/llm-accounts
POST   /api/v1/llm-accounts
PUT    /api/v1/llm-accounts/{account_id}
DELETE /api/v1/llm-accounts/{account_id}
```

内置 provider account 创建：

```json
{
  "name": "OpenAI Personal",
  "catalog_provider_id": "openai",
  "api_key": "sk-..."
}
```

自定义 account 创建：

```json
{
  "name": "Local vLLM",
  "catalog_provider_id": "custom",
  "provider_type": "openai",
  "base_url_override": "http://10.0.2.2:8000/v1",
  "api_key": "..."
}
```

内置 account 可选 `base_url_override`，但 UI 首版可以不暴露，保留后端能力即可。

Account API 字段命名统一使用 `base_url_override`：

- 内置 account：`base_url_override` 可省略；省略时使用 catalog provider 的 `base_url`。
- custom account：`base_url_override` 必填。
- 响应中可额外返回 `effective_base_url` 供 UI 展示，但写入字段仍只接受 `base_url_override`。

API key 语义：

- 创建 account 时 `api_key` 必填且必须是非空字符串。
- 更新 account 时省略 `api_key` 表示保留原 key。
- 更新 account 时提供非空 `api_key` 表示替换 key。
- `api_key=null` 或空字符串均返回 `400`；首版不支持清空 key，因为无 key 的 account 不能被安全地用于运行时调用。

### Custom Models

```http
GET    /api/v1/llm-accounts/{account_id}/models
POST   /api/v1/llm-accounts/{account_id}/models
PUT    /api/v1/llm-accounts/{account_id}/models/{model_record_id}
DELETE /api/v1/llm-accounts/{account_id}/models/{model_record_id}
```

只适用于 custom account。内置 account 的模型列表来自 catalog，不通过这些接口修改。

### Bindings

Binding API 分三类保留现有信息架构：

- 全局默认：新增 `GET/PUT /api/v1/llm-bindings/default`，内部写 `agent_type="__default__"`。
- Agent：保留 `GET/PUT/DELETE /api/v1/agents/{agent_type}/llm-binding`，请求/响应字段改为 `account_id + model_id + thinking_effort`。
- Memory component：保留 `GET/PUT/DELETE /api/v1/memory/components/{type}/llm-binding`，字段同上。

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

普通 agent 和 memory component 的 DELETE 语义仍是清除覆盖配置，使其 fallback 到 `__default__`。`__default__` 不能 DELETE；只能 PUT 到另一组 `account_id + model_id`。

## Android UX

Settings 首页保留两个入口，但调整文案和职责。

### LLM 连接

原 `模型与 Provider` 改名为 `LLM 连接` 或 `模型服务连接`。

职责：

- 管理 `llm_accounts`。
- 列表展示连接名、服务商名称、自定义标记、API key 是否已配置。
- 不展示“默认”标记，因为默认模型由 `__default__` binding 表达。

新增连接流程：

1. 选择服务商：OpenAI / Anthropic / DeepSeek / 智谱 / Custom。
2. 内置服务商：填写连接名和 API key。
3. Custom：填写连接名、provider type、base URL、API key。
4. Custom 保存后进入自定义模型管理，至少添加一个模型后才能被 binding 选择。

### 默认模型 / Agent 模型绑定

原 `Agent LLM Bindings` 改名为 `默认模型 / Agent 模型绑定`。

职责：

- 顶部固定展示 `默认模型` 行，对应 `agent_type="__default__"`。
- 下面展示 Sebastian、Sub-Agent、Memory component 等现有绑定对象。
- 编辑页选择 account，再选择该 account 可用模型，再选择 thinking effort。

模型选择规则：

- 选中内置 account：模型下拉来自 catalog。
- 选中 custom account：模型下拉来自 `llm_custom_models`。
- 切换 account 时清空不再合法的 model。
- 切换 model 时按目标 model 的 `thinking_capability` 重置或钳制 effort。
- 选中模型后展示 `context_window_tokens`，用于解释压缩阈值来自哪里。

## 错误处理

- 没有 `__default__` binding：对话请求返回明确错误，Android 引导先配置默认模型。
- binding 指向不存在的 account/model：返回配置损坏错误，不自动使用其他模型。
- 内置 catalog 删除了被 binding 引用的 model：提示重新选择模型。
- custom account 没有 custom model：绑定页禁用选择并提示先添加模型。
- `context_window_tokens` 非法：后端拒绝保存。
- API key 创建必填；更新时省略保留、非空替换、`null` 或空字符串返回 `400`。
- 删除 account 时，如果任何 binding 正在引用它，返回 `409`，要求用户先切换或清除相关 binding；未被引用的 account 可删除。
- 删除 custom model 时，如果任何 binding 正在引用它，返回 `409`；未被引用的 custom model 可删除。
- 更新 custom model 时，如果任何 binding 正在引用它，`model_id` 不允许变更并返回 `409`；`display_name`、`context_window_tokens`、`thinking_capability`、`thinking_format` 可更新，运行时继续按最新 metadata 解析并钳制 thinking effort。
- 删除 custom account 时同时删除其未被引用的 custom models。由于 account 被引用时会先返回 `409`，不会产生悬空 binding。
- 内置 catalog model 不能通过 API 删除；如果随版本移除导致 binding 悬空，运行时返回配置错误，Android 提示用户重新选择模型。

## Schema 与迁移策略

当前没有生产数据，首版按首次部署重写：

- 删除旧 `LLMProviderRecord` 语义。
- 新库直接创建 `llm_accounts`、`llm_custom_models`、新版 `agent_llm_bindings`。
- 不实现旧 `llm_providers` 到新表的产品迁移。
- 开发环境旧 DB 可通过清空 dev data 或手动 reset 重建。
- `_apply_idempotent_migrations` 不继续为旧 `llm_providers` 字段新增兼容补丁。

## 测试计划

后端：

- Catalog loader 解析、唯一性校验、字段合法性校验。
- `GET /api/v1/llm-catalog` 返回规范化 provider/model 列表。
- Account API：内置 account 创建、custom account 创建、base URL 校验、API key 加密。
- Account API：被任何 binding 引用时删除返回 `409`；未被引用的 custom account 删除时级联删除其 custom models。
- Custom model API：只允许 custom account、必填上下文窗口、同 account model ID 唯一。
- Custom model API：被任何 binding 引用时删除返回 `409`。
- Custom model API：被任何 binding 引用时变更 `model_id` 返回 `409`。
- Binding API：保存 `account_id + model_id`，默认 binding 使用 `__default__`。
- Registry：agent binding 优先；缺省 fallback `__default__`；无默认时报错。
- Registry：内置模型从 catalog 解析，自定义模型从 DB 解析。
- Registry：返回 `ResolvedProvider.context_window_tokens`，thinking effort 按模型 capability 钳制。
- Context compaction scheduler：按 resolved provider 的窗口计算阈值，不再使用全局 200k。
- 新 schema 创建测试覆盖三张表和外键关系。

Android：

- Catalog DTO / Account DTO / Binding DTO 解析。
- LLM 连接页：内置 provider 只要求 name + API key；custom 显示 provider type + base URL。
- 连接列表不再显示默认标记。
- 默认模型 / Agent 模型绑定页顶部展示 `__default__`。
- 绑定编辑：选择 account 后模型列表正确刷新。
- 绑定编辑：模型 context window 信息正确展示。
- 切换模型时 thinking effort 被重置或钳制。

## 实施阶段

1. 后端 catalog 与 schema：
   - 添加 catalog JSON 和 loader。
   - 新增 `LLMAccountRecord`、`LLMCustomModelRecord`。
   - 改造 `AgentLLMBindingRecord`。
   - 新增 catalog/account/custom model API。
2. Registry 与运行时：
   - 改造 `LLMProviderRegistry` 解析 binding。
   - 扩展 `ResolvedProvider`。
   - 改造 BaseAgent、memory component、context compactor 调用点。
   - 自动压缩调度接入 `context_window_tokens`。
3. Android：
   - Settings 首页文案改名。
   - Provider 列表/表单改为 account 连接管理。
   - Agent binding 编辑页支持 account + model。
   - 增加默认模型行。
4. 文档与验证：
   - 更新 `docs/architecture/spec/core/llm-provider.md`。
   - 更新 `sebastian/llm/README.md`、`sebastian/store/README.md`、`sebastian/gateway/routes/README.md`、Android 相关 README。
   - 更新 CHANGELOG `[Unreleased]`。

## 风险

- Catalog 模型信息过期：首版通过随版本更新 JSON 解决，不做远程热更新。
- 自定义模型填写错误：UI 明确展示上下文窗口和 thinking 能力，后端只做格式校验，不猜测真实能力。
- 默认 binding 未配置导致系统不可用：初始化或 Settings 页面应引导用户先配置 `__default__`。
- API 命名变化影响 Android：本次是开发期重构，无生产兼容承诺，Android 同步改造。
