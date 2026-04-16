# allowed_tools 白名单强制生效 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让子代理 `manifest.toml` 的 `allowed_tools` 白名单在 LLM 可见性层和执行校验层都真正生效。

**Architecture:** 两层强制边界。(1) LLM 可见性层：`AgentLoop` 存储 `allowed_tools/allowed_skills`，通过新增的 `PolicyGate.get_callable_specs()` 过滤传给 LLM 的 `tools` 列表（同时保留 MODEL_DECIDES 的 `reason` 字段注入）。(2) 执行校验层：`ToolCallContext` 新增 `allowed_tools` 字段，`PolicyGate.call()` Stage 0 前置校验，防止 LLM 幻觉工具名绕过。

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-04-15-allowed-tools-whitelist-enforcement-design.md`

---

## 文件改动概览

**修改**：
- `sebastian/core/protocols.py` — `ToolSpecProvider` 协议补 `get_callable_specs`
- `sebastian/permissions/types.py` — `ToolCallContext` 加 `allowed_tools` 字段
- `sebastian/permissions/gate.py` — 新增 `get_callable_specs()`，`call()` Stage 0 白名单校验
- `sebastian/core/agent_loop.py` — `AgentLoop` 接受并使用 `allowed_tools/allowed_skills`
- `sebastian/core/base_agent.py` — 向下透传白名单给 `AgentLoop` 和 `ToolCallContext`
- `sebastian/orchestrator/sebas.py` — `allowed_tools` 补 `reply_to_agent`
- `sebastian/agents/README.md` — 文档化三种语义 + 协议工具对比
- `docs/architecture/spec/agents/permission.md` — 更新"工具可见性"与审批流

**测试**：
- `tests/unit/identity/test_policy_gate.py` — Stage 0 白名单校验 + `get_callable_specs` 过滤
- `tests/unit/core/test_agent_loop.py` — LLM 可见性过滤
- `tests/unit/agents/test_agent_loader.py`（或 `test_agents_loader.py`） — 三种语义
- `tests/unit/runtime/test_sebas.py` — Sebastian `allowed_tools` 含 `reply_to_agent`

---

## Task 1: 给 `ToolCallContext` 加 `allowed_tools` 字段

**Files:**
- Modify: `sebastian/permissions/types.py`

- [ ] **Step 1: 修改 `ToolCallContext`**

在 `sebastian/permissions/types.py` 的 `ToolCallContext` dataclass 里新增 `allowed_tools` 字段，放在 `progress_cb` 之前：

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class PermissionTier(StrEnum):
    LOW = "low"
    MODEL_DECIDES = "model_decides"
    HIGH_RISK = "high_risk"


@dataclass
class ToolCallContext:
    task_goal: str
    session_id: str
    task_id: str | None
    agent_type: str = ""
    depth: int = 1
    allowed_tools: frozenset[str] | None = None
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]] | None = field(
        default=None, repr=False
    )


@dataclass
class ReviewDecision:
    decision: Literal["proceed", "escalate"]
    explanation: str
```

- [ ] **Step 2: 验证类型检查通过**

Run: `mypy sebastian/permissions/types.py`
Expected: `Success: no issues found`

- [ ] **Step 3: 跑回归测试确认没破坏现有调用**

Run: `pytest tests/unit/identity/test_policy_gate.py -v`
Expected: 全部 PASS（现有测试不显式传 `allowed_tools`，默认 `None`，行为不变）

- [ ] **Step 4: Commit**

```bash
git add sebastian/permissions/types.py
git commit -m "$(cat <<'EOF'
feat(permissions): ToolCallContext 新增 allowed_tools 字段

为后续 PolicyGate Stage 0 白名单校验铺路。默认 None 表示不限制。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `ToolSpecProvider` 协议补 `get_callable_specs`

**Files:**
- Modify: `sebastian/core/protocols.py`

- [ ] **Step 1: 修改协议声明**

把 `sebastian/core/protocols.py` 的 `ToolSpecProvider` 改为：

```python
# sebastian/core/protocols.py
from __future__ import annotations

from typing import Any, Protocol


class ApprovalManagerProtocol(Protocol):
    """Protocol satisfied by ConversationManager without explicit inheritance."""

    async def request_approval(
        self,
        approval_id: str,
        task_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        session_id: str = "",
        agent_type: str = "",
    ) -> bool: ...


class ToolSpecProvider(Protocol):
    """Protocol for any object that can provide tool specs. Satisfied by both
    CapabilityRegistry (tests/legacy) and PolicyGate (production)."""

    def get_all_tool_specs(self) -> list[dict[str, Any]]: ...

    def get_callable_specs(
        self,
        allowed_tools: set[str] | None = None,
        allowed_skills: set[str] | None = None,
    ) -> list[dict[str, Any]]: ...
```

- [ ] **Step 2: 验证 mypy 通过**

Run: `mypy sebastian/core/protocols.py`
Expected: `Success: no issues found`

注：此时 `PolicyGate` 还没有 `get_callable_specs`，但 `mypy` 对 Protocol 是 structural typing，已有调用点还没用新方法，所以不会失败。若 mypy 报错指出 `PolicyGate` 缺少 `get_callable_specs`，忽略即可，Task 3 会补上。

- [ ] **Step 3: Commit**

```bash
git add sebastian/core/protocols.py
git commit -m "$(cat <<'EOF'
feat(core): ToolSpecProvider 协议补 get_callable_specs

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `PolicyGate` 新增 `get_callable_specs()`（TDD）

**Files:**
- Test: `tests/unit/identity/test_policy_gate.py`
- Modify: `sebastian/permissions/gate.py`

- [ ] **Step 1: 写失败的单测**

在 `tests/unit/identity/test_policy_gate.py` 末尾追加：

```python
from sebastian.permissions.gate import PolicyGate


def _make_gate_with_specs(
    native_specs: list[dict],
    tool_tiers: dict[str, PermissionTier],
) -> "PolicyGate":
    """构造一个 PolicyGate，注入 registry 返回指定 native_specs。"""
    registry = MagicMock()
    registry.get_callable_specs = MagicMock(
        side_effect=lambda allowed_tools, allowed_skills: [
            spec for spec in native_specs
            if allowed_tools is None or spec["name"] in allowed_tools
        ]
    )
    reviewer = MagicMock()
    approval_manager = MagicMock()
    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)
    return gate


def test_get_callable_specs_filters_by_allowed_tools() -> None:
    """给定 allowed_tools={'Read'}，只返回 Read 的 spec。"""
    specs = [
        {"name": "Read", "description": "read", "input_schema": {"properties": {}}},
        {"name": "Bash", "description": "bash", "input_schema": {"properties": {}}},
    ]
    gate = _make_gate_with_specs(specs, {})

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = gate.get_callable_specs(allowed_tools={"Read"}, allowed_skills=None)

    names = [s["name"] for s in result]
    assert names == ["Read"]


def test_get_callable_specs_injects_reason_for_model_decides() -> None:
    """MODEL_DECIDES tier 的工具 spec 应被注入 required 的 reason 字段。"""
    specs = [
        {
            "name": "Bash",
            "description": "bash",
            "input_schema": {"properties": {"command": {"type": "string"}}, "required": ["command"]},
        },
    ]
    gate = _make_gate_with_specs(specs, {})

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.MODEL_DECIDES
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = gate.get_callable_specs(allowed_tools=None, allowed_skills=None)

    assert len(result) == 1
    schema = result[0]["input_schema"]
    assert "reason" in schema["properties"]
    assert "reason" in schema["required"]


def test_get_all_tool_specs_still_works_as_shim() -> None:
    """get_all_tool_specs() 调用 get_callable_specs(None, None)，行为保持不变。"""
    specs = [
        {"name": "Read", "description": "read", "input_schema": {"properties": {}}},
    ]
    gate = _make_gate_with_specs(specs, {})

    with patch("sebastian.permissions.gate.get_tool") as mock_get_tool:
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = gate.get_all_tool_specs()

    assert [s["name"] for s in result] == ["Read"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/identity/test_policy_gate.py::test_get_callable_specs_filters_by_allowed_tools tests/unit/identity/test_policy_gate.py::test_get_callable_specs_injects_reason_for_model_decides tests/unit/identity/test_policy_gate.py::test_get_all_tool_specs_still_works_as_shim -v`

Expected: FAIL — `AttributeError: 'PolicyGate' object has no attribute 'get_callable_specs'`

- [ ] **Step 3: 在 `PolicyGate` 实现 `get_callable_specs()` 并把 `get_all_tool_specs()` 改成 shim**

修改 `sebastian/permissions/gate.py`：

把现有的 `get_all_tool_specs` 方法（约 `gate.py:107-129`）替换为下面两段（保持文件其余部分不变）：

```python
    def get_callable_specs(
        self,
        allowed_tools: set[str] | None = None,
        allowed_skills: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Filtered tool+skill specs for LLM API calls.

        For MODEL_DECIDES tools (including unrecognised MCP tools), inject
        a required `reason` field so the LLM must state its intent.
        """
        specs: list[dict[str, Any]] = []
        for spec_dict in self._registry.get_callable_specs(allowed_tools, allowed_skills):
            tool_name = spec_dict["name"]
            native = get_tool(tool_name)
            tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES

            if tier == PermissionTier.MODEL_DECIDES:
                spec_dict = copy.deepcopy(spec_dict)
                schema = spec_dict.setdefault("input_schema", {})
                props = schema.setdefault("properties", {})
                required: list[str] = schema.setdefault("required", [])
                props["reason"] = _REASON_SCHEMA
                if "reason" not in required:
                    required.append("reason")

            specs.append(spec_dict)
        return specs

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Backward-compat shim for ToolSpecProvider protocol."""
        return self.get_callable_specs(None, None)
```

- [ ] **Step 4: 运行新测试确认通过**

Run: `pytest tests/unit/identity/test_policy_gate.py::test_get_callable_specs_filters_by_allowed_tools tests/unit/identity/test_policy_gate.py::test_get_callable_specs_injects_reason_for_model_decides tests/unit/identity/test_policy_gate.py::test_get_all_tool_specs_still_works_as_shim -v`

Expected: 3 passed

- [ ] **Step 5: 跑全量 policy_gate 回归**

Run: `pytest tests/unit/identity/test_policy_gate.py -v`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add sebastian/permissions/gate.py tests/unit/identity/test_policy_gate.py
git commit -m "$(cat <<'EOF'
feat(permissions): PolicyGate 新增 get_callable_specs 支持白名单过滤

- 过滤 allowed_tools/allowed_skills，同时保留 MODEL_DECIDES 的 reason 注入
- get_all_tool_specs 改为 shim，调用 get_callable_specs(None, None)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `AgentLoop` 接受并使用白名单（TDD）

**Files:**
- Test: `tests/unit/core/test_agent_loop.py`
- Modify: `sebastian/core/agent_loop.py`

- [ ] **Step 1: 写失败的单测**

在 `tests/unit/core/test_agent_loop.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_agent_loop_passes_allowed_tools_to_provider() -> None:
    """AgentLoop 存储的 allowed_tools 应传给 registry.get_callable_specs，
    过滤后的 tools 传给 provider.stream。"""
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    registry = MagicMock()
    registry.get_callable_specs = MagicMock(
        return_value=[{"name": "Read", "description": "read", "input_schema": {}}]
    )

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextBlockStop(block_id="b0_0", text="ok"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )
    captured_tools: list[Any] = []
    original_stream = provider.stream

    async def spy_stream(**kwargs: Any) -> Any:
        captured_tools.append(kwargs["tools"])
        async for event in original_stream(**kwargs):
            yield event

    provider.stream = spy_stream  # type: ignore[method-assign]

    loop = AgentLoop(
        provider,
        registry,
        model="test",
        allowed_tools={"Read"},
        allowed_skills=None,
    )
    await _collect(loop.stream(system_prompt="s", messages=[{"role": "user", "content": "hi"}]))

    registry.get_callable_specs.assert_called_once_with(
        allowed_tools={"Read"}, allowed_skills=None
    )
    assert captured_tools == [[{"name": "Read", "description": "read", "input_schema": {}}]]


@pytest.mark.asyncio
async def test_agent_loop_none_allowed_tools_means_unrestricted() -> None:
    """allowed_tools=None 表示不限制，registry 收到 None。"""
    from unittest.mock import MagicMock

    from sebastian.core.agent_loop import AgentLoop

    registry = MagicMock()
    registry.get_callable_specs = MagicMock(return_value=[])

    provider = MockLLMProvider(
        [
            TextBlockStart(block_id="b0_0"),
            TextBlockStop(block_id="b0_0", text="ok"),
            ProviderCallEnd(stop_reason="end_turn"),
        ]
    )

    loop = AgentLoop(provider, registry, model="test")
    await _collect(loop.stream(system_prompt="s", messages=[{"role": "user", "content": "hi"}]))

    registry.get_callable_specs.assert_called_once_with(allowed_tools=None, allowed_skills=None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/core/test_agent_loop.py::test_agent_loop_passes_allowed_tools_to_provider tests/unit/core/test_agent_loop.py::test_agent_loop_none_allowed_tools_means_unrestricted -v`

Expected: FAIL（`AgentLoop.__init__` 不接受 `allowed_tools`，或 `get_all_tool_specs` 被调用而不是 `get_callable_specs`）

- [ ] **Step 3: 修改 `AgentLoop`**

修改 `sebastian/core/agent_loop.py`：

`__init__` 增加两个参数：

```python
    def __init__(
        self,
        provider: LLMProvider | None,
        tool_provider: ToolSpecProvider,
        model: str = "claude-opus-4-6",
        max_tokens: int | None = None,
        allowed_tools: set[str] | None = None,
        allowed_skills: set[str] | None = None,
    ) -> None:
        self._provider = provider
        self._registry = tool_provider
        self._model = model
        self._allowed_tools = allowed_tools
        self._allowed_skills = allowed_skills
        if max_tokens is not None:
            self._max_tokens = max_tokens
        else:
            from sebastian.config import settings

            self._max_tokens = settings.llm_max_tokens
```

然后把 `stream()` 方法里第 101 行：

```python
        tools = self._registry.get_all_tool_specs()
```

改为：

```python
        tools = self._registry.get_callable_specs(
            allowed_tools=self._allowed_tools,
            allowed_skills=self._allowed_skills,
        )
```

- [ ] **Step 4: 运行新测试确认通过**

Run: `pytest tests/unit/core/test_agent_loop.py::test_agent_loop_passes_allowed_tools_to_provider tests/unit/core/test_agent_loop.py::test_agent_loop_none_allowed_tools_means_unrestricted -v`
Expected: 2 passed

- [ ] **Step 5: 跑 agent_loop 全量回归**

Run: `pytest tests/unit/core/test_agent_loop.py -v`
Expected: 全绿（现有测试未显式传 `allowed_tools`，默认 `None`，`get_callable_specs(None, None)` 等价于旧的 `get_all_tool_specs()`。但若现有测试用的是 `CapabilityRegistry`，需要确认它有 `get_callable_specs` 方法——从 `sebastian/capabilities/registry.py:55` 看已经有了，没问题）

- [ ] **Step 6: Commit**

```bash
git add sebastian/core/agent_loop.py tests/unit/core/test_agent_loop.py
git commit -m "$(cat <<'EOF'
feat(core): AgentLoop 按 allowed_tools/allowed_skills 过滤传给 LLM 的 tools

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `BaseAgent` 向下透传白名单

**Files:**
- Modify: `sebastian/core/base_agent.py`

- [ ] **Step 1: 在 `BaseAgent.__init__` 构造 `AgentLoop` 时透传**

打开 `sebastian/core/base_agent.py`，找到 `__init__` 末尾构造 `AgentLoop` 的代码块（约 `base_agent.py:132-136`）：

```python
        self._loop = AgentLoop(
            provider,
            gate,
            resolved_model,
        )
```

改为：

```python
        self._loop = AgentLoop(
            provider,
            gate,
            resolved_model,
            allowed_tools=(
                set(self.allowed_tools) if self.allowed_tools is not None else None
            ),
            allowed_skills=(
                set(self.allowed_skills) if self.allowed_skills is not None else None
            ),
        )
```

注意：`self.allowed_tools` 在此之前已经由 `__init__` 的 instance-level overrides 赋值（`base_agent.py:124-127`），所以这里拿到的就是最终值。

- [ ] **Step 2: 在 `_stream_inner` 创建 `ToolCallContext` 时填入白名单**

在 `sebastian/core/base_agent.py` 的 `_stream_inner` 里找到创建 `ToolCallContext` 的代码（约 `base_agent.py:447-457`）：

```python
                        context = ToolCallContext(
                            task_goal=self._current_task_goals.get(session_id, ""),
                            session_id=session_id,
                            task_id=task_id,
                            agent_type=agent_context,
                            depth=getattr(self, "_current_depth", {}).get(session_id, 1),
                            progress_cb=functools.partial(
                                self._publish, session_id, EventType.TOOL_RUNNING
                            ),
                        )
```

增加 `allowed_tools` 字段（放在 `progress_cb` 之前）：

```python
                        context = ToolCallContext(
                            task_goal=self._current_task_goals.get(session_id, ""),
                            session_id=session_id,
                            task_id=task_id,
                            agent_type=agent_context,
                            depth=getattr(self, "_current_depth", {}).get(session_id, 1),
                            allowed_tools=(
                                frozenset(self.allowed_tools)
                                if self.allowed_tools is not None
                                else None
                            ),
                            progress_cb=functools.partial(
                                self._publish, session_id, EventType.TOOL_RUNNING
                            ),
                        )
```

- [ ] **Step 3: 回归测试**

Run: `pytest tests/unit/core/test_base_agent_provider.py tests/unit/runtime/test_sebas.py -v`
Expected: 全绿（现有测试不检查 `context.allowed_tools`，只验证 `call` 被调用，所以字段增加不破坏）

- [ ] **Step 4: Commit**

```bash
git add sebastian/core/base_agent.py
git commit -m "$(cat <<'EOF'
feat(core): BaseAgent 向 AgentLoop 和 ToolCallContext 透传 allowed_tools

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `PolicyGate.call()` Stage 0 白名单校验（TDD）

**Files:**
- Test: `tests/unit/identity/test_policy_gate.py`
- Modify: `sebastian/permissions/gate.py`

- [ ] **Step 1: 写失败的单测**

在 `tests/unit/identity/test_policy_gate.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_call_rejects_tool_outside_allowed_tools() -> None:
    """context.allowed_tools 限制外的工具应被 Stage 0 拒绝，不到 registry。"""
    from sebastian.permissions.gate import PolicyGate

    registry = MagicMock()
    registry.call = AsyncMock()
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    context = ToolCallContext(
        task_goal="test",
        session_id="s1",
        task_id="t1",
        agent_type="forge",
        depth=2,
        allowed_tools=frozenset({"Read"}),
    )

    result = await gate.call("Bash", {"command": "ls"}, context)

    assert result.ok is False
    assert "'Bash'" in (result.error or "")
    assert "'forge'" in (result.error or "")
    registry.call.assert_not_awaited()
    reviewer.review.assert_not_called() if hasattr(reviewer, "review") else None
    approval_manager.request_approval.assert_not_called() if hasattr(
        approval_manager, "request_approval"
    ) else None


@pytest.mark.asyncio
async def test_call_allows_tool_inside_allowed_tools(tmp_path) -> None:
    """白名单内的工具应通过 Stage 0，正常走后续流程。"""
    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "notes.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    context = ToolCallContext(
        task_goal="test",
        session_id="s1",
        task_id="t1",
        agent_type="forge",
        depth=2,
        allowed_tools=frozenset({"file_read"}),
    )

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=inside_path),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("file_read", {"path": str(inside_path)}, context)

    assert result.ok
    registry.call.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_none_allowed_tools_means_unrestricted(tmp_path) -> None:
    """context.allowed_tools=None 表示不限制，任意合法工具可调用（回归）。"""
    from sebastian.permissions.gate import PolicyGate

    inside_path = tmp_path / "notes.txt"

    registry = MagicMock()
    registry.call = AsyncMock(return_value=ToolResult(ok=True, output="ok"))
    reviewer = MagicMock()
    approval_manager = MagicMock()

    gate = PolicyGate(registry=registry, reviewer=reviewer, approval_manager=approval_manager)

    context = ToolCallContext(
        task_goal="test",
        session_id="s1",
        task_id="t1",
        agent_type="forge",
        depth=2,
        allowed_tools=None,
    )

    with (
        patch("sebastian.permissions.gate.get_tool") as mock_get_tool,
        patch("sebastian.permissions.gate.resolve_path", return_value=inside_path),
        patch("sebastian.permissions.gate.settings") as mock_settings,
    ):
        mock_settings.workspace_dir = tmp_path
        mock_spec = MagicMock()
        mock_spec.permission_tier = PermissionTier.LOW
        mock_get_tool.return_value = (mock_spec, MagicMock())

        result = await gate.call("file_read", {"path": str(inside_path)}, context)

    assert result.ok
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/identity/test_policy_gate.py::test_call_rejects_tool_outside_allowed_tools -v`
Expected: FAIL — `registry.call` 被 awaited（因为 Stage 0 还没加），或返回 ok=True

- [ ] **Step 3: 在 `PolicyGate.call()` 开头加 Stage 0**

修改 `sebastian/permissions/gate.py` 的 `call` 方法（约 `gate.py:131-168`）。当前结构：

```python
    async def call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult:
        """Execute a tool after enforcing its permission tier."""
        native = get_tool(tool_name)
        tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES

        token = _current_tool_ctx.set(context)
        try:
            # Stage 1: 路径规范化...
            ...
```

改为：

```python
    async def call(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ToolCallContext,
    ) -> ToolResult:
        """Execute a tool after enforcing its permission tier."""
        # Stage 0: allowed_tools 白名单校验
        # 防止 LLM 幻觉工具名绕过 LLM 可见性层的过滤。
        if context.allowed_tools is not None and tool_name not in context.allowed_tools:
            return ToolResult(
                ok=False,
                error=(
                    f"Tool {tool_name!r} not in allowed_tools for agent "
                    f"{context.agent_type!r}"
                ),
            )

        native = get_tool(tool_name)
        tier = native[0].permission_tier if native else PermissionTier.MODEL_DECIDES

        token = _current_tool_ctx.set(context)
        try:
            # Stage 1: 路径规范化...
            ...
```

同时更新该方法的 docstring 里的"审批流顺序"注释块（在 `PolicyGate` 类 docstring `gate.py:73-83`），在列表最前面加一条 Stage 0：

```python
    审批流顺序
    ----------
    0. agent 身份白名单校验（所有 tier）：context.allowed_tools 非 None 且
       tool_name 不在其中 → 立即返回错误，不执行工具。
    1. Workspace 边界检查（所有 tier）：含 file_path/path 参数且路径在 workspace 外
       → 直接请求用户审批。
    2. LOW tier：直接执行。
    ... (其余保持不变)
```

- [ ] **Step 4: 运行新测试确认通过**

Run: `pytest tests/unit/identity/test_policy_gate.py::test_call_rejects_tool_outside_allowed_tools tests/unit/identity/test_policy_gate.py::test_call_allows_tool_inside_allowed_tools tests/unit/identity/test_policy_gate.py::test_call_none_allowed_tools_means_unrestricted -v`
Expected: 3 passed

- [ ] **Step 5: 跑 policy_gate 全量 + 集成回归**

Run: `pytest tests/unit/identity/test_policy_gate.py tests/integration/flows/test_permission_flow.py -v`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add sebastian/permissions/gate.py tests/unit/identity/test_policy_gate.py
git commit -m "$(cat <<'EOF'
feat(permissions): PolicyGate.call Stage 0 agent 身份白名单校验

防止 LLM 幻觉出白名单外的工具名绕过 LLM 可见性层的过滤。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Sebastian 补 `reply_to_agent`（TDD）

**Files:**
- Test: `tests/unit/runtime/test_sebas.py`
- Modify: `sebastian/orchestrator/sebas.py`

- [ ] **Step 1: 写失败的单测**

在 `tests/unit/runtime/test_sebas.py` 末尾追加（如果文件没有的 import，按文件里现有风格处理）：

```python
def test_sebastian_allowed_tools_includes_reply_to_agent() -> None:
    """Sebastian 作为主管家，需要 reply_to_agent 来回复组长的 ask_parent。"""
    from sebastian.orchestrator.sebas import Sebastian

    assert Sebastian.allowed_tools is not None
    assert "reply_to_agent" in Sebastian.allowed_tools
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/runtime/test_sebas.py::test_sebastian_allowed_tools_includes_reply_to_agent -v`
Expected: FAIL — `'reply_to_agent' not in Sebastian.allowed_tools`

- [ ] **Step 3: 修改 `Sebastian.allowed_tools`**

修改 `sebastian/orchestrator/sebas.py` 的类属性（约 `sebas.py:83-97`）：

```python
    # Orchestrator-scope tools. 包含 reply_to_agent：用于回复组长通过 ask_parent
    # 向 Sebastian 发起的请示。不含 spawn_sub_agent / ask_parent：前者由
    # delegate_to_agent 承担，后者因 Sebastian 无上级。
    allowed_tools = [
        "delegate_to_agent",
        "check_sub_agents",
        "inspect_session",
        "reply_to_agent",
        "todo_write",
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
    ]
```

- [ ] **Step 4: 运行新测试确认通过**

Run: `pytest tests/unit/runtime/test_sebas.py::test_sebastian_allowed_tools_includes_reply_to_agent -v`
Expected: PASS

- [ ] **Step 5: 跑 sebas 全量回归**

Run: `pytest tests/unit/runtime/test_sebas.py -v`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add sebastian/orchestrator/sebas.py tests/unit/runtime/test_sebas.py
git commit -m "$(cat <<'EOF'
fix(orchestrator): Sebastian 补 reply_to_agent 白名单

白名单真正生效后 Sebastian 需要显式声明 reply_to_agent，
才能响应组长的 ask_parent 请示。

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `_loader.py` 三种语义单测补齐（TDD）

**Files:**
- Test: `tests/unit/agents/test_agents_loader.py`

先确认哪个 loader 测试文件是活的：

```bash
head -5 tests/unit/agents/test_agent_loader.py tests/unit/agents/test_agents_loader.py
```

（两个文件里用更新的那个，或挑文件命名与现仓库主流一致的那个。）

- [ ] **Step 1: 读已有 loader 测试判断哪个是主文件**

Run: `head -40 tests/unit/agents/test_agent_loader.py`
Run: `head -40 tests/unit/agents/test_agents_loader.py`

挑活的那个（或更新的那个）继续；下文以 `test_agents_loader.py` 为准，实际改文件名对齐仓库现状。

- [ ] **Step 2: 写三种语义的单测**

在选定的 loader 测试文件末尾追加：

```python
import tomllib  # noqa: F401 — 若已 import 则忽略
from pathlib import Path
from textwrap import dedent


def _write_agent(tmp_path: Path, agent_name: str, toml_body: str) -> Path:
    """在 tmp_path 下造一个最小 agent 目录，返回父目录。"""
    agent_dir = tmp_path / agent_name
    agent_dir.mkdir()
    (agent_dir / "manifest.toml").write_text(toml_body)
    (agent_dir / "__init__.py").write_text(
        "from sebastian.core.base_agent import BaseAgent\n"
        f"class {agent_name.title()}Agent(BaseAgent):\n"
        "    pass\n"
    )
    return tmp_path


PROTOCOL_TOOLS = {
    "ask_parent",
    "reply_to_agent",
    "spawn_sub_agent",
    "check_sub_agents",
    "inspect_session",
}


def test_allowed_tools_unset_stays_none(tmp_path: Path) -> None:
    """未声明 allowed_tools → final 为 None（不限制）。"""
    from sebastian.agents._loader import load_agents

    _write_agent(
        tmp_path,
        "noscope",
        dedent(
            """
            [agent]
            class_name = "NoscopeAgent"
            description = "no scope"
            """
        ),
    )
    configs = {c.agent_type: c for c in load_agents(extra_dirs=[tmp_path])}
    assert configs["noscope"].allowed_tools is None


def test_allowed_tools_empty_list_injects_protocol_only(tmp_path: Path) -> None:
    """allowed_tools=[] → final 恰好等于 5 个协议工具。"""
    from sebastian.agents._loader import load_agents

    _write_agent(
        tmp_path,
        "minimal",
        dedent(
            """
            [agent]
            class_name = "MinimalAgent"
            description = "minimal"
            allowed_tools = []
            """
        ),
    )
    configs = {c.agent_type: c for c in load_agents(extra_dirs=[tmp_path])}
    final = configs["minimal"].allowed_tools
    assert final is not None
    assert set(final) == PROTOCOL_TOOLS


def test_allowed_tools_list_appends_protocol(tmp_path: Path) -> None:
    """allowed_tools=['Read'] → final 为 Read + 5 个协议工具，无重复。"""
    from sebastian.agents._loader import load_agents

    _write_agent(
        tmp_path,
        "reader",
        dedent(
            """
            [agent]
            class_name = "ReaderAgent"
            description = "reader"
            allowed_tools = ["Read"]
            """
        ),
    )
    configs = {c.agent_type: c for c in load_agents(extra_dirs=[tmp_path])}
    final = configs["reader"].allowed_tools
    assert final is not None
    assert set(final) == {"Read"} | PROTOCOL_TOOLS
    assert len(final) == len(set(final))  # 无重复
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/unit/agents/test_agents_loader.py -v` （对应活文件）
Expected: 3 个新测试全部 PASS（`_loader.py` 现有逻辑已经实现这三种语义，本 task 只是用测试固化行为）

若有 FAIL：
- 若 FAIL 是因为 test fixture 构造 agent 模块的方式与当前 loader 不兼容，参考已有通过的 loader 测试对齐 fixture 写法，不要改 `_loader.py` 实现逻辑。

- [ ] **Step 4: Commit**

```bash
git add tests/unit/agents/test_agents_loader.py
git commit -m "$(cat <<'EOF'
test(agents): 固化 allowed_tools 三种语义（None / [] / [...])

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 更新 `sebastian/agents/README.md`

**Files:**
- Modify: `sebastian/agents/README.md`

- [ ] **Step 1: 读现有 README**

Run: `cat sebastian/agents/README.md`

找到介绍 `allowed_tools` / `manifest.toml` 的章节，或合适的位置（如"能力白名单"、"开发 Sub-Agent"相关小节）。

- [ ] **Step 2: 新增一节"`allowed_tools` 白名单语义"**

在合适位置插入下列内容（保持与既有 markdown 风格一致）：

````markdown
## `allowed_tools` 白名单语义

Sub-agent 在 `manifest.toml` 中通过 `allowed_tools` 声明能力边界。
该白名单在两层强制生效：

1. **LLM 可见性层**：传给 LLM 的 `tools` 参数按白名单过滤，LLM 看不到白名单外的工具。
2. **执行校验层**：`PolicyGate.call()` Stage 0 前置校验 `tool_name`，即使 LLM 幻觉出白名单外的工具名也会被拒绝。

### 三种取值

| manifest 声明 | Sub-agent 最终白名单 | 含义 |
|---|---|---|
| 未声明（缺省） | `None` | 不限制，可用全量工具（含协议工具） |
| `allowed_tools = []` | 5 个协议工具 | 仅具备通信能力，无领域工具 |
| `allowed_tools = ["Read"]` | `Read` + 5 个协议工具 | Read + 通信能力 |

### 协议工具（5 个，由 `_loader.py` 自动追加）

| 工具 | 用途 |
|---|---|
| `ask_parent` | 向上级请示，暂停等待回复 |
| `reply_to_agent` | 回复等待中的下属，恢复其执行 |
| `spawn_sub_agent` | 向下分派 depth=3 组员 |
| `check_sub_agents` | 查看自己组员的任务状态 |
| `inspect_session` | 查看指定 session 的详细进展 |

这 5 个工具决定 sub-agent 在层级中的通信能力，不属于领域能力范畴，所以自动注入，不需要每个 manifest 手动声明。

### Sebastian vs Sub-agent 协议工具对比

Sebastian 主管家**不经过 `_loader.py`**，`allowed_tools` 在 `sebastian/orchestrator/sebas.py` 中手工维护，不享受自动协议注入。

| 能力 | Sebastian (depth=1) | 组长 (depth=2) | 组员 (depth=3) |
|---|---|---|---|
| 向下派活 | `delegate_to_agent` | `spawn_sub_agent` | — |
| 回复下属 | `reply_to_agent` | `reply_to_agent` | — |
| 问上级 | — (无上级) | `ask_parent` | `ask_parent` |
| 查下属进度 | `check_sub_agents` | `check_sub_agents` | — |
| 查 session | `inspect_session` | `inspect_session` | `inspect_session` |

> 当前实现中 depth=2 和 depth=3 共用同一套协议 5 工具，是已知的简化（组员事实上不会用 `spawn_sub_agent` / `check_sub_agents`）。
````

- [ ] **Step 3: Commit**

```bash
git add sebastian/agents/README.md
git commit -m "$(cat <<'EOF'
docs(agents): 文档化 allowed_tools 白名单语义与协议工具

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: 更新 `docs/architecture/spec/agents/permission.md`

**Files:**
- Modify: `docs/architecture/spec/agents/permission.md`

- [ ] **Step 1: 读现有 spec**

Run: `cat docs/architecture/spec/agents/permission.md`

定位"工具可见性"小节（若不存在，在合适位置新建），以及描述 `PolicyGate.call()` 审批流的小节。

- [ ] **Step 2: 更新"工具可见性"小节**

插入/替换为：

```markdown
## 工具可见性与白名单

Sub-agent 的 `allowed_tools` 白名单在两层强制生效：

1. **LLM 可见性层**（`AgentLoop.stream()`）
   - `AgentLoop` 在 `__init__` 存储 `allowed_tools` / `allowed_skills`。
   - 每轮调用 LLM 前通过 `PolicyGate.get_callable_specs(allowed_tools, allowed_skills)` 获取过滤后的 spec 列表。
   - LLM 只"看到"白名单内的工具，避免误调用。

2. **执行校验层**（`PolicyGate.call()` Stage 0）
   - `BaseAgent._stream_inner` 创建 `ToolCallContext` 时把 `allowed_tools` 传入（`frozenset[str] | None`）。
   - `PolicyGate.call()` 在路径规范化之前即做身份白名单校验，拒绝白名单外的调用。
   - 防御 LLM 幻觉工具名的情况——即使模型编造不存在于 `tools` 列表的名字也会被拒绝。

两层之所以同时存在：
- 可见性层降低幻觉概率（LLM 看不到的工具，幻觉率显著下降）。
- 校验层提供硬保证（无论 LLM 怎么调用，身份边界不会被突破）。

白名单取值语义参见 `sebastian/agents/README.md` 的 "`allowed_tools` 白名单语义" 一节。
```

- [ ] **Step 3: 更新审批流顺序描述**

如果该 spec 文档有描述 `PolicyGate.call()` 审批阶段的列表，在最前加上 Stage 0：

```markdown
0. **agent 身份白名单校验**（所有 tier）：`context.allowed_tools` 非 `None` 且 `tool_name` 不在其中 → 立即返回错误，不执行工具。
1. Workspace 边界检查（所有 tier）...
2. LOW tier：直接执行。
3. MODEL_DECIDES tier：...
4. HIGH_RISK tier：始终请求用户审批。
```

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/spec/agents/permission.md
git commit -m "$(cat <<'EOF'
docs(spec): permission.md 更新工具可见性与 Stage 0 校验说明

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: 全量回归 + lint

**Files:** 无

- [ ] **Step 1: 格式化**

Run: `ruff format sebastian/ tests/`
Expected: 无报错

- [ ] **Step 2: Lint**

Run: `ruff check sebastian/ tests/`
Expected: `All checks passed!`

- [ ] **Step 3: 类型检查**

Run: `mypy sebastian/`
Expected: `Success: no issues found`

- [ ] **Step 4: 全量单测**

Run: `pytest -x`
Expected: 全绿

若有 FAIL：
- 逐个排查，不要跳过或 skip。
- 若是本次改动引入的 regression，回到对应 Task 修补；若是环境问题（外部依赖、网络），记录并与用户确认。

- [ ] **Step 5: 若 ruff format 有未提交的变更，补一个 chore commit**

```bash
git status
# 如果 format 产生变更：
git add -u
git commit -m "$(cat <<'EOF'
chore: ruff format 格式化

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## 验收复核

对照 spec 的验收标准逐项确认：

- [ ] 子代理 LLM 看到的 `tools` 参数 = `allowed_tools`（Task 4 单测覆盖）
- [ ] 子代理调用白名单外工具时被 `PolicyGate` Stage 0 拒绝（Task 6 单测覆盖）
- [ ] Sebastian 能成功调用 `reply_to_agent`（Task 7 单测覆盖 + allowed_tools 包含）
- [ ] `allowed_tools = None / [] / [...]` 三种语义（Task 8 单测覆盖）
- [ ] 新增单测覆盖上述 4 组场景
- [ ] `pytest` / `ruff check` / `ruff format` / `mypy` 全绿（Task 11）
- [ ] `sebastian/agents/README.md` 已同步（Task 9）
- [ ] `docs/architecture/spec/agents/permission.md` 已同步（Task 10）
