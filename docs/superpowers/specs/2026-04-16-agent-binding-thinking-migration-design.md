---
version: "1.0"
last_updated: 2026-04-16
status: planned
---

# Agent Binding 次级页面 & 思考配置迁移设计

## 1. 背景与动机

当前思考档位（thinking effort）的配置有两个痛点：

1. **位置错位**：思考按钮挂在对话页 Composer 上（`ui/composer/ThinkButton.kt`），但思考深度是 agent + provider 的能力属性，放在对话输入口产生层级错位。
2. **不持久化**：`ChatViewModel.activeThinkingEffort` 仅存于内存，每次进 App 重置为 OFF，跨 session 不可复用。
3. **未按 agent 分化**：全局一个 effort 值，所有 agent 共用；但不同 agent 往往绑定不同 provider，其能力（TOGGLE / EFFORT / ADAPTIVE / ALWAYS_ON）不同，全局共用毫无合理性。
4. **Sebastian 被排除**：`agent_llm_bindings` 表主键能装 `"sebastian"`，但 API 层在 3 处主动屏蔽（`gateway/routes/agents.py` L29-30、L56、L78），Sebastian 始终只能用全局默认 provider，用户从 UI 无法调整。

**本次目标**：

- 把思考配置从"对话页每次选"改为"每个 agent-llm-binding 持久化一次配好"
- 为 `AgentBindingsPage` 的每个 agent 条目打开独立的次级设置页，在其中完成 provider 选择 + 思考配置
- 将 Sebastian orchestrator 纳入 agent bindings 体系（置顶分区），与 sub-agent 走同一路径
- 彻底移除 Composer 上的 `ThinkButton` 与相关链路

**非目标**：

- 不保留"对话页临时覆盖 effort"的入口（彻底迁移）
- 不新增 `thinking_budget_tokens` 等 provider-specific 字段（后续需要再扩）
- 不改 `ThinkingCapability` 枚举值（保持 `NONE / TOGGLE / EFFORT / ADAPTIVE / ALWAYS_ON`）
- 不做 Web UI 侧同步

---

## 2. 数据模型变更

扩展 `agent_llm_bindings` 表（`sebastian/store/models.py` L90-103）：

```python
class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True,
    )
    # 新增
    thinking_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    thinking_adaptive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ---
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
    )
```

**字段语义**：

- `thinking_effort`：字符串枚举，取值 `off` / `on` / `low` / `medium` / `high` / `max` / `null`
  - `null` = 未设置（等价于 `off`，但语义上区分"没配"和"明确关闭"）
  - `on` 仅用于 `TOGGLE` 能力
  - `low/medium/high` 用于 `EFFORT` 与 `ADAPTIVE`
  - `max` 仅 `ADAPTIVE`
- `thinking_adaptive`：布尔，仅 `ADAPTIVE` 能力下有意义；为 true 时后端调 LLM 不传 effort，由模型自决
- `NONE` / `ALWAYS_ON` 能力下两字段强制为 `null` / `false`

**迁移**：新增 Alembic migration `add_thinking_fields_to_agent_llm_bindings`，`ALTER TABLE` 加两列，所有现有行使用默认值（null / false）。

---

## 3. 后端改造

### 3.1 API 响应与请求扩展

**路由**：`sebastian/gateway/routes/agents.py`

- `AgentBindingDto` 响应体加 `thinking_effort: str | None` + `thinking_adaptive: bool`
- `SetBindingRequest` 请求体加同两字段（可选，默认 `null` / `false`）
- `GET /api/v1/agents` 列表响应里每个 agent 附带完整 binding（省一次请求）
- `PUT /api/v1/agents/{agent_type}/llm-binding` 切换 provider 时**强制重置**：

```python
async def put_binding(agent_type: str, req: SetBindingRequest):
    old = await repo.get(agent_type)
    if old and old.provider_id != req.provider_id:
        # Provider 切换 → 无视请求体，强制重置
        req = req.model_copy(update={"thinking_effort": None, "thinking_adaptive": False})
    # capability 判定（从新 provider 读）
    new_provider = await provider_repo.get(req.provider_id) if req.provider_id else None
    capability = new_provider.thinking_capability if new_provider else _default_capability()
    if capability in (ThinkingCapability.NONE, ThinkingCapability.ALWAYS_ON):
        req = req.model_copy(update={"thinking_effort": None, "thinking_adaptive": False})
    await repo.upsert(agent_type, req)
```

### 3.2 解除 Sebastian 屏蔽

`sebastian/gateway/routes/agents.py`：

- 删 L29-30 列表排除（`if agent_type == "sebastian": continue`）
- 删 L56 与 L78 的 `agent_type != "sebastian"` 校验
- 列表响应中 Sebastian 用虚拟 `AgentConfig`：
  ```python
  AgentConfig(
      agent_type="sebastian",
      display_name="Sebastian",
      description="Main orchestrator",
      is_orchestrator=True,  # 新字段，前端用来分区
  )
  ```

### 3.3 思考参数注入

扩展 `sebastian/llm/registry.py` 的 `get_provider` 返回值，一次性携带 binding 的 thinking 配置，避免 `base_agent` 中重复查询 binding 表：

```python
# registry.py
@dataclass
class ResolvedProvider:
    provider: LLMProvider
    model: str
    thinking_effort: str | None      # 已按 capability 钳制过
    thinking_adaptive: bool

async def get_provider(self, agent_type: str | None = None) -> ResolvedProvider:
    binding = await self._get_binding(agent_type) if agent_type else None
    record = (
        await self._get_record(binding.provider_id)
        if binding and binding.provider_id
        else await self._get_default_record()
    )
    # 防御性钳制：record.thinking_capability 不支持时强制清空
    effort, adaptive = _coerce_thinking(
        binding.thinking_effort if binding else None,
        binding.thinking_adaptive if binding else False,
        record.thinking_capability,
    )
    return ResolvedProvider(self._instantiate(record), record.model, effort, adaptive)
```

`sebastian/core/base_agent.py` 的 `turn()` 使用该结构：

```python
resolved = await self._llm_registry.get_provider(self.name)
llm_kwargs = {}
if resolved.thinking_adaptive:
    llm_kwargs["thinking"] = {"mode": "adaptive"}
elif resolved.thinking_effort and resolved.thinking_effort != "off":
    llm_kwargs["thinking"] = {"effort": resolved.thinking_effort}
# ALWAYS_ON provider 由 adapter 内部处理，不传参

response = await resolved.provider.chat(model=resolved.model, ..., **llm_kwargs)
```

具体 provider adapter（`sebastian/llm/providers/*.py`）按其 SDK 约定将 `thinking` 参数翻译为各自的入参（Anthropic 的 `thinking` 块、OpenAI 的 `reasoning_effort` 等）。

### 3.4 废弃 `SendTurnRequest.thinking_effort`

- `sebastian/gateway/routes/sessions.py` 的 `SendTurnRequest` Pydantic model 移除 `thinking_effort` 字段（若有）
- 所有下游读取点同步移除
- 前端 DTO 一起清理（见 § 4）

---

## 4. 前端架构（Android）

### 4.1 路由

`ui/navigation/Route.kt` 新增：

```kotlin
@Serializable
data class SettingsAgentBindingEditor(val agentType: String) : Route
```

`MainActivity.kt` 的 NavHost 注册对应 composable，从 `SettingsAgentBindings` 点击 item 触发 `navController.navigate(SettingsAgentBindingEditor(agentType))`。

### 4.2 新增文件

| 路径 | 职责 |
|---|---|
| `ui/settings/AgentBindingEditorPage.kt` | 次级页 Screen |
| `viewmodel/AgentBindingEditorViewModel.kt` | 单 binding 的状态 + 即时保存（debounce） |
| `ui/settings/components/ProviderPickerDialog.kt` | 居中浮层 provider 选择（替代 BottomSheet） |
| `ui/settings/components/EffortSlider.kt` | 按 capability 渲染的档位 slider |
| `ui/settings/components/AdaptiveSwitch.kt` | ADAPTIVE 能力下的自适应开关 |

### 4.3 改造与删除

**改造**：

- `ui/settings/AgentBindingsPage.kt` — 删 `ModalBottomSheet` 与 `ProviderPickerContent`，保留列表；item 点击改为 navigate；列表加"Orchestrator / Sub-Agents"分区
- `data/remote/dto/AgentBindingDto.kt` — 加 `thinking_effort` + `thinking_adaptive`
- `data/remote/dto/SetBindingRequest.kt` — 加同两字段
- `data/repository/AgentRepository.kt` — `setBinding` 签名加两参数
- `viewmodel/AgentBindingsViewModel.kt` — 原 sheet 相关 state 移除，仅保留列表加载

**删除**：

- `ui/composer/ThinkButton.kt` — 整个文件删除
- `ui/composer/EffortPickerCard.kt` — 整个文件删除（`ThinkButton` 点击弹出的档位选择面板）
- `ui/chat/ChatScreen.kt`：删除 `EffortPickerCard` import（L63）、`showEffortPicker` state（L154）、EffortPickerCard overlay 整块（L328-370 附近）、传给 Composer 的 `onShowEffortPicker` 回调（L379）
- `ui/composer/Composer.kt`：删 `ThinkButton` 引用 + `onShowEffortPicker` 参数。ThinkButton 原占位不收缩 Composer 高度
- `ChatViewModel.kt`：`activeThinkingEffort` state、`setEffort()` 方法、`sendTurn` 的 effort 参数
- `SendTurnRequest.kt`：`thinkingEffort` 字段
- `ChatRepositoryImpl.kt` L76-82：effort → 后端字符串的映射逻辑

### 4.4 `AgentBindingEditorViewModel`

```kotlin
data class EditorUiState(
    val agentType: String,
    val agentDisplayName: String,
    val isOrchestrator: Boolean,
    val providers: List<Provider>,
    val selectedProvider: Provider?,       // null = 走 Use default
    val thinkingEffort: ThinkingEffort,    // OFF/ON/LOW/MEDIUM/HIGH/MAX
    val thinkingAdaptive: Boolean,
    val isSaving: Boolean,
    val errorMessage: String?,
    val loadState: LoadState,              // Loading / Ready / Error
) {
    val effectiveCapability: ThinkingCapability?
        get() = (selectedProvider ?: providers.firstOrNull { it.isDefault })?.thinkingCapability
}

class AgentBindingEditorViewModel : ViewModel() {
    fun selectProvider(providerId: String?)
    fun setEffort(effort: ThinkingEffort)
    fun setAdaptive(enabled: Boolean)
    // 内部：所有 setter 合并走同一个 debounced PUT job（300ms）
}
```

**即时保存**：每个 setter 先改本地 state，`debounceJob?.cancel()` + `launch { delay(300); put(...) }`。PUT 失败 → snackbar + state 回滚到保存前快照。

**Provider 切换即重置**：`selectProvider` 内部除了 `selectedProvider`，强制 `thinkingEffort = OFF` + `thinkingAdaptive = false`。仅当旧配置非空时 snackbar 提示 `Thinking config reset for new provider`。

**capability fallback**：UI 渲染条件一律读 `effectiveCapability`，而非 `selectedProvider.thinkingCapability`。这样"Use default provider"时下方仍能按全局默认 provider 的能力渲染。

**越界钳制**：state 初始化时若 `thinkingEffort` 不在 `effectiveCapability` 支持的刻度里，钳到最高合法刻度（防御历史数据）。

---

## 5. UI 规范

### 5.1 `AgentBindingsPage` 列表

```
┌─────────────────────────────────┐
│ Agent LLM Bindings           [<]│
├─ Orchestrator ──────────────────┤
│ ┌─────────────────────────────┐ │
│ │ [icon] Sebastian            │ │
│ │        Claude Sonnet · high │ │
│ └─────────────────────────────┘ │
├─ Sub-Agents ────────────────────┤
│ ┌─────────────────────────────┐ │
│ │ [icon] ResearchAgent        │ │
│ │        Claude · adaptive    │ │
│ └─────────────────────────────┘ │
│ ...                             │
└─────────────────────────────────┘
```

- 分区 header 用 `Text` + `HorizontalDivider`
- Orchestrator 区固定置顶，始终只有 1 条（Sebastian）
- Sub-Agents 区按后端返回顺序
- item 用 `ElevatedCard`
- Leading icon：Orchestrator 用 `Icons.Outlined.AutoAwesome`，Sub-Agent 用 `Icons.Outlined.Extension`
- 副标题规则：
  - 已绑定：`${provider.displayName} · ${effortLabel}`（effort 为 OFF 时省略）
  - 未绑定：`Use default · ${defaultProvider?.displayName ?: "—"}`

### 5.2 `AgentBindingEditorPage` 布局

```
┌─────────────────────────────────┐
│ [<] Sebastian                   │
├─────────────────────────────────┤
│ LLM Provider                    │
│ ┌─────────────────────────────┐ │
│ │ [icon] Claude Sonnet 4.6  ▸ │ │
│ │        Anthropic            │ │
│ └─────────────────────────────┘ │
│                                 │
│ Thinking Depth                  │
│  ●───○───○───○───○             │
│  Off  Low  Med  High  Max       │
│                                 │
│ ┌─────────────────────────────┐ │
│ │ Adaptive Thinking     [●─] │ │
│ │ Let the model decide        │ │
│ │ thinking depth              │ │
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

- 所有文案英文
- 所有区块不使用 emoji，图标一律 Material Icons
- Provider 卡片：`ElevatedCard` with shadow，点击弹 `ProviderPickerDialog`
- Thinking Depth slider 仅在 `effectiveCapability ∈ {TOGGLE, EFFORT, ADAPTIVE}` 时渲染
- Adaptive switch 仅在 `effectiveCapability == ADAPTIVE` 时渲染
- Adaptive switch 开启 → EffortSlider `enabled=false`（整体半透明 + 不响应点击）

### 5.3 `ProviderPickerDialog`

Material3 `AlertDialog` + 自定义 content，居中悬浮。无确定/取消按钮（点击即选即关）：

```
┌─────────────────────────────┐
│ Select LLM Provider         │
├─────────────────────────────┤
│  Use default provider     ⨉ │  ← 首行固定，代表 null
├─────────────────────────────┤
│  Claude Sonnet 4.6       ✓ │
│  Anthropic                  │
├─────────────────────────────┤
│  GPT-4o                     │
│  OpenAI                     │
├─────────────────────────────┤
│  Gemini 2.0 Flash           │
│  Google                     │
└─────────────────────────────┘
```

- 当前选中项左侧 `Icons.Filled.CheckCircle`
- "Use default provider" 与当前 `selectedProvider == null` 等价

### 5.4 `EffortSlider`

```kotlin
@Composable
fun EffortSlider(
    capability: ThinkingCapability,
    value: ThinkingEffort,
    onValueChange: (ThinkingEffort) -> Unit,
    enabled: Boolean = true,
)
```

刻度数组按 capability 决定：

| capability | 刻度 | 数量 |
|---|---|---|
| `TOGGLE` | `[Off, On]` | 2（渲染为 Switch，不用 slider） |
| `EFFORT` | `[Off, Low, Medium, High]` | 4 |
| `ADAPTIVE` | `[Off, Low, Medium, High, Max]` | 5 |

实现用 `Slider(steps = size - 2)` + 下方等宽标签行。`enabled=false` 时透明度 0.38 + `Modifier.pointerInput { }` 吞点击。

**特例**：`TOGGLE` 不用 slider，用 `SebastianSwitch`（`ui/common/SebastianSwitch.kt`，苹果风绿色公共组件）+ leading label `Thinking`（Off/On）。视觉上和档位条区分。

### 5.5 `AdaptiveSwitch`

Material3 `ListItem` + trailing `SebastianSwitch`（复用 `ui/common/SebastianSwitch.kt`，苹果风绿色）：

- `headlineContent`: `Adaptive Thinking`
- `supportingContent`: `Let the model decide thinking depth`
- `trailingContent`: `SebastianSwitch(checked, onCheckedChange)`

### 5.6 `ALWAYS_ON` / `NONE` 能力

- `ALWAYS_ON` → 渲染只读 `ListItem`：`Thinking: Always on (controlled by model)`，无交互
- `NONE` → 整个思考区块不渲染，页面只剩 Provider 卡片
- `effectiveCapability == null`（全局也没默认 provider）→ 思考区不渲染，Provider 卡片下显示 `No default provider configured`

---

## 6. 交互与边界

### 6.1 即时保存

- 所有 setter debounce 300ms 合并为一次 PUT
- PUT 期间 `isSaving=true`，但控件不置灰（避免闪烁），再次改动会 cancel 上一次 debounce
- PUT 成功静默
- PUT 失败 → snackbar `Failed to save. Retry?` + state 回滚到保存前快照

### 6.2 Provider 切换重置

**前端**：`selectProvider` 本地立刻重置 effort/adaptive。旧配置非空时 snackbar 提示 `Thinking config reset for new provider`。

**后端**：`PUT` 检测到 `provider_id` 变化时强制把 effort/adaptive 置空，即使请求体里带了值。双保险。

### 6.3 Use default provider 时的 capability fallback

`effectiveCapability` 派生属性读取 `selectedProvider ?: providers.first { isDefault }` 的 capability。无需额外 API。若全局也没默认 provider，展示 `No default provider configured` 静态文案。

### 6.4 越界钳制

`ViewModel` 初始化 state 时：若 `thinking_effort` 不在 `effectiveCapability` 支持的刻度中（例如 DB 存的 `max` 但 provider 换成 EFFORT），钳到最高合法刻度（EFFORT → `high`）。同时立刻触发一次 PUT 把 DB 纠正到合法值。

### 6.5 加载态 / 错误态

- 进页面并行拉 `GET /api/v1/agents/{agent_type}/llm-binding` + `GET /api/v1/llm-providers`
- 期间显示 `CircularProgressIndicator`
- 任一失败 → 全页 `ErrorState` + `Retry`

### 6.6 聊天页联动

- `ThinkButton` 移除后，Composer 中该位置留空，**不收缩整体高度**
- `sendTurn()` 签名去 `effort` 参数，后端从 binding 读
- 聊天页 UI 不展示当前 effort 档位（"管家配好就走"心智）
- 思考中间块（`ThinkingCard`）渲染逻辑不变

---

## 7. 测试计划

### 7.1 后端单元测试（`tests/unit/`）

- `test_agent_llm_binding_model.py`
  - 新字段默认值：`thinking_effort=None, thinking_adaptive=False`
- `test_agent_llm_binding_api.py`
  - `PUT` 带完整字段 → 正确写入
  - `PUT` 切换 `provider_id` → 即使请求体带 effort 也被强制重置
  - `PUT` 同一 provider 改 effort → 正常保留
  - `PUT` 到 NONE/ALWAYS_ON provider → effort/adaptive 强制 null/false
  - `GET` Sebastian 不再返回 403
  - `GET /api/v1/agents` 响应包含 `sebastian` 条目且 `is_orchestrator=true`
  - 列表响应每项附带完整 binding
- `test_base_agent_thinking_injection.py`
  - binding 有 effort → LLM 调用参数包含 `thinking.effort`
  - binding adaptive=true → LLM 调用参数包含 `thinking.mode=adaptive`，不传 effort
  - NONE / ALWAYS_ON provider → 不传 thinking 参数
  - 无 binding / binding.provider_id=null → 用全局默认 provider，不传 thinking 参数

### 7.2 后端集成测试（`tests/integration/`）

- `test_agent_binding_flow.py`：Sebastian 和 sub-agent 独立绑定不同 provider，互不干扰；binding 持久化跨重启
- `test_sessions_send_turn.py`：`SendTurnRequest` 不再接受 `thinking_effort`（已废弃）

### 7.3 Android 单元测试（`app/src/test/`）

- `AgentBindingEditorViewModelTest`
  - `selectProvider` → 本地立即重置 effort/adaptive + debounce PUT
  - `setEffort` / `setAdaptive` → debounce 合并连续改动为一次 PUT（用 fake dispatcher 控时间）
  - PUT 失败 → state 回滚 + errorMessage 设置
  - `effectiveCapability` 在 `selectedProvider == null` 时走 `isDefault=true` 的 provider
  - 越界钳制：初始 state `thinkingEffort=MAX` 但 provider capability=EFFORT → 钳到 HIGH 并触发 PUT
- `EffortSliderTest` / `ThinkingCapabilityStepsTest`（纯 util）
  - TOGGLE → 2 档、EFFORT → 4 档、ADAPTIVE → 5 档

### 7.4 手动验收清单

- [ ] Bindings 列表顶部出现 `Orchestrator` 分区 + Sebastian 条目
- [ ] Sub-Agents 分区下方按原顺序展示 sub-agent
- [ ] 点击任一条目进入 Editor 次级页
- [ ] Provider 卡片点击弹出居中 `ProviderPickerDialog`（非 BottomSheet）
- [ ] Dialog 首行 "Use default provider" 正常工作
- [ ] 选 EFFORT capability provider → 4 档 slider，无 Adaptive 开关
- [ ] 选 ADAPTIVE capability provider → 5 档 slider + Adaptive 开关
- [ ] Adaptive 开关开启 → slider 整体半透明 + 不响应点击；关闭 → 恢复
- [ ] 选 TOGGLE capability provider → Switch（非 slider）
- [ ] 选 NONE 能力 provider → 思考区完全隐藏
- [ ] 选 ALWAYS_ON provider → 显示只读 `Thinking: Always on` label
- [ ] 切换 provider → snackbar `Thinking config reset for new provider`，且 effort 回到 Off
- [ ] 返回列表页，item 副标题正确反映最新绑定
- [ ] Composer 已无 ThinkButton，整体高度**不变**
- [ ] 对话页 ChatScreen 已无 `EffortPickerCard` 浮层（不再有任何地方会弹出档位面板）
- [ ] 发一条消息，后端日志可见 binding 中的 effort 被注入到 LLM 调用
- [ ] 所有文案英文，无 emoji
- [ ] `GET /api/v1/llm-providers` 无默认 provider 的极端情况下，编辑页显示 `No default provider configured`

---

## 8. 风险与回滚

**风险**：

- 后端 `base_agent.py` 的 LLM 参数注入需要适配所有 provider adapter（Anthropic / OpenAI / Google / ...），若某 adapter 未实现 `thinking` 参数翻译会静默失效
  - 对策：`test_base_agent_thinking_injection.py` 中针对每个 adapter 单独验证参数透传
- 历史 `SendTurnRequest.thinking_effort` 字段移除会 break 旧版 Android App
  - 对策：此字段原本就没持久化效果（每次进 App 重置 OFF），影响可忽略；发版 notes 中说明需升级 App

**回滚**：

- DB migration 可 downgrade（drop 两列，现有代码不读取时无副作用）
- 前端通过 feature flag 不必要（一次性切换，回滚即 revert commit）

---

## 9. 受影响文件清单

### 后端
- `sebastian/store/models.py` — 扩 `AgentLLMBindingRecord`
- `sebastian/store/migrations/versions/xxxx_add_thinking_fields.py` — 新建
- `sebastian/store/agent_binding_repository.py` — repo 方法签名扩展
- `sebastian/gateway/routes/agents.py` — DTO 扩展、解除 Sebastian 屏蔽、列表响应 attach binding
- `sebastian/gateway/routes/sessions.py` — `SendTurnRequest` 移除 `thinking_effort`
- `sebastian/core/base_agent.py` — 读 binding 注入 LLM 参数
- `sebastian/llm/providers/anthropic.py` / `openai.py` / `google.py` — 确保 `thinking` kwarg 翻译

### Android
- `app/src/main/java/com/sebastian/android/ui/navigation/Route.kt` — 新 route
- `app/src/main/java/com/sebastian/android/MainActivity.kt` — NavHost 注册
- `app/src/main/java/com/sebastian/android/ui/settings/AgentBindingsPage.kt` — 改造
- `app/src/main/java/com/sebastian/android/ui/settings/AgentBindingEditorPage.kt` — 新建
- `app/src/main/java/com/sebastian/android/ui/settings/components/ProviderPickerDialog.kt` — 新建
- `app/src/main/java/com/sebastian/android/ui/settings/components/EffortSlider.kt` — 新建
- `app/src/main/java/com/sebastian/android/ui/settings/components/AdaptiveSwitch.kt` — 新建
- `app/src/main/java/com/sebastian/android/viewmodel/AgentBindingEditorViewModel.kt` — 新建
- `app/src/main/java/com/sebastian/android/viewmodel/AgentBindingsViewModel.kt` — 简化
- `app/src/main/java/com/sebastian/android/data/remote/dto/AgentBindingDto.kt` — 加两字段
- `app/src/main/java/com/sebastian/android/data/remote/dto/SetBindingRequest.kt` — 加两字段
- `app/src/main/java/com/sebastian/android/data/remote/dto/SendTurnRequest.kt` — 删 `thinkingEffort`
- `app/src/main/java/com/sebastian/android/data/repository/AgentRepository.kt` — 接口扩展
- `app/src/main/java/com/sebastian/android/data/repository/ChatRepositoryImpl.kt` — 删 effort 映射
- `app/src/main/java/com/sebastian/android/viewmodel/ChatViewModel.kt` — 删 `activeThinkingEffort` 等
- `app/src/main/java/com/sebastian/android/ui/composer/Composer.kt` — 删 `ThinkButton` 引用与 `onShowEffortPicker` 参数
- `app/src/main/java/com/sebastian/android/ui/composer/ThinkButton.kt` — 删除
- `app/src/main/java/com/sebastian/android/ui/composer/EffortPickerCard.kt` — 删除
- `app/src/main/java/com/sebastian/android/ui/chat/ChatScreen.kt` — 删 `EffortPickerCard` import、`showEffortPicker` state、overlay 渲染块、`onShowEffortPicker` 回调

### 文档
- `ui/mobile-android/README.md` — 修改导航表更新 Composer 行、AgentBindings 行
- `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/README.md` — 若有相关章节同步
- 本 spec 归档到 `docs/architecture/spec/` 由后续 `/integrate-spec` 流程处理
