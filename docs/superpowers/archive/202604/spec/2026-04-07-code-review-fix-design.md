# Code Review 修复设计

**版本**：v1.0
**日期**：2026-04-07
**状态**：设计完成，待实施
**来源**：Sebastian 代码审查完整报告（30 个问题，4 个 Critical / 10 个 High / 12 个 Medium / 4 个 Low）

---

## 设计原则

- 最短路径实现：直接改到位，不打兼容性补丁
- 不引入新抽象层，除非现有结构必须重组
- 分 4 批提交，每批独立可测试
- 开发环境假设：`llm_providers` 表无历史数据，C1 无需 Alembic migration

---

## Batch 1 — 后端核心正确性

解决 Critical 全部 + 高价值 High，共 6 个问题（C1 / C2+H6 / H1 / H2 / H3 / H4+H5+M4）。

### C1：api_key 加密存储

**问题**：`LLMProviderRecord.api_key` 明文存 SQLite，GET 接口明文返回。

**修复**：

1. `pyproject.toml`：dependencies 加 `cryptography>=42.0`
2. 新建 `sebastian/llm/crypto.py`：
   - `encrypt(plain: str) -> str` / `decrypt(enc: str) -> str`
   - 使用 `cryptography.fernet.Fernet`，密钥从 `SEBASTIAN_JWT_SECRET` 派生（`base64.urlsafe_b64encode(hashlib.sha256(jwt_secret.encode()).digest())`）
   - 无需新增 env var，JWT secret 已是必填项
3. `store/models.py`：
   - `api_key: Mapped[str]` → `api_key_enc: Mapped[str]`
   - `created_at` / `updated_at` 的 `default=datetime.utcnow` → `default=lambda: datetime.now(UTC)`（顺带修 M5）
5. `llm/registry.py`：
   - `create(record)` 前调用 `encrypt(record.api_key_enc)`（入参仍叫 api_key，存储前加密）
   - `update(id, **kwargs)` 若 kwargs 含 `api_key_enc` 则先加密
   - `_instantiate(record)` 调用 `decrypt(record.api_key_enc)` 获取明文
6. `gateway/routes/llm_providers.py`：
   - `_record_to_dict` 移除 `api_key_enc` 字段，GET 不返回任何密钥字段
   - `LLMProviderCreate.api_key` 保持（前端输入字段名），路由层调用 `encrypt` 后写入 `api_key_enc`
7. DB 处理：drop table `llm_providers` + 重建（开发环境假设，无历史数据）

---

### C2 + H6：spawn_sub_agent 超限问题（stalled 占位 + 竞态）

**问题**：`list_active_children` 不统计 stalled；check-then-create 无锁可并发超限。

**修复**：

1. `store/index_store.py`：`list_active_children` 过滤条件改为：
   ```python
   s.get("status") in ("active", "stalled")
   ```
2. `capabilities/tools/spawn_sub_agent/__init__.py`：
   - 模块级 `_SPAWN_LOCKS: dict[str, asyncio.Lock] = {}`
   - 辅助函数 `_get_lock(agent_type: str) -> asyncio.Lock`（按需创建，幂等）
   - 将 check（`list_active_children`）+ create（`session_store.create_session`）整块包在 `async with _get_lock(agent_type):` 内

---

### H1：删除 `_resolve_agent_path` 遗留逻辑

**问题**：用 `rpartition("_")` 剥离数字后缀，是 AgentPool/worker 命名的遗留，三层架构后 `assigned_agent` 直接是 `agent_type`。

**修复**：`core/task_manager.py`：
- 删除 `_resolve_agent_path` 方法
- 两处调用点（`submit` 和 `_transition`）直接使用 `task.assigned_agent`

---

### H2：删除废弃的 `/intervene` 路由

**问题**：`POST /sessions/{id}/intervene` 与 `POST /sessions/{id}/turns` 逻辑完全重复，保留了已废弃的"代答"语义。

**修复**：`gateway/routes/sessions.py`：删除 `intervene_session` handler 及对应 `@router.post` 装饰器（约 14 行）。

---

### H3：session_runner 捕获 CancelledError

**问题**：`except Exception` 捕获不到 `asyncio.CancelledError`（Python 3.9+），cancelled session 状态永不写入。

**修复**：`core/session_runner.py`：在 `except Exception` 之前插入：

```python
except asyncio.CancelledError:
    session.status = SessionStatus.CANCELLED
    raise  # finally 块负责持久化后继续传播
```

`finally` 块已有 `update_session` + `upsert`，无需额外改动。

---

### H4 + H5 + M4：Session 加 goal 字段 + 下游补全

**问题**：`Session` 无 `goal` 字段，`check_sub_agents` / `inspect_session` / `GET /recent` / stalled 事件均缺失 goal 信息。

**修复**：

1. `core/types.py`：`Session` 加 `goal: str = ""`
2. `store/session_store.py`：`create_session` 写 `meta.json` 时加 `goal` 字段；`get_session` 读取时映射 `goal`
3. 4 处 `Session(...)` 构造调用传入 `goal=content`：
   - `gateway/routes/sessions.py` `create_agent_session`
   - `capabilities/tools/delegate_to_agent/__init__.py`
   - `capabilities/tools/spawn_sub_agent/__init__.py`
   - `sebastian/orchestrator/sebas.py`（Sebastian 主会话）
4. `capabilities/tools/check_sub_agents/__init__.py`：输出加 `goal`、`last_activity_at`（从 index entry 读取，无需额外 IO）
5. `capabilities/tools/inspect_session/__init__.py`：输出加 `goal`（从 session 对象读取）
6. `gateway/routes/sessions.py` `get_session_recent`：响应 dict 加 `"goal": session.goal`
7. `core/stalled_watchdog.py`：`SESSION_STALLED` 事件 data 加 `"goal": session.goal`

---

## Batch 2 — 架构分层 + 中等问题

共 7 个问题（M8 / H9 / M1+M2 / M3 / M5 / M9 / M12）。

### M8：base_agent 消除反向依赖

**问题**：`core/base_agent.py._update_activity` 在运行时 `import sebastian.gateway.state`，core 层反向依赖 gateway 层。

**修复**：构造函数注入：

1. `BaseAgent.__init__` 新增 `index_store: IndexStore | None = None` 参数，存为 `self._index_store`
2. `_update_activity` 改为：
   ```python
   async def _update_activity(self, session_id: str) -> None:
       if self._index_store is not None:
           await self._index_store.update_activity(session_id)
   ```
3. `gateway/app.py` 或构造 agent 处传入 `index_store=state.index_store`
4. 测试构造 agent 不传 `index_store`，行为不变

---

### H9：per-agent LLM provider 路由

**问题**：`LLMProviderRegistry` 只有 `get_default()`，manifest `[llm]` 配置无法生效。

**修复**：`llm/registry.py` 加 `get_provider(agent_type: str | None = None) -> tuple[LLMProvider, str]`：

```python
async def get_provider(self, agent_type: str | None = None) -> tuple[LLMProvider, str]:
    if agent_type is not None:
        manifest_llm = _read_manifest_llm(agent_type)  # 读 agents/{agent_type}/manifest.toml [llm]
        if manifest_llm:
            provider_type = manifest_llm.get("provider_type")
            model = manifest_llm.get("model")
            if provider_type and model:
                record = await self._get_by_type(provider_type)  # 取该类型第一个 record
                if record:
                    return self._instantiate(record), model
    return await self.get_default_with_model()
```

`base_agent.py` 中 LLM 调用替换为 `llm_registry.get_provider(self.agent_type)`。

---

### M1 + M2：activity 写入一致性

**问题**：`IndexStore.update_activity` 只更新 `index.json`，重启后 meta.json 可能覆盖 stalled→active 状态。

**修复**：

1. `store/session_store.py` 新增 `update_activity(session_id: str, agent_type: str) -> None`：
   - 只读写 `meta.json` 中 `last_activity_at` + `status` 两个字段（不加载完整 Session）
2. `store/index_store.py`：`IndexStore.__init__` 新增 `session_store: SessionStore | None = None` 参数；`update_activity` 结尾调用 `await self._session_store.update_activity(session_id, agent_type)`（若注入了 session_store）
3. 构造 `IndexStore` 处传入 `session_store`

---

### M3：两条路径 session 状态管理对齐

**问题**：`_schedule_session_turn` 失败只 log，session 状态不更新（与 `run_agent_session` 不一致）。

**修复**：`gateway/routes/sessions.py`：`_schedule_session_turn` 改为注入 `session_store` + `index_store`，用 done callback 在失败时更新状态：

```python
def _make_turn_done_callback(session, session_store, index_store, event_bus):
    def _cb(task):
        if task.cancelled():
            session.status = SessionStatus.CANCELLED
        elif task.exception():
            session.status = SessionStatus.FAILED
        else:
            return
        asyncio.create_task(_persist_session_status(session, session_store, index_store, event_bus))
    return _cb
```

正常完成（无 exception）不改状态，session 保持 active 等下一轮用户输入。

---

### M5：utcnow 已废弃

`store/models.py`：`datetime.utcnow` → `lambda: datetime.now(UTC)`（已在 C1 修复中一并处理）。

---

### M9：create_task 返回值未保存

`gateway/routes/sessions.py` `create_agent_session`：

```python
task = asyncio.create_task(run_agent_session(...))
task.add_done_callback(_log_background_turn_failure)
```

---

### M12：删除多余 agent_name kwarg

`gateway/routes/sessions.py` `_schedule_session_turn`：删除 `agent_name=session.agent_type` 参数。确认 `BaseAgent.run_streaming` 签名不含此参数。

---

## Batch 3 — 前端修复

共 5 个问题（C3 / H7 / H8 / M6 / M7）。

### C3：handleSend 双击竞态

`ui/mobile/app/subagents/session/[id].tsx`：

- 新增 `sendingRef = useRef(false)`
- `handleSend` 开头：`if (sendingRef.current) return; sendingRef.current = true;`
- `finally` 块：`sendingRef.current = false;`
- `setSending` 保留用于 UI 按钮禁用状态

---

### H7：AgentList item.goal → item.description

`ui/mobile/src/components/subagents/AgentList.tsx:31`：`item.goal` → `item.description`。

---

### H8：createAgentSession 后补 setRealSessionId

`ui/mobile/app/subagents/session/[id].tsx`：

```tsx
const newId = await createAgentSession(agentType, text);
setRealSessionId(newId);  // 补上
router.replace(`/subagents/session/${newId}?agent=${agentType}`);
```

---

### M6：StatusBadge 加 stalled 颜色 + 类型扩展

`ui/mobile/src/components/common/StatusBadge.tsx`：

- COLOR 映射加 `stalled: '#F59E0B'`
- Props 类型改为 `AgentStatus | TaskStatus | SessionMeta['status']`

---

### M7：AppSidebar FAB disabled 补完

`ui/mobile/src/components/chat/AppSidebar.tsx:105`：

```tsx
disabled={!!draftSession || !currentSessionId}
```

---

## Batch 4 — 测试 + 清理

共 8 个问题（C4 / M10 / M11 / H10 / L1 / L2 / L3 / L4）。

### C4：stalled_watchdog 补测试

`tests/unit/test_stalled_watchdog.py` 新增 5 个测试用例：

1. `completed` session 不被误标（status != active 跳过）
2. 阈值边界下边（`threshold - 1s`）→ 不标
3. 阈值边界上边（`threshold + 1s`）→ 标
4. `last_activity_at` 为空字符串 → 跳过，不报错
5. `session_store.get_session` 返回 None → 跳过；`index_store.upsert` 验证被调用

---

### M10：test_tool_delegate 补测试

`tests/unit/test_tool_delegate.py` 新增：

1. `agent_type` 不在 registry → 返回 `ToolResult(ok=False)`
2. 成功路径：`asyncio.create_task` 被调用（patch `asyncio.create_task` 验证）

---

### M11：test_session_store_paths 补测试

`tests/unit/test_session_store_paths.py` 新增：

1. `depth=3` session 路径格式：`sessions/{agent_type}/{session_id}/`
2. `depth=3` 的 `parent_session_id` 写入 `meta.json` 后可读回
3. `depth=1`（Sebastian）路径格式：`sessions/sebastian/{session_id}/`

---

### H10：集成测试环境变量隔离

`tests/integration/test_gateway_turns.py` + `test_gateway_sessions.py`：

- 删除模块顶层 `os.environ.setdefault` 和 `importlib.reload`
- `tests/conftest.py` 加 autouse fixture：

```python
@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SEBASTIAN_JWT_SECRET", "test-secret")
    monkeypatch.setenv("SEBASTIAN_ENCRYPTION_KEY", Fernet.generate_key().decode())
```

---

### L1：cancel_task 按 session 路由

`gateway/routes/sessions.py` cancel 端点按 `session.agent_type` 找 agent 的 task_manager：

```python
if session.agent_type == "sebastian":
    manager = state.sebastian._task_manager
else:
    agent = state.agent_instances.get(session.agent_type)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    manager = agent._task_manager
```

---

### L2：删除 ARCHIVED 状态

- `core/types.py`：删 `SessionStatus.ARCHIVED = "archived"`
- `ui/mobile/src/types.ts`：`SessionMeta.status` 联合类型删 `'archived'`

---

### L3：README 更新

- `sebastian/protocol/a2a/README.md`：清空 A2ADispatcher/DelegateTask/EscalateRequest 描述，改为说明该目录保留 types.py 仅作历史参考，Agent 间通信已改为直接调用 + event bus
- `sebastian/orchestrator/README.md`：删除 `intervene()`、`A2ADispatcher.delegate()` 引用

---

### L4：EventBus 测试隔离

`protocol/events/bus.py`：`EventBus` 加 `reset() -> None` 方法，清空 `_handlers`。

`tests/conftest.py` 加：

```python
@pytest.fixture(autouse=True)
def _reset_event_bus():
    yield
    from sebastian.protocol.events.bus import bus
    bus.reset()
```

---

## 文件改动汇总

### Batch 1（后端）

| 文件 | 操作 |
|------|------|
| `pyproject.toml` | 加 `cryptography` 依赖 |
| `sebastian/llm/crypto.py` | **新建** Fernet 加密工具 |
| `sebastian/config.py` | 加 `encryption_key` 字段 |
| `store/models.py` | `api_key` → `api_key_enc`，修 utcnow（含 M5） |
| `llm/registry.py` | 加密/解密调用 |
| `gateway/routes/llm_providers.py` | 移除 GET 响应中的密钥字段 |
| `store/index_store.py` | `list_active_children` 加 stalled |
| `capabilities/tools/spawn_sub_agent/__init__.py` | 加锁 |
| `core/task_manager.py` | 删 `_resolve_agent_path` |
| `gateway/routes/sessions.py` | 删 intervene 端点 |
| `core/session_runner.py` | 捕获 CancelledError |
| `core/types.py` | `Session` 加 `goal` |
| `store/session_store.py` | meta.json 读写加 `goal` |
| 4 处 Session 构造调用 | 传 `goal=content` |
| `check_sub_agents/__init__.py` | 输出加 goal / last_activity_at |
| `inspect_session/__init__.py` | 输出加 goal |
| `gateway/routes/sessions.py` GET /recent | 加 goal |
| `core/stalled_watchdog.py` | 事件加 goal |

### Batch 2（架构）

| 文件 | 操作 |
|------|------|
| `core/base_agent.py` | 注入 index_store，删 runtime import |
| `llm/registry.py` | 加 `get_provider(agent_type?)` |
| `store/session_store.py` | 加 `update_activity` 轻量方法 |
| `store/index_store.py` | 注入 session_store，`update_activity` 同步写 meta |
| `gateway/routes/sessions.py` | `_schedule_session_turn` 加 done callback |
| `gateway/routes/sessions.py` | `create_agent_session` 保存 task |
| `gateway/routes/sessions.py` | 删 `agent_name` kwarg |

### Batch 3（前端）

| 文件 | 操作 |
|------|------|
| `app/subagents/session/[id].tsx` | sendingRef + setRealSessionId |
| `src/components/subagents/AgentList.tsx` | goal → description |
| `src/components/common/StatusBadge.tsx` | 加 stalled 颜色 + 类型 |
| `src/components/chat/AppSidebar.tsx` | FAB disabled 补全 |

### Batch 4（测试 + 清理）

| 文件 | 操作 |
|------|------|
| `tests/unit/test_stalled_watchdog.py` | 补 5 个测试 |
| `tests/unit/test_tool_delegate.py` | 补 2 个测试 |
| `tests/unit/test_session_store_paths.py` | 补 3 个测试 |
| `tests/conftest.py` | env patch + bus reset fixture |
| `tests/integration/test_gateway_*.py` | 删模块顶层 setdefault |
| `gateway/routes/sessions.py` | cancel_task 路由修复 |
| `core/types.py` | 删 ARCHIVED |
| `src/types.ts` | 删 archived |
| `protocol/events/bus.py` | 加 reset() |
| `sebastian/protocol/a2a/README.md` | 更新 |
| `sebastian/orchestrator/README.md` | 更新 |
