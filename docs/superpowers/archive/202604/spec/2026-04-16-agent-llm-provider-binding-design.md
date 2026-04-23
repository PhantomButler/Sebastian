---
version: "1.0"
last_updated: 2026-04-16
status: planned
integrated_to: core/llm-provider.md
integrated_at: 2026-04-23
---

# Agent ↔ LLM Provider 绑定系统设计

## 1. 背景与动机

当前 Sebastian 的 LLM Provider 体系支持用户在 Settings 里管理多条 provider 记录，并通过 `is_default` 标记一条为全局默认。但不支持"给每个 agent 指定特定 provider"的语义：

- 现有 `manifest.toml [llm]` 段按 `provider_type` 匹配 DB 第一条记录，多条同类型 provider 时行为不确定
- 绑定写在代码库中的 manifest 文件，用户无法从 UI 动态调整
- 前端 Settings 无 agent 配置入口

**目标**：把所有 provider 记录视为共享池，允许用户从 UI 为每个 sub-agent 从池中挑选一个 provider 绑定；未绑定的 agent fallback 到全局默认 provider。

**非目标**：
- 不改造 Sebastian orchestrator 的 provider 解析路径（继续用全局默认）
- 不支持"绑定时独立指定 model"（model 随 provider record 走）
- 不改 provider 的命名（保持 `LLMProviderRecord`、`llm_providers` 表名、`/api/v1/llm-providers` 路径；用户端靠 `name` 字段自由命名区分）
- 不做 Web UI（暂仅 Android）

---

## 2. 数据模型

新增表 `agent_llm_bindings`：

```python
# sebastian/store/models.py

class AgentLLMBindingRecord(Base):
    __tablename__ = "agent_llm_bindings"

    agent_type: Mapped[str] = mapped_column(String, primary_key=True)   # "forge" / "aide" ...
    provider_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("llm_providers.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**语义**：
- `agent_type` 为主键，一个 agent 只有一条绑定记录
- `provider_id = NULL` 或表中无记录 → 等价于"使用全局默认 provider"
- 外键 `ON DELETE SET NULL`：删除 provider 时自动把所有引用它的绑定置空，静默 fallback 到全局默认
- Sebastian orchestrator 不写入此表

**迁移**：Alembic 新增 migration 创建表。无存量数据迁移需求（现有 manifest.toml 未声明 `[llm]` 段）。

---

## 3. Registry 改造

文件：`sebastian/llm/registry.py`

### 3.1 `get_provider` 查询源切换

```python
async def get_provider(self, agent_type: str | None = None) -> tuple[LLMProvider, str]:
    """Return (provider, model) for the given agent_type.

    Checks agent_llm_bindings table first.
    Falls back to get_default_with_model() if no binding or binding's provider is gone.
    """
    if agent_type is not None:
        binding = await self._get_binding(agent_type)
        if binding and binding.provider_id:
            record = await self._get_record(binding.provider_id)
            if record is not None:
                return self._instantiate(record), record.model
    return await self.get_default_with_model()
```

### 3.2 删除内容

- 函数 `_read_manifest_llm(agent_type)` 整体删除
- 方法 `_get_by_type(provider_type)` 整体删除（按 type 匹配的老逻辑不再需要）
- `manifest.toml` 文档里关于 `[llm]` 段的描述移除

### 3.3 新增内容

```python
async def _get_binding(self, agent_type: str) -> AgentLLMBindingRecord | None: ...
async def _get_record(self, provider_id: str) -> LLMProviderRecord | None: ...

async def list_bindings(self) -> list[AgentLLMBindingRecord]:
    """Return all binding records. Used by GET /api/v1/agents to assemble response."""

async def set_binding(self, agent_type: str, provider_id: str | None) -> AgentLLMBindingRecord:
    """Upsert a binding. provider_id=None means 'use default'."""

async def clear_binding(self, agent_type: str) -> None:
    """Remove binding for the given agent_type. Equivalent to set_binding(agent_type, None)."""
```

---

## 4. BaseAgent / AgentLoop 集成

**零结构改动**。现有代码 `sebastian/core/base_agent.py:280-283` 已经在每个 turn 开始时调用 `self._llm_registry.get_provider(self.name)` 并 mutate `self._loop._provider / _model`：

```python
if not self._provider_injected and self._llm_registry is not None:
    provider, model = await self._llm_registry.get_provider(self.name)
    self._loop._provider = provider
    self._loop._model = model
```

Registry 内部查询源换成 binding 表后，此处自动读到最新绑定。无需改 BaseAgent 结构。

**生效时机**：per-turn live。用户改绑定 → 正在进行的 turn 保持旧 provider（mutation 发生在 turn 入口）→ 下一个 turn 使用新 provider。

**Sebastian orchestrator**：保持 `get_default_with_model()` 调用路径不变。

**跨 provider type 换绑的边界**：
- Anthropic → OpenAI：OpenAI provider 不发 thinking block，历史 thinking block 在构造请求时会被过滤（现有 provider 实现已处理）
- OpenAI → Anthropic：历史无 thinking signature，Anthropic provider 构造请求时不会在 assistant 历史块里塞 signature 字段
- 两种方向都不会因 binding 切换触发 API 拒绝。实际运行中遇到异常的用户可重开 session 恢复

---

## 5. Gateway 路由

### 5.1 扩展现有 `GET /api/v1/agents`

文件：`sebastian/gateway/routes/agents.py`

给每个 agent 条目增加 `bound_provider_id` 字段：

```python
@router.get("/agents")
async def list_agents(...) -> JSONDict:
    import sebastian.gateway.state as state

    bindings = await state.llm_registry.list_bindings()
    binding_map = {b.agent_type: b.provider_id for b in bindings}

    agents = []
    for agent_type, config in state.agent_registry.items():
        if agent_type == "sebastian":
            continue
        sessions = await state.index_store.list_by_agent_type(agent_type)
        active_count = sum(1 for s in sessions if s.get("status") == "active")

        agents.append({
            "agent_type": agent_type,
            "description": config.description,
            "active_session_count": active_count,
            "max_children": config.max_children,
            "bound_provider_id": binding_map.get(agent_type),
        })
    return {"agents": agents}
```

**兼容性**：现有字段全保留，`bound_provider_id` 是纯新增字段，旧前端忽略即可。

### 5.2 新增 binding 写路由

```
PUT    /api/v1/agents/{agent_type}/llm-binding
       body: { "provider_id": "uuid-xxx" | null }
       200 → { "agent_type": "...", "provider_id": "..." | null }
       404 → agent_type 不存在
       400 → provider_id 存在但 DB 无此 provider 记录

DELETE /api/v1/agents/{agent_type}/llm-binding
       204 No Content
       （语义等价于 PUT null，前端任选其一使用）
```

**Provider 删除路由保持不变**：`DELETE /api/v1/llm-providers/{id}` 依赖 DB 外键 `ON DELETE SET NULL` 自动清理绑定，后端 handler 不需额外逻辑。

**注意：SQLite 外键需显式启用**。当前 `sebastian/store/database.py` 未设置 `PRAGMA foreign_keys=ON`，SQLite 默认不强制外键。实施时必须在 engine connect 事件上启用此 pragma，否则 `ON DELETE SET NULL` 不生效。方案见 §10 实施检查清单。

### 5.3 认证

所有新路由继承 `require_auth` 依赖，与现有 agents / providers 路由一致。

---

## 6. Android 前端

### 6.1 导航结构

Settings 主页新增一个 list item：

```
Settings
├─ LLM Providers           >   (已有子页)
├─ Agent LLM Bindings      >   (新增子页)
├─ ...
```

### 6.2 `AgentBindingsScreen` 子页

**结构**：
```
┌─────────────────────────────────────────┐
│  ← Agent LLM Bindings                   │
├─────────────────────────────────────────┤
│  Select a provider for each agent,      │
│  or use the global default.             │
├─────────────────────────────────────────┤
│  Forge Agent                            │
│  Code writing and refactoring           │
│  Provider: Claude Sonnet 家用       >   │
├─────────────────────────────────────────┤
│  Aide Agent                             │
│  Research and summary                   │
│  Provider: Use Default              >   │
└─────────────────────────────────────────┘
```

**交互**：点整行 → 弹 `ProviderPickerBottomSheet`，包含 `Use Default` + provider 池中所有条目（按 `name` 显示）。选中后：
- `Use Default` → `DELETE /llm-binding`
- 具体 provider → `PUT /llm-binding {provider_id}`
- 成功：调用 `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt` 展示中心气泡，文案固定英文 `"Binding will take effect on next message."`
- 失败：同样经 `ToastCenter` 显示错误信息（沿用项目统一错误 toast 规范）

### 6.3 数据层

新增：
- `AgentApi`（Retrofit interface）：`listAgents()`、`putBinding(agentType, providerId?)`、`deleteBinding(agentType)`
- `AgentRepository`：包装 API，暴露 `Flow<List<AgentInfo>>`
- `AgentBindingsViewModel`（Hilt injected）：组合 `AgentRepository` + 现有 `LlmProviderRepository`，输出 `UiState`（agent 列表 + provider 池）

复用：
- 现有 `LlmProviderRepository.providers` 作为 provider 池数据源
- 现有 Toast 组件 `com.sebastian.android.ui.common.ToastCenter`（位于 [ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt](ui/mobile-android/app/src/main/java/com/sebastian/android/ui/common/ToastCenter.kt)）

### 6.4 展开/折叠与排序

- 所有 agent 默认展开显示（个人用户 agent 数量有限，不需要折叠）
- 列表按 `agent_type` 字母序排列（或服务端返回顺序）

### 6.5 Provider 选择器展示

`ProviderPickerBottomSheet` 的每一项显示：
- 第一行：`name`（粗体）
- 第二行：`provider_type` · `model`（次要文字）
- 当前选中项打勾

`Use Default` 项单独列在最顶部，附说明 "Follow global default provider"。

---

## 7. 规格文档同步

以下 spec 需要更新（作为 implementation 步骤的一部分）：

- `docs/architecture/spec/core/llm-provider.md`
  - §2.3 per-agent 模型选择 → 改为描述 `agent_llm_bindings` 表及语义
  - §7 LLMProviderRegistry → 更新 `get_provider` 优先级描述
  - §8.2 BaseAgent 集成 → 保留（实现逻辑不变）
  - §10 Gateway 路由 → 增加 `/agents/{agent_type}/llm-binding` 两条
- `docs/architecture/spec/overview/three-tier-agent.md` → 若有提及 manifest `[llm]` 段，改为 binding 表
- `docs/architecture/spec/agents/INDEX.md` → 如有需要，补一条链接
- `sebastian/agents/README.md` → 删除/修订 manifest `[llm]` 段说明
- `sebastian/llm/README.md`（若存在） → 同步

---

## 8. 测试计划

### 8.1 后端单元测试

- `tests/unit/llm/test_registry_bindings.py`
  - `get_provider` 命中 binding → 返回对应 provider + model
  - `get_provider` binding 存在但 `provider_id` 为 NULL → fallback 默认
  - `get_provider` binding 不存在 → fallback 默认
  - `get_provider` binding 的 `provider_id` 指向已删除的 record → fallback 默认（外键 SET NULL 生效路径）
  - `set_binding` upsert 语义：首次插入、覆盖更新
  - `clear_binding` 删除行为
  - `list_bindings` 返回格式

- `tests/unit/gateway/test_agents_route.py`
  - `GET /agents` 响应包含 `bound_provider_id` 字段
  - `PUT /agents/{type}/llm-binding` 写入 binding
  - `PUT` provider_id 指向不存在记录 → 400
  - `DELETE /agents/{type}/llm-binding` 清除 binding
  - 未知 `agent_type` → 404

- `tests/unit/llm/test_registry_legacy_removed.py`
  - 确认 `_read_manifest_llm` 已移除（import error 或 attribute error）
  - 即使 manifest 包含 `[llm]` 段也不影响 provider 解析（manifest fallback 彻底废弃）

### 8.2 集成测试

- `tests/integration/test_agent_provider_binding.py`
  - 创建两个 provider，绑定 forge → providerA、aide 未绑 → fallback default
  - 发 turn 给 forge，确认 AgentLoop 使用 providerA（mock LLM 按 API key/model 区分）
  - 切换 forge binding → providerB，下一个 turn 切换成功

### 8.3 Android 单元测试

- `AgentBindingsViewModelTest`：loading/success/error 状态流转
- `AgentBindingsRepositoryTest`：API 调用、错误映射
- UI 测试（可选）：Picker 选中 "Use Default" → 触发 DELETE，选中具体 provider → 触发 PUT

### 8.4 手动验证

- Android 端 Settings → Agent LLM Bindings 子页渲染正常
- 为 forge 绑定 sonnet 后下一条消息生效；删除 sonnet provider 后 forge 绑定自动置空
- Toast "Binding will take effect on next message." 出现时机、位置正确

---

## 9. 风险与备注

- **Provider 跨 type 切换**：Anthropic ↔ OpenAI 切换的历史兼容性由现有 Provider 实现兜底（见 §4）。极端场景用户可重开 session。
- **Binding 表主键选择**：用 `agent_type` 作 PK 限制了"同一 agent 多个并行会话不能用不同 provider"。这与 Q5"per-turn live"决策一致，且与 BaseAgent singleton 架构自洽。未来如需 per-session 独立 provider，需要另起一套 session-level override 设计，不在本次范围。
- **Sebastian orchestrator 不纳入绑定**：用户想"Sebastian 用 X、sub-agent 默认用 Y"的场景，将 X 设为全局默认 + 把需要 Y 的 sub-agent 逐个绑定到 Y 即可达成。
- **Registry 事务边界**：`set_binding` 使用 SQLAlchemy `merge` 或显式 upsert。provider record 删除时 ON DELETE SET NULL 由数据库层保证（需确认 SQLite 的 `PRAGMA foreign_keys=ON` 已启用 —— 现有 store 应已处理，实施时复核）。

---

## 10. 实施检查清单

- [ ] DB migration：新增 `agent_llm_bindings` 表
- [ ] `sebastian/store/models.py`：新增 `AgentLLMBindingRecord`
- [ ] `sebastian/llm/registry.py`：改 `get_provider`、删 `_read_manifest_llm` / `_get_by_type`、加 binding CRUD
- [ ] `sebastian/gateway/routes/agents.py`：扩展 `GET /agents`、新增 `PUT/DELETE /agents/{type}/llm-binding`
- [ ] `sebastian/gateway/state.py`：确认 `llm_registry` 暴露方式支持 route 调用
- [ ] 更新 spec 文档（见 §7）
- [ ] Android：新增 `AgentApi`、`AgentRepository`、`AgentBindingsViewModel`、`AgentBindingsScreen`、`ProviderPickerBottomSheet`、Settings 导航入口
- [ ] 单元测试（后端 + Android）
- [ ] 集成测试
- [ ] 手动端到端验证
