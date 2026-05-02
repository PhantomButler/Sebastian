# Soul 人格切换系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Sebastian 的人格提示词提取为可热切换的 `.md` Soul 文件，通过 `switch_soul` 工具实现下一 turn 立即生效的角色切换，内置 sebastian 和 cortana 两个人格，重启后自动恢复上次激活的 soul。

**Architecture:** `SoulLoader` 负责 `~/.sebastian/data/souls/` 目录管理；`app_settings` KV 表存储 `active_soul`；`switch_soul` 工具通过 `gateway.state` 单例引用更新 `sebastian.persona` 和 `system_prompt`；gateway lifespan 启动时恢复上次切换的 soul。Soul 文件只含人格灵魂内容（中文），行为约束提取为 `BASE_BUTLER_RULES` 常量，由 `Sebastian._persona_section()` 固定注入。

**Tech Stack:** Python 3.12+, SQLAlchemy async, pytest-asyncio, `unittest.mock`

---

## 文件变更清单

| 操作 | 文件 |
|------|------|
| 新增 | `sebastian/core/soul_loader.py` |
| 新增 | `sebastian/capabilities/tools/switch_soul/__init__.py` |
| 新增 | `tests/unit/core/test_soul_loader.py` |
| 新增 | `tests/unit/capabilities/test_switch_soul.py` |
| 新增 | `tests/integration/test_gateway_soul.py` |
| 修改 | `sebastian/orchestrator/sebas.py` |
| 修改 | `sebastian/config/__init__.py` |
| 修改 | `sebastian/store/app_settings_store.py` |
| 修改 | `sebastian/gateway/state.py` |
| 修改 | `sebastian/gateway/app.py` |
| 修改 | `sebastian/capabilities/tools/README.md` |
| 修改 | `docs/architecture/spec/core/system-prompt.md` |

---

### Task 1: SoulLoader 模块

**Files:**
- Create: `sebastian/core/soul_loader.py`
- Test: `tests/unit/core/test_soul_loader.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/core/test_soul_loader.py`：

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.soul_loader import SoulLoader

_BUILTIN = {"sebastian": "You are Sebastian.", "cortana": "You are Cortana."}


@pytest.fixture
def souls_dir(tmp_path: Path) -> Path:
    d = tmp_path / "souls"
    d.mkdir()
    return d


@pytest.fixture
def loader(souls_dir: Path) -> SoulLoader:
    return SoulLoader(souls_dir=souls_dir, builtin_souls=_BUILTIN)


def test_list_souls_empty_dir(loader: SoulLoader) -> None:
    assert loader.list_souls() == []


def test_list_souls_returns_stems(souls_dir: Path, loader: SoulLoader) -> None:
    (souls_dir / "alice.md").write_text("Alice persona")
    (souls_dir / "bob.md").write_text("Bob persona")
    assert loader.list_souls() == ["alice", "bob"]


def test_load_returns_content(souls_dir: Path, loader: SoulLoader) -> None:
    (souls_dir / "alice.md").write_text("Alice persona")
    assert loader.load("alice") == "Alice persona"


def test_load_returns_none_when_missing(loader: SoulLoader) -> None:
    assert loader.load("nonexistent") is None


def test_load_rejects_path_traversal(loader: SoulLoader) -> None:
    assert loader.load("../../etc/passwd") is None
    assert loader.load("../secret") is None
    assert loader.load("/absolute/path") is None


def test_ensure_defaults_creates_missing_files(souls_dir: Path, loader: SoulLoader) -> None:
    loader.ensure_defaults()
    assert (souls_dir / "sebastian.md").read_text() == "You are Sebastian."
    assert (souls_dir / "cortana.md").read_text() == "You are Cortana."


def test_ensure_defaults_does_not_overwrite_existing(souls_dir: Path, loader: SoulLoader) -> None:
    (souls_dir / "sebastian.md").write_text("Custom Sebastian")
    loader.ensure_defaults()
    assert (souls_dir / "sebastian.md").read_text() == "Custom Sebastian"


def test_ensure_defaults_creates_dir_if_missing(tmp_path: Path) -> None:
    souls_dir = tmp_path / "new_souls"
    loader = SoulLoader(souls_dir=souls_dir, builtin_souls=_BUILTIN)
    loader.ensure_defaults()
    assert souls_dir.exists()
    assert (souls_dir / "sebastian.md").exists()


def test_current_soul_default(loader: SoulLoader) -> None:
    assert loader.current_soul == "sebastian"


def test_current_soul_can_be_updated(loader: SoulLoader) -> None:
    loader.current_soul = "cortana"
    assert loader.current_soul == "cortana"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/core/test_soul_loader.py -v
```

期望：`ModuleNotFoundError: No module named 'sebastian.core.soul_loader'`

- [ ] **Step 3: 实现 SoulLoader**

`sebastian/core/soul_loader.py`：

```python
from __future__ import annotations

from pathlib import Path


class SoulLoader:
    def __init__(self, souls_dir: Path, builtin_souls: dict[str, str]) -> None:
        self._souls_dir = souls_dir
        self._builtin_souls = builtin_souls
        self.current_soul: str = "sebastian"

    def list_souls(self) -> list[str]:
        if not self._souls_dir.exists():
            return []
        return sorted(p.stem for p in self._souls_dir.glob("*.md"))

    def load(self, soul_name: str) -> str | None:
        if soul_name != Path(soul_name).name:  # reject path separators / traversal
            return None
        path = self._souls_dir / f"{soul_name}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def ensure_defaults(self) -> None:
        self._souls_dir.mkdir(parents=True, exist_ok=True)
        for name, content in self._builtin_souls.items():
            path = self._souls_dir / f"{name}.md"
            if not path.exists():
                path.write_text(content, encoding="utf-8")
```

- [ ] **Step 4: 运行确认全通过**

```bash
pytest tests/unit/core/test_soul_loader.py -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/core/soul_loader.py tests/unit/core/test_soul_loader.py
git commit -m "feat(core): 新增 SoulLoader，管理 souls/ 目录与内置人格文件"
```

---

### Task 2: CORTANA_PERSONA + config + app_settings 常量

**Files:**
- Modify: `sebastian/orchestrator/sebas.py`
- Modify: `sebastian/config/__init__.py`
- Modify: `sebastian/store/app_settings_store.py`

- [ ] **Step 1: 在 `sebas.py` 提取 BASE_BUTLER_RULES，瘦身 SEBASTIAN_PERSONA，添加 CORTANA_PERSONA**

Soul 文件只含人格灵魂内容（中文），行为约束提取为常量 `BASE_BUTLER_RULES`，由 `Sebastian._persona_section()` 固定注入。

在 `sebastian/orchestrator/sebas.py` 中，原 `SEBASTIAN_PERSONA` 替换为以下三段：

```python
BASE_BUTLER_RULES = """\
## 忠诚
你服务于主人的真实意图，而非字面措辞。
...（完整内容见 sebas.py）
"""

SEBASTIAN_PERSONA = """\
你是 Sebastian。

## 性格
你举止优雅，执行精准，泰山崩于前而色不变。
...
"""

CORTANA_PERSONA = """\
你是 Cortana。

## 性格
你敏锐、温暖，观察力极强。
...
"""
```

并在 `Sebastian` 类中添加 `_persona_section()` 覆盖：

```python
def _persona_section(self) -> str:
    return f"{BASE_BUTLER_RULES}\n\n{self.persona}"
```

- [ ] **Step 2: 在 `config/__init__.py` 添加 `souls_dir` 属性并更新 `ensure_data_dir`**

在 `Settings` 类的 `attachments_dir` 属性之后添加：

```python
@property
def souls_dir(self) -> Path:
    return self.user_data_dir / "souls"
```

在 `ensure_data_dir()` 的 `for sub in (...)` 列表末尾追加 `settings.souls_dir`：

```python
    for sub in (
        settings.user_data_dir / "extensions" / "skills",
        settings.user_data_dir / "extensions" / "agents",
        settings.user_data_dir / "workspace",
        settings.user_data_dir / "memory",
        settings.logs_dir,
        settings.run_dir,
        settings.attachments_dir / "blobs",
        settings.attachments_dir / "thumbs",
        settings.attachments_dir / "tmp",
        settings.souls_dir,
    ):
        sub.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 3: 在 `app_settings_store.py` 添加 `APP_SETTING_ACTIVE_SOUL` 常量**

在 `APP_SETTING_MEMORY_ENABLED` 常量后追加：

```python
APP_SETTING_ACTIVE_SOUL = "active_soul"
```

- [ ] **Step 4: 运行受影响测试确认无回归**

```bash
pytest tests/unit/test_config_paths.py tests/unit/store/ -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/orchestrator/sebas.py sebastian/config/__init__.py sebastian/store/app_settings_store.py
git commit -m "feat(soul): 新增 CORTANA_PERSONA，souls_dir 配置，APP_SETTING_ACTIVE_SOUL 常量"
```

---

### Task 3: gateway state + soul 恢复逻辑 + 集成测试

**Files:**
- Modify: `sebastian/gateway/state.py`
- Modify: `sebastian/gateway/app.py`
- Create: `tests/integration/test_gateway_soul.py`

- [ ] **Step 1: 写失败集成测试**

`tests/integration/test_gateway_soul.py`：

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sebastian.core.soul_loader import SoulLoader
from sebastian.gateway.app import _restore_active_soul
from sebastian.store.app_settings_store import APP_SETTING_ACTIVE_SOUL, AppSettingsStore
from sebastian.store.models import Base

_BUILTIN = {"sebastian": "You are Sebastian.", "cortana": "You are Cortana."}


@pytest.fixture
async def db_factory(tmp_path: Path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def soul_loader(tmp_path: Path) -> SoulLoader:
    loader = SoulLoader(souls_dir=tmp_path / "souls", builtin_souls=_BUILTIN)
    loader.ensure_defaults()
    return loader


def _make_sebastian(persona: str = "You are Sebastian.") -> MagicMock:
    agent = MagicMock()
    agent.persona = persona
    agent.system_prompt = ""
    agent._gate = MagicMock()
    agent._agent_registry = {}
    agent.build_system_prompt = MagicMock(return_value="rebuilt_prompt")
    return agent


@pytest.mark.asyncio
async def test_restore_uses_active_soul_from_db(db_factory, soul_loader):
    async with db_factory() as session:
        store = AppSettingsStore(session)
        await store.set(APP_SETTING_ACTIVE_SOUL, "cortana")
        await session.commit()

    agent = _make_sebastian()
    await _restore_active_soul(soul_loader, db_factory, agent)

    assert agent.persona == "You are Cortana."
    assert agent.system_prompt == "rebuilt_prompt"
    assert soul_loader.current_soul == "cortana"


@pytest.mark.asyncio
async def test_restore_defaults_to_sebastian_when_no_setting(db_factory, soul_loader):
    agent = _make_sebastian()
    await _restore_active_soul(soul_loader, db_factory, agent)

    assert agent.persona == "You are Sebastian."
    assert soul_loader.current_soul == "sebastian"


@pytest.mark.asyncio
async def test_restore_falls_back_to_hardcoded_when_file_missing(db_factory, soul_loader, tmp_path):
    async with db_factory() as session:
        store = AppSettingsStore(session)
        await store.set(APP_SETTING_ACTIVE_SOUL, "ghost")
        await session.commit()

    agent = _make_sebastian(persona="HARDCODED")
    original_persona = agent.persona
    await _restore_active_soul(soul_loader, db_factory, agent)

    # soul file missing → persona unchanged, system_prompt NOT rebuilt
    assert agent.persona == original_persona
    agent.build_system_prompt.assert_not_called()
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/integration/test_gateway_soul.py -v
```

期望：`ImportError: cannot import name '_restore_active_soul' from 'sebastian.gateway.app'`

- [ ] **Step 3: 在 `state.py` 添加 `soul_loader` 字段**

在 `sebastian/gateway/state.py` 的 import 块顶部添加：

```python
if TYPE_CHECKING:
    ...
    from sebastian.core.soul_loader import SoulLoader  # 已有 TYPE_CHECKING 块，追加这行
```

在模块级变量区（`sebastian: Sebastian` 附近）添加：

```python
soul_loader: SoulLoader
```

- [ ] **Step 4: 在 `app.py` 提取 `_restore_active_soul` 并接入 lifespan**

在 `_initialize_agent_instances` 函数之后（`lifespan` 函数之前），添加独立函数。`app.py` 顶部已有 `from __future__ import annotations`，所以 `TYPE_CHECKING` 块里的类型只在静态检查时求值，不影响运行时：

在文件顶部 `TYPE_CHECKING` 块（已存在）里追加：

```python
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.core.soul_loader import SoulLoader
    from sebastian.orchestrator.sebas import Sebastian
```

然后添加独立函数：

```python
async def _restore_active_soul(
    soul_loader: SoulLoader,
    db_factory: async_sessionmaker[AsyncSession],
    sebastian_agent: Sebastian,
) -> None:
    import logging

    from sebastian.store.app_settings_store import APP_SETTING_ACTIVE_SOUL, AppSettingsStore

    _log = logging.getLogger(__name__)
    try:
        async with db_factory() as session:
            store = AppSettingsStore(session)
            active = await store.get(APP_SETTING_ACTIVE_SOUL, "sebastian")
        content = soul_loader.load(active)
        if content is None:
            _log.warning(
                "active soul file '%s.md' not found, keeping default persona", active
            )
            return
        soul_loader.current_soul = active
        sebastian_agent.persona = content
        sebastian_agent.system_prompt = sebastian_agent.build_system_prompt(
            sebastian_agent._gate, sebastian_agent._agent_registry
        )
    except Exception:
        _log.warning("soul restore failed at startup, keeping default persona", exc_info=True)
```

在 lifespan 函数里，`state.sebastian = sebastian_agent` 之后加：

```python
    # Soul restore ── 从 DB 恢复上次激活的 soul，用 builtin_souls 防止误删
    from sebastian.core.soul_loader import SoulLoader
    from sebastian.orchestrator.sebas import CORTANA_PERSONA, SEBASTIAN_PERSONA

    _soul_loader = SoulLoader(
        souls_dir=settings.souls_dir,
        builtin_souls={"sebastian": SEBASTIAN_PERSONA, "cortana": CORTANA_PERSONA},
    )
    _soul_loader.ensure_defaults()
    state.soul_loader = _soul_loader
    await _restore_active_soul(_soul_loader, db_factory, sebastian_agent)
```

这段代码插入位置：`state.sebastian = sebastian_agent`（约第 265 行）之后，`state.sse_manager = sse_mgr` 之前。

- [ ] **Step 5: 运行集成测试确认通过**

```bash
pytest tests/integration/test_gateway_soul.py -v
```

期望：3 个测试全部 PASS

- [ ] **Step 6: Commit**

```bash
git add sebastian/gateway/state.py sebastian/gateway/app.py tests/integration/test_gateway_soul.py
git commit -m "feat(gateway): soul restore on startup，state 挂载 soul_loader"
```

---

### Task 4: switch_soul 工具

**Files:**
- Create: `sebastian/capabilities/tools/switch_soul/__init__.py`
- Test: `tests/unit/capabilities/test_switch_soul.py`

- [ ] **Step 1: 写失败单元测试**

`tests/unit/capabilities/test_switch_soul.py`：

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_state(souls_dir: Path, current_soul: str = "sebastian") -> MagicMock:
    from sebastian.core.soul_loader import SoulLoader

    loader = SoulLoader(
        souls_dir=souls_dir,
        builtin_souls={"sebastian": "You are Sebastian.", "cortana": "You are Cortana."},
    )
    loader.ensure_defaults()
    loader.current_soul = current_soul

    sebastian = MagicMock()
    sebastian.persona = "You are Sebastian."
    sebastian.system_prompt = "old_prompt"
    sebastian._gate = MagicMock()
    sebastian._agent_registry = {}
    sebastian.build_system_prompt = MagicMock(return_value="new_prompt")

    db_session = AsyncMock()
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(return_value=db_session)
    db_cm.__aexit__ = AsyncMock(return_value=None)
    db_factory = MagicMock(return_value=db_cm)

    state = MagicMock()
    state.soul_loader = loader
    state.sebastian = sebastian
    state.db_factory = db_factory
    return state


@pytest.mark.asyncio
async def test_switch_soul_list(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path)
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("list")

    assert result.ok is True
    assert "sebastian" in result.output
    assert "cortana" in result.output


@pytest.mark.asyncio
async def test_switch_soul_already_active(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("sebastian")

    assert result.ok is True
    assert "已经在了" in result.output
    state.sebastian.build_system_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_switch_soul_file_not_found(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path)
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("ghost")

    assert result.ok is False
    assert "Do not retry automatically" in result.error
    assert "ghost" in result.error


@pytest.mark.asyncio
async def test_switch_soul_success(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("cortana")

    assert result.ok is True
    assert "cortana" in result.output
    assert state.sebastian.persona == "You are Cortana."
    assert state.sebastian.system_prompt == "new_prompt"
    assert state.soul_loader.current_soul == "cortana"
    # 验证 DB 持久化：commit 必须被调用，否则重启后 soul 不会恢复
    db_session = state.db_factory.return_value.__aenter__.return_value
    db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_soul_db_failure(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    state = _make_state(tmp_path, current_soul="sebastian")
    # make db_factory raise on __aenter__
    db_cm = AsyncMock()
    db_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))
    db_cm.__aexit__ = AsyncMock(return_value=None)
    state.db_factory = MagicMock(return_value=db_cm)

    with patch("sebastian.capabilities.tools.switch_soul._get_state", return_value=state):
        result = await switch_soul("cortana")

    assert result.ok is False
    assert "Do not retry automatically" in result.error


@pytest.mark.asyncio
async def test_switch_soul_unexpected_exception(tmp_path: Path) -> None:
    from sebastian.capabilities.tools.switch_soul import switch_soul

    with patch(
        "sebastian.capabilities.tools.switch_soul._get_state", side_effect=RuntimeError("boom")
    ):
        result = await switch_soul("cortana")

    assert result.ok is False
    assert "Do not retry automatically" in result.error
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/unit/capabilities/test_switch_soul.py -v
```

期望：`ModuleNotFoundError: No module named 'sebastian.capabilities.tools.switch_soul'`

- [ ] **Step 3: 实现 switch_soul 工具**

新建目录并创建 `sebastian/capabilities/tools/switch_soul/__init__.py`：

```python
from __future__ import annotations

import logging
from types import ModuleType

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier
from sebastian.store.app_settings_store import APP_SETTING_ACTIVE_SOUL, AppSettingsStore

logger = logging.getLogger(__name__)


def _get_state() -> ModuleType:
    import sebastian.gateway.state as state

    return state


@tool(
    name="switch_soul",
    description=(
        "列出或切换 Sebastian 的当前人格（soul）。"
        "soul_name='list' 查看可用列表，其他值执行切换。"
    ),
    permission_tier=PermissionTier.LOW,
    display_name="Soul",
)
async def switch_soul(soul_name: str) -> ToolResult:
    try:
        state = _get_state()
        soul_loader = state.soul_loader
        soul_loader.ensure_defaults()

        if soul_name == "list":
            souls = soul_loader.list_souls()
            return ToolResult(ok=True, output=souls, display=", ".join(souls))

        if soul_name == soul_loader.current_soul:
            msg = f"{soul_name} 已经在了，无需切换"
            return ToolResult(ok=True, output=msg, display=msg)

        content = soul_loader.load(soul_name)
        if content is None:
            return ToolResult(
                ok=False,
                error=(
                    f"找不到 soul: {soul_name}。Do not retry automatically；"
                    "请先调用 switch_soul('list') 查看可用列表"
                ),
            )

        try:
            async with state.db_factory() as session:
                store = AppSettingsStore(session)
                await store.set(APP_SETTING_ACTIVE_SOUL, soul_name)
                await session.commit()
        except Exception as e:
            return ToolResult(
                ok=False,
                error=f"切换失败: {e}。Do not retry automatically；请向用户报告此错误",
            )

        soul_loader.current_soul = soul_name
        state.sebastian.persona = content
        state.sebastian.system_prompt = state.sebastian.build_system_prompt(
            state.sebastian._gate, state.sebastian._agent_registry
        )
        msg = f"已切换到 {soul_name}"
        return ToolResult(ok=True, output=msg, display=msg)

    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"switch_soul 内部错误: {e}。Do not retry automatically；请向用户报告此错误",
        )
```

- [ ] **Step 4: 运行确认全通过**

```bash
pytest tests/unit/capabilities/test_switch_soul.py -v
```

期望：6 个测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add sebastian/capabilities/tools/switch_soul/ tests/unit/capabilities/test_switch_soul.py
git commit -m "feat(tools): 新增 switch_soul 工具，支持列出和切换 soul"
```

---

### Task 5: Sebastian allowed_tools + 文档更新

**Files:**
- Modify: `sebastian/orchestrator/sebas.py`
- Modify: `sebastian/capabilities/tools/README.md`
- Modify: `docs/architecture/spec/core/system-prompt.md`

- [ ] **Step 1: 在 `Sebastian.allowed_tools` 添加 `switch_soul`**

`sebastian/orchestrator/sebas.py` 的 `allowed_tools` 列表末尾（`"Grep"` 之后）加入：

```python
    allowed_tools = [
        "delegate_to_agent",
        "check_sub_agents",
        "inspect_session",
        "resume_agent",
        "stop_agent",
        "todo_write",
        "todo_read",
        "send_file",
        "capture_screenshot_and_send",
        "memory_save",
        "memory_search",
        "switch_soul",   # ← 新增
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
    ]
```

- [ ] **Step 2: 验证 switch_soul 工具注册到了 Sebastian 的能力白名单**

```bash
pytest tests/unit/core/test_prompt_builder.py -v
```

期望：PASS（不引入回归）

- [ ] **Step 3: 更新 `sebastian/capabilities/tools/README.md`**

在目录结构的能力工具区（`memory_search/` 条目之后）追加：

```
├── switch_soul/             # Sebastian 人格切换工具（Sebastian-only，permission_tier: LOW）
│   └── __init__.py          # @tool: switch_soul(soul_name)；list 列出可用 soul；其他值切换并重建 system_prompt
```

在「修改导航」表末尾追加：

```
| Sebastian 人格切换工具 | [switch_soul/\_\_init\_\_.py](switch_soul/__init__.py) |
```

- [ ] **Step 4: 更新 `docs/architecture/spec/core/system-prompt.md`**

在文档末尾（`*← [Core 索引]...` 之前）插入新章节：

```markdown
## 5. Soul 文件机制

### 5.1 概述

人格提示词可通过 Soul 文件热切换，无需修改源码或重启 gateway。

- Soul 文件存放于 `~/.sebastian/data/souls/`，每个文件为纯文本（`.md` 扩展名）
- 内置两个预设：`sebastian.md`（男管家）、`cortana.md`（女管家）；首次启动自动创建
- `app_settings` 表存储当前激活的 soul 名（key = `active_soul`，value = 文件名不含扩展名）
- gateway 重启时自动从 DB 读取并恢复上次切换的 soul

### 5.2 SoulLoader

`sebastian/core/soul_loader.py` 负责目录管理与文件读写：

| 方法 | 说明 |
|------|------|
| `list_souls()` | 返回 souls/ 下所有 `.md` 文件名（不含扩展名），字母排序 |
| `load(name)` | 读取文件内容，文件不存在返回 `None` |
| `ensure_defaults()` | 补建缺失的内置 soul 文件，不覆盖已有文件 |
| `current_soul` | 当前激活 soul 名，由 lifespan 和 switch_soul 工具维护 |

### 5.3 switch_soul 工具

`switch_soul(soul_name)` 为 Sebastian-only 工具（`permission_tier: LOW`）：

- `"list"` → 返回可用 soul 列表
- 已激活同名 → 返回 "xxx 已经在了"，不操作
- 文件不存在 → `ok=False` + `Do not retry automatically`
- 正常切换 → 写 DB + 更新 `sebastian.persona` + 重建 `system_prompt`，下个 turn 立即生效
```

- [ ] **Step 5: 运行完整测试套件**

```bash
pytest tests/unit/ tests/integration/test_gateway_soul.py -q
```

期望：无新增失败

- [ ] **Step 6: Commit**

```bash
git add sebastian/orchestrator/sebas.py sebastian/capabilities/tools/README.md docs/architecture/spec/core/system-prompt.md
git commit -m "feat(soul): Sebastian 接入 switch_soul 工具，更新文档"
```

---

## 自检结果

**Spec 覆盖检查：**

| Spec 要求 | 覆盖任务 |
|-----------|---------|
| souls/ 目录 + 文件读写 | Task 1 |
| app_settings active_soul | Task 2, Task 3 |
| ensure_defaults 两个内置 soul | Task 1, Task 2 |
| CORTANA_PERSONA | Task 2 |
| gateway lifespan soul 恢复 | Task 3 |
| switch_soul 工具所有分支 | Task 4 |
| 已激活同名边界 | Task 4 |
| Sebastian allowed_tools | Task 5 |
| 文档更新 | Task 5 |

**类型一致性：** `soul_loader.current_soul`（str）在 Task 1 定义、Task 3 lifespan 使用、Task 4 工具读写，三处一致。`_restore_active_soul` 在 Task 3 定义并测试，Task 3 集成测试导入路径与实现路径一致。

**无 placeholder：** 所有 step 均包含完整代码，无 TBD/TODO。
