# No LLM Provider Friendly Error Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当数据库未配置 LLM Provider 时，后端不崩溃启动，用户发消息收到结构化 HTTP 400，App 在对话界面内显示带 "前往 Settings" 按钮的友好错误气泡。

**Architecture:** 后端去掉 lifespan eager 取 provider，把 `PermissionReviewer` 改成持有 `llm_registry` lazy 解析；三个发消息路由前置 `_ensure_llm_ready(agent_type)` helper 用 `registry.get_provider(agent_type)` 检查，失败返回 `400 + {code: "no_llm_provider"}`。前端 `handleSend` catch 识别 code，写入 conversation store 的 `errorBanner` / `draftErrorBanner`，`ChatScreen` 在输入框上方渲染新 `ErrorBanner` 组件。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / pytest-asyncio / React Native / Expo Router / Zustand / axios

**Spec reference:** [docs/superpowers/specs/2026-04-07-no-llm-provider-friendly-error-design.md](../specs/2026-04-07-no-llm-provider-friendly-error-design.md)

---

## File Structure

**Backend (4 files modified)**

| File | Responsibility |
|---|---|
| `sebastian/permissions/reviewer.py` | `PermissionReviewer` 改持有 `LLMProviderRegistry`，`review()` 内 lazy 解析 provider/model；解析失败返回 escalate |
| `sebastian/gateway/app.py` | 删除 lifespan 里 `get_default_with_model()` eager 调用；reviewer 构造改用 registry |
| `sebastian/gateway/routes/turns.py` | 新增模块级 `_ensure_llm_ready(agent_type)` helper；`send_turn` 路由开头调用 |
| `sebastian/gateway/routes/sessions.py` | 从 turns 导入 `_ensure_llm_ready`；`create_agent_session` 与 `send_turn_to_session` 加 pre-check |

**Backend tests (2 files)**

| File | Responsibility |
|---|---|
| `tests/unit/test_permission_reviewer.py` | 重写：适配新的 `llm_registry` 构造签名；新增"registry 抛 RuntimeError → escalate"用例 |
| `tests/integration/test_gateway_no_provider.py` | 新建：空 DB lifespan 正常完成；三个发消息路由返回 400 + code |

**Frontend (5 files)**

| File | Responsibility |
|---|---|
| `ui/mobile/src/store/conversation.ts` | `ConvSessionState` 增 `errorBanner` 字段；store 加 `draftErrorBanner` 顶层字段 + `setErrorBanner` / `setDraftErrorBanner` / `clearErrorBanner` actions |
| `ui/mobile/src/types.ts` | `ConvSessionState` 加 `errorBanner` 字段类型 |
| `ui/mobile/src/components/conversation/ErrorBanner.tsx` | 新建：对话内错误气泡组件（带"前往 Settings"按钮） |
| `ui/mobile/app/index.tsx` | `handleSend` catch 识别 `no_llm_provider`；在 `MessageInput` 上方渲染 `ErrorBanner` |
| `ui/mobile/app/subagents/session/[id].tsx` | 同上模式（识别 code + 渲染 banner） |

**不改动**：`BaseAgent` / `AgentLoop` / EventBus / EventType / `api/client.ts`（axios 已透传 `error.response.data`）/ `api/turns.ts` / `api/sessions.ts`

---

## Task 1: PermissionReviewer lazy 化

**Files:**
- Modify: `sebastian/permissions/reviewer.py`
- Test: `tests/unit/test_permission_reviewer.py`（完全重写）

- [ ] **Step 1: 阅读当前 reviewer 与已有测试**

Run: `cat sebastian/permissions/reviewer.py`
Run: `cat tests/unit/test_permission_reviewer.py`

当前测试用 `PermissionReviewer(client=mock_client)` 签名，这与现存的 `__init__(provider, model)` 签名不一致，说明这些测试在上一次重构后已经破损。本任务会把测试重写成与新 `llm_registry` 签名对齐。

- [ ] **Step 2: 写新的失败测试（registry 构造 + lazy 解析）**

替换 `tests/unit/test_permission_reviewer.py` 全部内容为：

```python
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.core.stream_events import TextDelta


async def _async_iter(items: list[Any]):
    for item in items:
        yield item


def _make_registry(provider: Any, model: str = "claude-haiku-4-5-20251001") -> MagicMock:
    registry = MagicMock()
    registry.get_default_with_model = AsyncMock(return_value=(provider, model))
    return registry


def _make_provider(response_text: str) -> MagicMock:
    provider = MagicMock()
    provider.stream = MagicMock(
        return_value=_async_iter([TextDelta(delta=response_text)])
    )
    return provider


@pytest.mark.asyncio
async def test_reviewer_returns_proceed_on_safe_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider('{"decision": "proceed", "explanation": ""}')
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "cat /etc/hosts"},
        reason="Reading hosts file to debug DNS issue",
        task_goal="Debug network connectivity",
    )

    assert decision.decision == "proceed"
    assert decision.explanation == ""
    registry.get_default_with_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_reviewer_returns_escalate_on_risky_command() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider(
        '{"decision": "escalate", "explanation": "此命令将永久删除文件，请确认。"}'
    )
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "rm -rf /tmp/old_data"},
        reason="Cleaning up temp files",
        task_goal="Summarize today's news",
    )

    assert decision.decision == "escalate"
    assert "删除" in decision.explanation


@pytest.mark.asyncio
async def test_reviewer_defaults_to_escalate_on_provider_error() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = MagicMock()

    def _raising(*args: Any, **kwargs: Any):
        async def _gen():
            raise RuntimeError("API error")
            yield  # pragma: no cover
        return _gen()

    provider.stream = _raising
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "ls"},
        reason="List files",
        task_goal="Find config file",
    )

    assert decision.decision == "escalate"
    assert decision.explanation != ""


@pytest.mark.asyncio
async def test_reviewer_defaults_to_escalate_on_invalid_json() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider("not valid json")
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="file_write",
        tool_input={"path": "/tmp/out.txt", "content": "data"},
        reason="Write output",
        task_goal="Generate report",
    )

    assert decision.decision == "escalate"


@pytest.mark.asyncio
async def test_reviewer_escalates_when_no_provider_configured() -> None:
    """Lazy resolution: if registry raises RuntimeError (no provider), escalate safely."""
    from sebastian.permissions.reviewer import PermissionReviewer

    registry = MagicMock()
    registry.get_default_with_model = AsyncMock(
        side_effect=RuntimeError("No default LLM provider configured.")
    )

    reviewer = PermissionReviewer(llm_registry=registry)
    decision = await reviewer.review(
        tool_name="shell",
        tool_input={"command": "ls"},
        reason="List files",
        task_goal="Any goal",
    )

    assert decision.decision == "escalate"
    assert "Provider" in decision.explanation or "provider" in decision.explanation


@pytest.mark.asyncio
async def test_reviewer_passes_context_to_llm() -> None:
    from sebastian.permissions.reviewer import PermissionReviewer

    provider = _make_provider('{"decision": "proceed", "explanation": ""}')
    registry = _make_registry(provider)

    reviewer = PermissionReviewer(llm_registry=registry)
    await reviewer.review(
        tool_name="shell",
        tool_input={"command": "pwd"},
        reason="Check working directory",
        task_goal="Debug file path issue",
    )

    call_kwargs = provider.stream.call_args
    user_content = call_kwargs.kwargs["messages"][0]["content"]
    assert "shell" in user_content
    assert "pwd" in user_content
    assert "Check working directory" in user_content
    assert "Debug file path issue" in user_content
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/unit/test_permission_reviewer.py -v`
Expected: FAIL — `PermissionReviewer.__init__() got an unexpected keyword argument 'llm_registry'`（或类似）

- [ ] **Step 4: 改造 reviewer.py**

替换 `sebastian/permissions/reviewer.py` 全部内容为：

```python
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sebastian.permissions.types import ReviewDecision

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a security reviewer for an AI assistant system.
Your job: decide whether a tool call should proceed directly or require user approval.

Rules:
- PROCEED if: the action is reversible, read-only, or clearly aligned with the stated task goal
- ESCALATE if: the action is destructive, irreversible, accesses sensitive data,
  or the stated reason does not match the task goal
- When in doubt, ESCALATE

Respond ONLY in valid JSON:
{"decision": "proceed" | "escalate", "explanation": "..."}
explanation must be in the user's language, written for a non-technical user.
When decision is "proceed", explanation is an empty string.\
"""


class PermissionReviewer:
    """Stateless LLM reviewer for MODEL_DECIDES tool calls.

    Holds a reference to the LLM registry and lazily resolves the default
    provider on each review() call. This way the reviewer can be constructed
    before any provider is configured — at review time, if the registry still
    has no provider, the reviewer falls back to a safe escalate decision.
    """

    def __init__(self, llm_registry: LLMProviderRegistry) -> None:
        self._llm_registry = llm_registry

    async def review(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        task_goal: str,
    ) -> ReviewDecision:
        """Return a proceed/escalate decision for the given tool call."""
        from sebastian.core.stream_events import TextDelta

        try:
            provider, model = await self._llm_registry.get_default_with_model()
        except RuntimeError:
            logger.warning(
                "PermissionReviewer: no LLM provider configured, defaulting to escalate"
            )
            return ReviewDecision(
                decision="escalate",
                explanation="未配置 LLM Provider，无法自动审查工具调用，请人工批准。",
            )

        user_content = (
            f"Task goal: {task_goal}\n"
            f"Tool: {tool_name}\n"
            f"Input: {json.dumps(tool_input, ensure_ascii=False)}\n"
            f"Model's reason: {reason}"
        )
        try:
            text = ""
            async for event in provider.stream(
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
                tools=[],
                model=model,
                max_tokens=256,
            ):
                if isinstance(event, TextDelta):
                    text += event.delta
            data = json.loads(text.strip())
            decision = data.get("decision", "escalate")
            if decision not in ("proceed", "escalate"):
                decision = "escalate"
            explanation = data.get("explanation", "")
            return ReviewDecision(decision=decision, explanation=explanation)
        except Exception:
            logger.exception("PermissionReviewer failed, defaulting to escalate")
            return ReviewDecision(
                decision="escalate",
                explanation="Permission review failed; manual approval required.",
            )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/unit/test_permission_reviewer.py -v`
Expected: PASS — all 6 tests green

- [ ] **Step 6: 提交**

```bash
git add sebastian/permissions/reviewer.py tests/unit/test_permission_reviewer.py
git commit -m "refactor(permissions): PermissionReviewer 改持有 llm_registry lazy 解析

Why: lifespan 启动时 eager 构造 reviewer 需要具体 provider 实例，
空数据库场景会导致 FastAPI 启动崩溃。改造后 reviewer 在 review()
时才从 registry 取 provider，取不到则安全 fallback 为 escalate。

- __init__(llm_registry) 替代 (provider, model)
- review() 内 lazy 解析默认 provider
- RuntimeError (未配 provider) → escalate + 提示语
- 重写单元测试覆盖 6 个场景

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Gateway lifespan 去掉 eager 取 provider

**Files:**
- Modify: `sebastian/gateway/app.py`（行 78、102）
- Test: `tests/integration/test_llm_provider_wiring.py`（可能需要更新断言）

- [ ] **Step 1: 先看现有 wiring 测试**

Run: `cat tests/integration/test_llm_provider_wiring.py`

这个测试验证 gateway 能起、`state.llm_registry` 存在。改造完成后它应当**仍然通过**，因为我们只是移除 eager 调用，registry 实例化不变。

- [ ] **Step 2: 运行现有 wiring 测试看当前状态**

Run: `pytest tests/integration/test_llm_provider_wiring.py -v`
Expected: 可能 FAIL（空 DB 时 lifespan 抛 RuntimeError），这正是本任务要修的问题。

- [ ] **Step 3: 修改 gateway/app.py**

打开 `sebastian/gateway/app.py`，定位到 lifespan 函数中的这两行（约 78 和 102 行）：

```python
llm_registry = LLMProviderRegistry(db_factory)
default_provider, default_model = await llm_registry.get_default_with_model()
```

删除第二行（`default_provider, default_model = ...`），保留 `llm_registry = ...`。

继续定位到（约第 102 行）：

```python
reviewer = PermissionReviewer(provider=default_provider, model=default_model)
```

改成：

```python
reviewer = PermissionReviewer(llm_registry=llm_registry)
```

改完后确认：lifespan 函数里不再存在任何 `default_provider` / `default_model` 变量引用。

Run: `grep -n "default_provider\|default_model" sebastian/gateway/app.py`
Expected: 无输出

- [ ] **Step 4: 运行 wiring 测试确认通过**

Run: `pytest tests/integration/test_llm_provider_wiring.py -v`
Expected: PASS — 空 DB 下 gateway 正常启动

- [ ] **Step 5: 运行所有现有 gateway 集成测试，确保没回归**

Run: `pytest tests/integration/test_gateway_turns.py tests/integration/test_gateway_sessions.py tests/integration/test_llm_provider_wiring.py -v`
Expected: PASS —（若有既存失败用例与本次无关，记录但不修）

- [ ] **Step 6: 提交**

```bash
git add sebastian/gateway/app.py
git commit -m "fix(gateway): lifespan 去掉 eager 取 default provider

Why: 空数据库部署时 get_default_with_model() 抛 RuntimeError 导致
FastAPI 启动崩溃。配合 PermissionReviewer lazy 改造，lifespan 不再
需要在启动时预取 provider。

- 删除 lifespan 第 78 行 default_provider/default_model eager 取值
- PermissionReviewer 构造改传 llm_registry

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Gateway pre-check helper + turns 路由接入

**Files:**
- Modify: `sebastian/gateway/routes/turns.py`
- Test: `tests/integration/test_gateway_no_provider.py`（新建）

- [ ] **Step 1: 新建失败测试文件**

创建 `tests/integration/test_gateway_no_provider.py`：

```python
from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def empty_db_client(tmp_path):
    """Gateway with empty DB (no LLM provider configured)."""
    from sebastian.gateway.auth import hash_password

    password_hash = hash_password("testpass")

    with patch.dict(
        os.environ,
        {
            "SEBASTIAN_OWNER_PASSWORD_HASH": password_hash,
            "SEBASTIAN_DATA_DIR": str(tmp_path),
            "SEBASTIAN_JWT_SECRET": "test-secret-key",
        },
    ):
        import sebastian.config as cfg_module

        importlib.reload(cfg_module)
        with patch.object(cfg_module.settings, "sebastian_owner_password_hash", password_hash):
            from sebastian.gateway.app import create_app

            test_app = create_app()
            with TestClient(test_app, raise_server_exceptions=True) as test_client:
                yield test_client


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_lifespan_starts_with_empty_db(empty_db_client: TestClient) -> None:
    """Gateway should start normally even when no LLM provider is configured."""
    # Reaching this point means lifespan completed successfully.
    response = empty_db_client.post("/api/v1/auth/login", json={"password": "testpass"})
    assert response.status_code == 200


def test_send_turn_returns_400_no_llm_provider(empty_db_client: TestClient) -> None:
    token = _login(empty_db_client)
    response = empty_db_client.post(
        "/api/v1/turns",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "no_llm_provider"
    assert "Settings" in detail["message"] or "设置" in detail["message"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/integration/test_gateway_no_provider.py -v`
Expected: FAIL —
- `test_lifespan_starts_with_empty_db`：现在 Task 2 已修好，可能 PASS
- `test_send_turn_returns_400_no_llm_provider`：FAIL，现在 send_turn 没做 pre-check

- [ ] **Step 3: 在 turns.py 加 helper 并接入 send_turn**

打开 `sebastian/gateway/routes/turns.py`，在 imports 下、`router = APIRouter(...)` 之后、`AuthPayload = ...` 之前，新增 helper：

```python
async def _ensure_llm_ready(agent_type: str) -> None:
    """Verify that the given agent_type has a usable LLM provider.

    Raises HTTPException(400) with a structured code if none is configured,
    so the client can render a friendly error pointing to Settings.
    """
    import sebastian.gateway.state as state

    try:
        await state.llm_registry.get_provider(agent_type)
    except RuntimeError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_llm_provider",
                "message": "尚未配置 LLM Provider，请前往 Settings → 模型 页面添加",
            },
        )
```

然后修改 `send_turn` 路由，在 `session = await state.sebastian.get_or_create_session(...)` **之前**加一行 pre-check：

```python
@router.post("/turns")
async def send_turn(
    body: SendTurnRequest,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    await _ensure_llm_ready("sebastian")
    session = await state.sebastian.get_or_create_session(body.session_id, body.content)
    task = asyncio.create_task(state.sebastian.run_streaming(body.content, session.id))
    task.add_done_callback(_log_background_turn_failure)
    return {
        "session_id": session.id,
        "ts": datetime.now(UTC).isoformat(),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/integration/test_gateway_no_provider.py -v`
Expected: PASS — 两个测试都 green

- [ ] **Step 5: 确保 turns 现有测试没回归**

Run: `pytest tests/integration/test_gateway_turns.py -v`
Expected: PASS（现有测试用 mock 了 `Sebastian.run_streaming`，但会经过 pre-check。由于现有 fixture 的数据库依然是空的，现有测试可能因新增 pre-check 失败——如果失败，需要在 fixture 里预先 seed 一条默认 provider 记录，或对 `_ensure_llm_ready` 打 patch。）

- [ ] **Step 6: 若 Step 5 失败，给 turns 测试 fixture 打 patch**

若 `test_gateway_turns.py` 因 pre-check 失败，在其 `client` fixture 内新增一层 patch，让 `_ensure_llm_ready` 成为 no-op：

```python
from unittest.mock import AsyncMock
# ... 在 with patch(...) 链内部追加：
with patch(
    "sebastian.gateway.routes.turns._ensure_llm_ready",
    new_callable=AsyncMock,
):
    ...
```

重新运行 Step 5 直到 PASS。

- [ ] **Step 7: 提交**

```bash
git add sebastian/gateway/routes/turns.py tests/integration/test_gateway_no_provider.py tests/integration/test_gateway_turns.py
git commit -m "feat(gateway): turns 路由加 _ensure_llm_ready pre-check

Why: 用户发消息时若未配置 LLM Provider，需返回结构化 HTTP 400
({code: no_llm_provider}) 而非让后台 task 静默失败。pre-check
使用 get_provider(agent_type) 为未来 per-agent provider 绑定留路。

- 新增 _ensure_llm_ready(agent_type) helper
- send_turn 在创建 session 之前调用 pre-check
- 新增集成测试：空 DB 启动 + 400 响应契约

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Sessions 路由接入 pre-check

**Files:**
- Modify: `sebastian/gateway/routes/sessions.py`
- Test: `tests/integration/test_gateway_no_provider.py`（追加用例）

- [ ] **Step 1: 追加失败测试**

在 `tests/integration/test_gateway_no_provider.py` 文件底部追加：

```python
def test_create_agent_session_returns_400(empty_db_client: TestClient) -> None:
    token = _login(empty_db_client)
    response = empty_db_client.post(
        "/api/v1/agents/sebastian/sessions",
        json={"content": "hello sub-agent"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # pre-check 先于 agent_type 404 检查
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "no_llm_provider"


def test_send_turn_to_session_returns_400(empty_db_client: TestClient, tmp_path) -> None:
    """Need an existing session to hit this route. Create one directly via store."""
    import asyncio
    from sebastian.core.types import Session

    token = _login(empty_db_client)

    # Create a session directly via store (bypass create route which is also gated).
    import sebastian.gateway.state as state

    async def _seed() -> str:
        session = Session(
            agent_type="sebastian",
            title="seed",
            goal="seed",
            depth=1,
        )
        await state.session_store.create_session(session)
        await state.index_store.upsert(session)
        return session.id

    session_id = asyncio.get_event_loop().run_until_complete(_seed())

    response = empty_db_client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "no_llm_provider"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/integration/test_gateway_no_provider.py -v`
Expected: 两个新用例 FAIL

- [ ] **Step 3: 修改 sessions.py 加 pre-check**

打开 `sebastian/gateway/routes/sessions.py`，在顶部 imports 区加：

```python
from sebastian.gateway.routes.turns import _ensure_llm_ready
```

修改 `create_agent_session`，在 `if agent_type not in state.agent_instances:` 之前加 pre-check（**先检查 provider，再检查 agent 存在性**——顺序很重要，让用户优先看到 provider 问题）：

```python
@router.post("/agents/{agent_type}/sessions")
async def create_agent_session(
    agent_type: str,
    body: dict,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    """Create a new conversation with a sub-agent."""
    import sebastian.gateway.state as state

    await _ensure_llm_ready(agent_type)

    if agent_type not in state.agent_instances:
        raise HTTPException(404, f"Agent type not found: {agent_type}")
    # ... rest unchanged
```

修改 `send_turn_to_session`，在 `_resolve_session` 之后、`_touch_session` 之前加 pre-check（此处需要先 resolve 才知道 agent_type）：

```python
@router.post("/sessions/{session_id}/turns")
async def send_turn_to_session(
    session_id: str,
    body: SendTurnBody,
    _auth: AuthPayload = Depends(require_auth),
) -> JSONDict:
    import sebastian.gateway.state as state

    session = await _resolve_session(state, session_id)
    await _ensure_llm_ready(session.agent_type)
    now = await _touch_session(state, session)
    await _schedule_session_turn(session, body.content)

    return {
        "session_id": session_id,
        "ts": now.isoformat(),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/integration/test_gateway_no_provider.py -v`
Expected: PASS — 所有 4 个用例 green

- [ ] **Step 5: 确保 sessions 现有测试没回归**

Run: `pytest tests/integration/test_gateway_sessions.py -v`
Expected: PASS。若因 pre-check 失败，参考 Task 3 Step 6 的方式在对应 fixture 里 patch `sebastian.gateway.routes.turns._ensure_llm_ready`。

- [ ] **Step 6: 跑全量 backend 测试确认全绿**

Run: `pytest tests/unit tests/integration -v`
Expected: PASS（或至少与改动前同样的 PASS 集合）

- [ ] **Step 7: 提交**

```bash
git add sebastian/gateway/routes/sessions.py tests/integration/test_gateway_no_provider.py tests/integration/test_gateway_sessions.py
git commit -m "feat(gateway): sessions 路由接入 _ensure_llm_ready pre-check

Why: sub-agent 创建会话 / 已有 session 发 turn 与主 turns 路由共享
同一个 provider 契约，同样需要在 background task 调度之前返回
400 + no_llm_provider。

- create_agent_session: pre-check 在 agent_type 存在性检查之前
- send_turn_to_session: pre-check 在 resolve_session 之后（需 agent_type）
- 复用 turns.py 的 _ensure_llm_ready helper，不重复定义
- 集成测试覆盖两个新路由

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 前端 types + conversation store 加 errorBanner

**Files:**
- Modify: `ui/mobile/src/types.ts`
- Modify: `ui/mobile/src/store/conversation.ts`

- [ ] **Step 1: 修改 types.ts**

打开 `ui/mobile/src/types.ts`，找到 `ConvSessionState` 接口（约 169 行），修改为：

```ts
export interface ErrorBanner {
  code: string;
  message: string;
}

export interface ConvSessionState {
  status: 'idle' | 'loading' | 'live' | 'paused';
  messages: ConvMessage[];
  activeTurn: ActiveTurn | null;
  errorBanner: ErrorBanner | null;
}
```

- [ ] **Step 2: 修改 conversation.ts store**

打开 `ui/mobile/src/store/conversation.ts`。

2a. 更新 `emptySession()`（约第 29 行）：

```ts
function emptySession(): ConvSessionState {
  return { status: 'idle', messages: [], activeTurn: null, errorBanner: null };
}
```

2b. 在 imports 下补类型：

```ts
import type { ActiveTurn, ConvMessage, ConvSessionState, ErrorBanner, RenderBlock } from '../types';
```

2c. 修改 `ConversationStore` interface（约第 6 行），在 `sessions` 字段后追加 `draftErrorBanner`，在 action 列表末尾追加三个新 action：

```ts
interface ConversationStore {
  sessions: Record<string, ConvSessionState>;
  draftErrorBanner: ErrorBanner | null;

  getOrInit(sessionId: string): ConvSessionState;
  setStatus(sessionId: string, status: ConvSessionState['status']): void;
  setMessages(sessionId: string, messages: ConvMessage[]): void;
  pauseSession(sessionId: string): void;
  evictSession(sessionId: string): void;

  onThinkingBlockStart(sessionId: string, blockId: string): void;
  onThinkingDelta(sessionId: string, blockId: string, delta: string): void;
  onThinkingBlockStop(sessionId: string, blockId: string): void;
  onTextBlockStart(sessionId: string, blockId: string): void;
  onTextDelta(sessionId: string, blockId: string, delta: string): void;
  onTextBlockStop(sessionId: string, blockId: string): void;
  appendUserMessage(sessionId: string, content: string): void;
  onToolRunning(sessionId: string, toolId: string, name: string, input: string): void;
  onToolExecuted(sessionId: string, toolId: string, result: string): void;
  onToolFailed(sessionId: string, toolId: string, error: string): void;
  onTurnComplete(sessionId: string): void;
  completeTurn(sessionId: string): void;

  setErrorBanner(sessionId: string, banner: ErrorBanner | null): void;
  setDraftErrorBanner(banner: ErrorBanner | null): void;
  clearErrorBanners(sessionId: string | null): void;
}
```

2d. 在 `create<ConversationStore>((set, get) => ({` 的初始 state 加上 `draftErrorBanner: null,`：

```ts
export const useConversationStore = create<ConversationStore>((set, get) => ({
  sessions: {},
  draftErrorBanner: null,

  getOrInit(sessionId) { ... },
  ...
```

2e. 在 store 对象末尾（`completeTurn` 后、闭合 `}))` 之前）追加三个 action：

```ts
  setErrorBanner(sessionId, banner) {
    set((s) => ({ sessions: updateSession(s.sessions, sessionId, { errorBanner: banner }) }));
  },

  setDraftErrorBanner(banner) {
    set({ draftErrorBanner: banner });
  },

  clearErrorBanners(sessionId) {
    set((s) => {
      const next: Partial<ConversationStore> = { draftErrorBanner: null };
      if (sessionId && s.sessions[sessionId]) {
        next.sessions = updateSession(s.sessions, sessionId, { errorBanner: null });
      }
      return next as ConversationStore;
    });
  },
```

2f. 在 `appendUserMessage` 的 set 回调里顺带清 banner（成功发出新消息即视为用户已看到提示）。找到现有实现（约第 178 行）：

```ts
appendUserMessage(sessionId, content) {
  set((s) => {
    const session = s.sessions[sessionId] ?? emptySession();
    const msg: ConvMessage = {
      id: `${sessionId}-user-${Date.now()}`,
      role: 'user',
      content,
      createdAt: new Date().toISOString(),
    };
    return {
      sessions: updateSession(s.sessions, sessionId, {
        messages: [...session.messages, msg],
        errorBanner: null,
      }),
      draftErrorBanner: null,
    };
  });
},
```

（新增了 `errorBanner: null` 和 `draftErrorBanner: null`）

- [ ] **Step 3: TypeScript 类型检查**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误。若报 `ConvSessionState` 字段不全，确认所有 `emptySession()` 引用都已更新。

- [ ] **Step 4: 提交**

```bash
git add ui/mobile/src/types.ts ui/mobile/src/store/conversation.ts
git commit -m "feat(mobile): conversation store 增 errorBanner 字段与 actions

Why: 后端返回 no_llm_provider 400 时，前端需要一个 ephemeral
(非持久化) 的错误态容器，用于在对话界面内渲染友好提示气泡。
草稿 session (currentSessionId === null) 单独用 draftErrorBanner
顶层字段，避免用特殊 key 污染 sessions map。

- ConvSessionState 加 errorBanner: ErrorBanner | null
- store 加 draftErrorBanner 顶层字段
- 新增 setErrorBanner / setDraftErrorBanner / clearErrorBanners actions
- appendUserMessage 成功时清除 banner

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 新建 ErrorBanner 组件

**Files:**
- Create: `ui/mobile/src/components/conversation/ErrorBanner.tsx`

- [ ] **Step 1: 创建组件文件**

创建 `ui/mobile/src/components/conversation/ErrorBanner.tsx`：

```tsx
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useTheme } from '@/src/theme/ThemeContext';

interface Props {
  message: string;
  onAction: () => void;
}

export function ErrorBanner({ message, onAction }: Props) {
  const colors = useTheme();
  return (
    <View
      style={[
        styles.container,
        { backgroundColor: colors.errorBg ?? '#FEF2F2', borderColor: colors.errorBorder ?? '#FCA5A5' },
      ]}
    >
      <Text style={[styles.message, { color: colors.errorText ?? '#991B1B' }]}>
        {message}
      </Text>
      <TouchableOpacity onPress={onAction} style={styles.actionBtn}>
        <Text style={[styles.actionText, { color: colors.errorText ?? '#991B1B' }]}>
          前往 Settings →
        </Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: 12,
    marginVertical: 8,
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
  },
  message: {
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 8,
  },
  actionBtn: {
    alignSelf: 'flex-start',
  },
  actionText: {
    fontSize: 14,
    fontWeight: '600',
  },
});
```

**说明 errorBg / errorBorder / errorText**：这几个颜色可能不在现有 theme 里。组件用 `??` fallback 到硬编码红色系，保证无论 theme 是否定义都能渲染。未来 theme 补齐这几个 key 时组件自动跟随，无需改动。

- [ ] **Step 2: TypeScript 检查**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误。若 `useTheme` 返回类型导致 `colors.errorBg` 报错（类型严格），把 `colors` cast 成 `any`：

```tsx
const colors = useTheme() as any;
```

（主题字段扩展不在本任务范围内。）

- [ ] **Step 3: 提交**

```bash
git add ui/mobile/src/components/conversation/ErrorBanner.tsx
git commit -m "feat(mobile): 新增 ErrorBanner 对话内错误气泡组件

Why: 为未配置 LLM Provider 等配置类错误提供对话界面内的友好
提示入口，带跳转 Settings 按钮。组件不依赖具体错误类型，可
复用于其他结构化错误场景。

- 红色系气泡样式 + 单行 action button
- 颜色字段有 fallback，theme 未定义也可正常渲染

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 主对话页 handleSend catch + 渲染 ErrorBanner

**Files:**
- Modify: `ui/mobile/app/index.tsx`

- [ ] **Step 1: 修改 imports**

打开 `ui/mobile/app/index.tsx`，在现有 imports 下追加：

```tsx
import { router } from 'expo-router';
import axios from 'axios';
import { ErrorBanner } from '@/src/components/conversation/ErrorBanner';
```

- [ ] **Step 2: 修改 handleSend 的 catch**

找到现有 `handleSend` 函数（约 31 行），替换为：

```tsx
async function handleSend(text: string) {
  try {
    const { sessionId } = await sendTurn(currentSessionId, text);
    if (!currentSessionId) {
      persistSession({
        id: sessionId,
        agent: 'sebastian',
        title: text.slice(0, 40),
        status: 'active',
        updated_at: new Date().toISOString(),
        task_count: 0,
        active_task_count: 0,
      });
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    }
    useConversationStore.getState().appendUserMessage(sessionId, text);
    queryClient.invalidateQueries({ queryKey: ['messages', sessionId] });
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 400) {
      const detail = err.response.data?.detail;
      if (detail?.code === 'no_llm_provider') {
        const banner = { code: detail.code, message: detail.message };
        const store = useConversationStore.getState();
        if (currentSessionId) {
          store.setErrorBanner(currentSessionId, banner);
        } else {
          store.setDraftErrorBanner(banner);
        }
        return;
      }
    }
    Alert.alert('发送失败，请重试');
  }
}
```

- [ ] **Step 3: 从 store 订阅当前 banner**

在 `ChatScreen` 组件顶部（现有 `isWorking` useConversationStore 订阅旁边）追加：

```tsx
const currentBanner = useConversationStore((s) =>
  currentSessionId ? (s.sessions[currentSessionId]?.errorBanner ?? null) : s.draftErrorBanner,
);
```

- [ ] **Step 4: 渲染 ErrorBanner**

定位 JSX 内 `<MessageInput ... />` 这一行（约 98 行），在它**之上**插入：

```tsx
{currentBanner && (
  <ErrorBanner
    message={currentBanner.message}
    onAction={() => router.push('/settings')}
  />
)}
<MessageInput isWorking={isWorking} onSend={handleSend} onStop={handleStop} />
```

- [ ] **Step 5: TypeScript 检查**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: 手动验证步骤（记录在提交消息里，不写死在测试里）**

验证清单：
1. 确认本地 DB 无 provider（或删 `~/.sebastian/sebastian.db` 重启后端）
2. `uvicorn sebastian.gateway.app:app --port 8000 --reload` — 应正常启动，不崩
3. `cd ui/mobile && npx expo start` — 启动 App
4. App 内发消息 → 对话区出现红色错误气泡 + "前往 Settings" 按钮
5. 点击按钮 → 跳转 Settings 页
6. 配置一个 Provider 并设为默认
7. 回到对话页，再次发消息 → 成功，错误气泡消失

- [ ] **Step 7: 提交**

```bash
git add ui/mobile/app/index.tsx
git commit -m "feat(mobile): 主对话页 handleSend 识别 no_llm_provider 并渲染 ErrorBanner

Why: 后端未配置 LLM Provider 时会返回 400 + {code: no_llm_provider}，
前端需要在对话界面内显示友好提示而非通用 Alert。

- handleSend catch 块识别结构化 detail.code
- draft 态 / 已有 session 分别写入 draftErrorBanner / per-session errorBanner
- MessageInput 上方条件渲染 <ErrorBanner>，点击跳 /settings

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Sub-agent 会话页同样处理

**Files:**
- Modify: `ui/mobile/app/subagents/session/[id].tsx`

- [ ] **Step 1: 读现有实现**

Run: `cat ui/mobile/app/subagents/session/[id].tsx`

定位该页的 `handleSend` 函数与 JSX 中 `<MessageInput>` 的位置。此页通常通过 session id 发 turn，调用 `/api/v1/sessions/{id}/turns`。

- [ ] **Step 2: 追加 imports**

在该文件顶部追加（如尚未存在）：

```tsx
import { router } from 'expo-router';
import axios from 'axios';
import { ErrorBanner } from '@/src/components/conversation/ErrorBanner';
import { useConversationStore } from '@/src/store/conversation';
```

- [ ] **Step 3: 修改 handleSend catch**

该页的 `currentSessionId` 来自路由 params（一定非 null）。把 `handleSend` 的 catch 块改为：

```tsx
} catch (err) {
  if (axios.isAxiosError(err) && err.response?.status === 400) {
    const detail = err.response.data?.detail;
    if (detail?.code === 'no_llm_provider') {
      useConversationStore.getState().setErrorBanner(sessionId, {
        code: detail.code,
        message: detail.message,
      });
      return;
    }
  }
  Alert.alert('发送失败，请重试');
}
```

（变量名 `sessionId` 按该文件实际命名调整。）

- [ ] **Step 4: 订阅 + 渲染 banner**

在组件顶部订阅：

```tsx
const banner = useConversationStore((s) => s.sessions[sessionId]?.errorBanner ?? null);
```

在 JSX 的 `<MessageInput ... />` 上方插入：

```tsx
{banner && (
  <ErrorBanner
    message={banner.message}
    onAction={() => router.push('/settings')}
  />
)}
```

- [ ] **Step 5: TypeScript 检查**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: 提交**

```bash
git add ui/mobile/app/subagents/session/[id].tsx
git commit -m "feat(mobile): sub-agent 会话页同样识别 no_llm_provider 并渲染 ErrorBanner

Why: 与主对话页保持一致，sub-agent session 发 turn 失败时也要在
对话界面内友好提示而非通用 Alert。

- handleSend catch 识别 detail.code === no_llm_provider
- 写入 per-session errorBanner
- MessageInput 上方渲染 ErrorBanner

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: 端到端验证 + 更新模块 README

**Files:**
- Possibly modify: `sebastian/permissions/README.md` / `sebastian/gateway/README.md` / `ui/mobile/README.md`（如相关章节提到 provider 行为）

- [ ] **Step 1: 全量后端测试**

Run: `pytest tests/unit tests/integration -v`
Expected: 所有原 PASS 用例仍 PASS，新加的 6 + 4 个用例 PASS。

- [ ] **Step 2: 前端 TypeScript 全量检查**

Run: `cd ui/mobile && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 手动 E2E 验证**

按 Task 7 Step 6 的清单执行一次完整手动验证，确认：
- 空 DB 启动后端不崩
- 三个发消息入口（主对话、sub-agent 创建、sub-agent 发 turn）都能触发 400
- App 内两个对话页都能看到 ErrorBanner 并跳转 Settings
- 配置 provider 后发消息正常恢复

- [ ] **Step 4: 检查相关 README 是否需要更新**

Run: `grep -l "LLM Provider\|ANTHROPIC_API_KEY" sebastian/permissions/README.md sebastian/gateway/README.md sebastian/llm/README.md ui/mobile/README.md 2>/dev/null`

若有 README 描述了旧的 env key fallback 或 reviewer 构造签名，更新为新行为。若无相关描述，跳过。

- [ ] **Step 5: 提交（如有 README 改动）**

```bash
git add <changed README files>
git commit -m "docs: 同步 provider lazy 行为到相关模块 README

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

若无 README 改动，跳过本步。

---

## Self-Review Notes

**Spec coverage check**

| Spec 要求 | 对应 Task |
|---|---|
| 启动不依赖 DB 有 provider | Task 1 (reviewer lazy) + Task 2 (lifespan 去 eager) |
| 发消息返回结构化 400 + code | Task 3 (turns) + Task 4 (sessions) |
| 前瞻：用 `get_provider(agent_type)` | Task 3 Step 3 helper |
| PermissionReviewer lazy + escalate fallback | Task 1 |
| 错误不持久化，ephemeral UI | Task 5 (store) + Task 6 (component) |
| 对话界面内显示 + 跳 Settings | Task 6 + Task 7 + Task 8 |
| Draft session 独立 banner | Task 5 (draftErrorBanner) + Task 7 |
| 三个发消息路由全覆盖 | Task 3 (1 个) + Task 4 (2 个) |
| 不改 BaseAgent/AgentLoop/EventBus | 无对应 task（刻意不做）|
| 不加 env key fallback | 无对应 task（刻意不做）|

**Placeholder scan**：无 "TBD" / "similar to above" / "handle edge cases"。所有代码块完整。

**Type consistency check**：
- `_ensure_llm_ready` 在 Task 3 定义、Task 4 复用（import）—— 一致
- `ErrorBanner` 类型在 Task 5 定义、Task 6/7/8 使用 —— 一致
- `setErrorBanner` / `setDraftErrorBanner` / `clearErrorBanners` 签名在 Task 5 定义、Task 7/8 调用 —— 一致
- `currentBanner` 选择器逻辑 Task 7 定义，Task 8 用 per-session 版本 —— 一致（草稿态仅主页存在）
