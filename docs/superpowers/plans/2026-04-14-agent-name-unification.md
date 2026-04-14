# Agent 命名统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 Sub-Agent 的 `display_name` 二元命名，让每个 agent 只有一个名字 `agent_type`（小写 identifier），UI title-case 展示由前端做；同时把 `code` sub-agent 重命名为 `forge`。

**Architecture:** 后端 `AgentConfig` 删 `display_name` 字段，manifest.toml 废弃 `name`；所有 backend 调用点改用 `agent_type`（对外展示前 `.capitalize()`）。Android/Web DTO 删 `name`，改用 `agentType.replaceFirstChar { uppercase }`（Kotlin）/ `titleCase(id)`（TS）。orchestrator system prompt 简化。历史磁盘数据用户手动迁移，gateway 启动对孤儿目录打 warning。

**Tech Stack:** Python 3.12 / FastAPI / pytest / ruff / mypy；Kotlin / Jetpack Compose / JUnit4 / Moshi / Hilt；TypeScript / React Native。

**Spec：** [docs/superpowers/specs/2026-04-14-agent-name-unification-design.md](docs/superpowers/specs/2026-04-14-agent-name-unification-design.md)

---

## 前置说明

- 工作分支：`dev`（不开 worktree，项目规则禁止随意拉分支）
- 所有 commit 遵循项目规范：`类型(范围): 中文摘要` + `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
- 每个任务结束跑对应验证；Task 8 / Task 13 / Task 17 是集中验证点
- Android 单测由本会话跑，APK install 由用户自行完成

---

## Task 1: 重命名 `sebastian/agents/code/` → `sebastian/agents/forge/`

**Files:**
- Rename directory: `sebastian/agents/code/` → `sebastian/agents/forge/`
- Modify: `sebastian/agents/forge/__init__.py`
- Modify: `sebastian/agents/forge/manifest.toml`

- [ ] **Step 1: git mv 整个目录**

```bash
git mv sebastian/agents/code sebastian/agents/forge
```

- [ ] **Step 2: 修改 `sebastian/agents/forge/__init__.py` 类名和 name**

替换原内容的前 7 行：

```python
from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class ForgeAgent(BaseAgent):
    name = "forge"
```

persona 文本保留不变。

- [ ] **Step 3: 修改 `sebastian/agents/forge/manifest.toml`**

新内容：

```toml
[agent]
class_name = "ForgeAgent"
description = "编写代码、调试问题、构建工具"
max_children = 5
stalled_threshold_minutes = 5
allowed_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
allowed_skills = []
```

（删除 `name = "Forge"` 行）

- [ ] **Step 4: 验证目录能被 loader 扫到**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && python -c "from sebastian.agents._loader import load_agents; [print(c.agent_type, c.agent_class.__name__) for c in load_agents()]"
```
Expected: `forge ForgeAgent`（display_name 字段此时仍存在但值为 `agent_type`，下个任务才移除；此处只验证 class 加载正常）

- [ ] **Step 5: Commit**

```bash
git add sebastian/agents/forge/
git commit -m "$(cat <<'EOF'
refactor(agents): 重命名 code sub-agent 为 forge

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 从 `AgentConfig` 移除 `display_name` 字段

**Files:**
- Modify: `sebastian/agents/_loader.py`

- [ ] **Step 1: 修改 `AgentConfig` dataclass 删除 display_name**

`sebastian/agents/_loader.py` 第 15-25 行替换为：

```python
@dataclass
class AgentConfig:
    agent_type: str
    name: str  # agent class name (e.g. "ForgeAgent")
    description: str
    max_children: int  # max concurrent depth=3 sessions
    stalled_threshold_minutes: int  # stalled detection threshold in minutes
    agent_class: type[BaseAgent]
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
```

- [ ] **Step 2: 修改构造 AgentConfig 的代码块**

`sebastian/agents/_loader.py` 第 76-86 行替换为：

```python
            configs[agent_type] = AgentConfig(
                agent_type=agent_type,
                name=agent_section.get("class_name", agent_type),
                description=agent_section.get("description", ""),
                max_children=int(agent_section.get("max_children", 5)),
                stalled_threshold_minutes=int(agent_section.get("stalled_threshold_minutes", 5)),
                agent_class=agent_class,
                allowed_tools=list(raw_tools) if raw_tools is not None else None,
                allowed_skills=list(raw_skills) if raw_skills is not None else None,
            )
```

（删除 `display_name=agent_section.get("name", agent_section.get("class_name", agent_type)),` 行）

- [ ] **Step 3: 验证 loader 仍工作**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && python -c "from sebastian.agents._loader import load_agents; c = load_agents()[0]; print(c.agent_type, c.name, c.description); assert not hasattr(c, 'display_name'), 'display_name should be removed'"
```
Expected: `forge ForgeAgent 编写代码、调试问题、构建工具` 且不抛错

- [ ] **Step 4: Commit**

```bash
git add sebastian/agents/_loader.py
git commit -m "$(cat <<'EOF'
refactor(agents): 从 AgentConfig 移除 display_name 字段

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 更新 `delegate_to_agent` 工具及其测试

**Files:**
- Modify: `sebastian/capabilities/tools/delegate_to_agent/__init__.py:44-45,73`
- Modify: `tests/unit/capabilities/test_tool_delegate.py`

- [ ] **Step 1: 修改 delegate_to_agent 工具实现**

`sebastian/capabilities/tools/delegate_to_agent/__init__.py` 第 44-45 行替换为（直接删掉 config 和 display_name 两行）：

```python
    if agent_type not in state.agent_instances:
        return ToolResult(ok=False, error=f"未知的 Agent 类型: {agent_type}")

    session = Session(
```

然后 第 73 行（`return ToolResult(...)`）替换为：

```python
    return ToolResult(ok=True, output=f"已安排 {agent_type.capitalize()} 处理：{goal}")
```

- [ ] **Step 2: 更新 test_tool_delegate.py 的断言和 mock**

`tests/unit/capabilities/test_tool_delegate.py` 第 15-17 行替换为：

```python
    mock_state.agent_registry = {
        "forge": MagicMock(max_children=5),
    }
```

第 14 行 `mock_state.agent_instances = {"code": mock_agent}` 改为 `{"forge": mock_agent}`

第 26 行 `agent_type="code"` 改为 `agent_type="forge"`

第 32 行 `assert "铁匠" in result.output` 改为 `assert "Forge" in result.output`

同样更新 `test_delegate_creates_background_task` 测试：
- 第 65 行 `{"code": mock_agent}` → `{"forge": mock_agent}`
- 第 66-68 行的 `agent_registry` mock 改为：
  ```python
  mock_state.agent_registry = {
      "forge": MagicMock(max_children=5),
  }
  ```
- 第 81 行 `agent_type="code"` → `agent_type="forge"`

- [ ] **Step 3: 跑测试验证**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && pytest tests/unit/capabilities/test_tool_delegate.py -v
```
Expected: 3 passed

- [ ] **Step 4: Commit**

```bash
git add sebastian/capabilities/tools/delegate_to_agent/__init__.py tests/unit/capabilities/test_tool_delegate.py
git commit -m "$(cat <<'EOF'
refactor(tools): delegate_to_agent 直接用 agent_type 生成返回文案

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 更新 `completion_notifier.py`

**Files:**
- Modify: `sebastian/gateway/completion_notifier.py:103-128`

- [ ] **Step 1: 改通知文案生成逻辑**

第 103-128 行的 `_build_notification` 方法替换为（删除 `config` 查表和 `display_name` 变量，直接用 `agent_type.capitalize()`）：

```python
    async def _build_notification(self, event_type: EventType, data: dict[str, Any]) -> str | None:
        session_id = data.get("session_id", "")
        agent_type = data.get("agent_type", "")
        goal = data.get("goal", "未知目标")
        display = agent_type.capitalize() if agent_type else ""

        if event_type == EventType.SESSION_WAITING:
            question = data.get("question", "（未提供问题内容）")
            return (
                f"[内部通知] 子代理 {display} 遇到问题，需要你的指示\n"
                f"目标：{goal}\n"
                f"问题：{question}\n"
                f"session_id：{session_id}（回复请使用 reply_to_agent 工具）"
            )

        # COMPLETED / FAILED
        last_report = await self._get_last_assistant_message(session_id, agent_type)
        status_label = "完成" if event_type == EventType.SESSION_COMPLETED else "失败"
        return (
            f"[内部通知] 子代理 {display} 已{status_label}任务\n"
            f"目标：{goal}\n"
            f"状态：{data.get('status', '')}\n"
            f"汇报：{last_report}\n"
            f"session_id：{session_id}（可用 inspect_session 查看详情）"
        )
```

（注意：`self._agent_registry` 的 import/依赖可能变成未使用——Step 2 处理）

- [ ] **Step 2: 检查并清理未使用的 agent_registry 依赖**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -n "agent_registry" sebastian/gateway/completion_notifier.py
```

如果只剩构造函数参数和一处 `self._agent_registry = agent_registry`，保留（该字段目前无其他用途但可留作未来扩展点——或者一并删除，以避免死字段）。

倾向**保留**（删除会涉及 `app.py` 构造调用签名变更，溢出当前任务范围）。只注释化或什么都不做。

- [ ] **Step 3: 手动冒烟验证无 display_name 引用**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -n "display_name" sebastian/gateway/completion_notifier.py
```
Expected: 无输出

- [ ] **Step 4: Commit**

```bash
git add sebastian/gateway/completion_notifier.py
git commit -m "$(cat <<'EOF'
refactor(gateway): completion_notifier 用 agent_type.capitalize() 生成通知文案

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 更新 `/agents` 路由

**Files:**
- Modify: `sebastian/gateway/routes/agents.py:27-35`

- [ ] **Step 1: 删除 JSON 返回里的 `name` 字段**

`sebastian/gateway/routes/agents.py` 第 27-35 行替换为：

```python
        agents.append(
            {
                "agent_type": agent_type,
                "description": config.description,
                "active_session_count": active_count,
                "max_children": config.max_children,
            }
        )
```

- [ ] **Step 2: 检查是否有其他代码依赖 response 的 `name` 字段**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -rn '"name"' sebastian/gateway/routes/ tests/
```

Expected：仅无关匹配（不涉及 agents 列表的结构）

- [ ] **Step 3: Commit**

```bash
git add sebastian/gateway/routes/agents.py
git commit -m "$(cat <<'EOF'
refactor(gateway): /agents 接口移除 name 字段

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 更新 gateway 启动日志 + 孤儿目录 warning

**Files:**
- Modify: `sebastian/gateway/app.py:43` (log tweak)
- Modify: `sebastian/gateway/app.py:140-145` 附近（lifespan 内 state 装配完后加 warning 检查）

- [ ] **Step 1: 修改启动日志**

`sebastian/gateway/app.py:43` 替换：

```python
        logger.info("Registered agent instance: %s", cfg.agent_type)
```

- [ ] **Step 2: 加孤儿 session 目录自检**

在 `sebastian/gateway/app.py` 的 `lifespan` 函数里，**在 `state.agent_instances = _initialize_agent_instances(...)` 之后、`watchdog_task = start_watchdog(...)` 之前**插入：

```python
    # 孤儿 session 目录提醒（agent 重命名后遗留数据）
    sessions_dir = settings.sessions_dir
    if sessions_dir.exists():
        known = {"sebastian", *state.agent_registry.keys()}
        orphans = [d.name for d in sessions_dir.iterdir() if d.is_dir() and d.name not in known]
        if orphans:
            logger.warning(
                "Found orphan session dirs (not in registry): %s. "
                "Likely from a renamed agent. See CHANGELOG for migration.",
                orphans,
            )
```

- [ ] **Step 3: 验证 gateway 启动无报错**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && python -c "
import asyncio
from sebastian.gateway.app import lifespan
from fastapi import FastAPI
app = FastAPI()
async def check():
    async with lifespan(app):
        print('lifespan entered OK')
asyncio.run(check())
" 2>&1 | tail -5
```
Expected: 输出包含 `lifespan entered OK` 或其他非崩溃日志。如果报错涉及 DB / secret.key 缺失，视为预期（dev 环境未初始化），跳过此步——重点是语法层无 crash。

- [ ] **Step 4: Commit**

```bash
git add sebastian/gateway/app.py
git commit -m "$(cat <<'EOF'
feat(gateway): 启动时对 sessions/ 下孤儿目录打 warning

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 简化 orchestrator system prompt + 新增单测

**Files:**
- Modify: `sebastian/orchestrator/sebas.py:102-116`
- Modify: `tests/unit/core/test_prompt_builder.py`（新增测试）

- [ ] **Step 1: 先写失败的单测**

在 `tests/unit/core/test_prompt_builder.py` 末尾新增（注意 imports 如 `CapabilityRegistry` / `SessionStore` 已在文件顶部存在；参考现有 test 复用）：

```python
@pytest.mark.asyncio
async def test_sebastian_agents_section_renders_agent_type_only(tmp_path: Path) -> None:
    from dataclasses import dataclass

    from sebastian.orchestrator.sebas import Sebastian

    @dataclass
    class FakeCfg:
        agent_type: str
        description: str

    registry = {"forge": FakeCfg(agent_type="forge", description="编写代码")}
    store = SessionStore(tmp_path / "sessions")
    reg = CapabilityRegistry()

    with patch("anthropic.AsyncAnthropic", return_value=MagicMock()):
        with patch("sebastian.core.base_agent.settings") as mock_settings:
            mock_settings.sebastian_owner_name = "Eric"
            mock_settings.sebastian_model = "claude-opus-4-6"
            mock_settings.anthropic_api_key = "test"
            mock_settings.llm_max_tokens = 16000
            # Sebastian constructor 需要额外依赖，用 _agents_section 独立测更干净
            section = Sebastian._agents_section(Sebastian.__new__(Sebastian), registry)

    assert "- forge:" in section
    assert "编写代码" in section
    assert "display name" not in section.lower()
    assert "agent_type=" not in section
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && pytest tests/unit/core/test_prompt_builder.py::test_sebastian_agents_section_renders_agent_type_only -v
```
Expected: FAIL（因为 `_agents_section` 仍然输出 `- Forge (agent_type="forge")...`）

- [ ] **Step 3: 改 `_agents_section` 让测试通过**

`sebastian/orchestrator/sebas.py:102-116` 替换为：

```python
    def _agents_section(self, agent_registry: Mapping[str, Any] | None = None) -> str:
        registry = agent_registry or self._agent_registry
        if not registry:
            return ""
        lines = ["## Available Sub-Agents", ""]
        for config in registry.values():
            desc = getattr(config, "description", "")
            lines.append(f"- {config.agent_type}: {desc}")
        lines.append("")
        lines.append(
            "Use the `delegate_to_agent` tool to assign tasks. "
            "Pass the agent name as `agent_type`."
        )
        return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && pytest tests/unit/core/test_prompt_builder.py -v
```
Expected: 所有测试 PASS，包括新增的 `test_sebastian_agents_section_renders_agent_type_only`

- [ ] **Step 5: Commit**

```bash
git add sebastian/orchestrator/sebas.py tests/unit/core/test_prompt_builder.py
git commit -m "$(cat <<'EOF'
refactor(orchestrator): 简化 agent roster，移除 display_name 双名指令

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 后端集中验证（lint + type + test）

**Files:** 无（只跑检查）

- [ ] **Step 1: ruff check**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && ruff check sebastian/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 2: ruff format check**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && ruff format --check sebastian/ tests/
```
Expected: 无 "Would reformat" 输出。如有，运行 `ruff format sebastian/ tests/` 并加入下一次 commit。

- [ ] **Step 3: mypy**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && mypy sebastian/
```
Expected: 无新增 error。如有 `display_name` / `code` 相关 error，修掉。

- [ ] **Step 4: 全量单测**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && pytest tests/unit/ -x --timeout=30
```
Expected: 全部 PASS。若有依赖 `display_name` / `"code"` 的测试遗漏，修正并加入 commit。

- [ ] **Step 5: 集成测试**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && pytest tests/integration/ -x --timeout=60
```
Expected: 全部 PASS 或跳过（取决于本地环境）。如有涉及 `/agents` 响应结构的集成测试 fail，修正断言。

- [ ] **Step 6: 如果 Step 2 或 Step 4-5 触发了代码修改，commit**

```bash
# 仅当有修改时执行
git add -u
git commit -m "$(cat <<'EOF'
test: 同步更新 agent 重命名后的测试断言

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Android — `AgentDto` / `AgentInfo` 去除 `name`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentDto.kt`
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AgentInfo.kt`

- [ ] **Step 1: 修改 `AgentDto.kt`**

全文替换为：

```kotlin
package com.sebastian.android.data.remote.dto

import com.sebastian.android.data.model.AgentInfo
import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class AgentListResponse(
    @param:Json(name = "agents") val agents: List<AgentDto>,
)

@JsonClass(generateAdapter = true)
data class AgentDto(
    @param:Json(name = "agent_type") val agentType: String,
    @param:Json(name = "description") val description: String,
    @param:Json(name = "active_session_count") val activeSessionCount: Int = 0,
    @param:Json(name = "max_children") val maxChildren: Int = 0,
) {
    fun toDomain() = AgentInfo(
        agentType = agentType,
        description = description,
        activeSessionCount = activeSessionCount,
        maxChildren = maxChildren,
    )
}
```

- [ ] **Step 2: 修改 `AgentInfo.kt`**

全文替换为：

```kotlin
package com.sebastian.android.data.model

data class AgentInfo(
    val agentType: String,
    val description: String,
    val activeSessionCount: Int = 0,
    val maxChildren: Int = 0,
) {
    val isActive: Boolean get() = activeSessionCount > 0

    /** UI 展示用：agent_type 首字母大写。 */
    val displayName: String get() = agentType.replaceFirstChar { it.uppercase() }
}
```

- [ ] **Step 3: Commit（先 commit 数据层，下个任务改 UI 消费者）**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/data/
git commit -m "$(cat <<'EOF'
refactor(android): AgentInfo 移除 name 字段，新增 displayName 扩展

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

> 注意：此 commit 之后代码会暂时编译失败（AgentListScreen 还在用 `agent.name`），Task 10 修复。若想保持每个 commit 可编译，把 Task 9 和 Task 10 合并成一次 commit——推荐合并。

---

## Task 10: Android — 更新 `AgentListScreen` 使用 `displayName`

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt:63-67`

- [ ] **Step 1: 替换 `agent.name` 为 `agent.displayName`**

第 63 行 `Text(agent.name)` → `Text(agent.displayName)`

第 66 行 `Route.AgentChat(agentId = agent.agentType, agentName = agent.name)` → `Route.AgentChat(agentId = agent.agentType, agentName = agent.displayName)`

- [ ] **Step 2: 编译验证**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew :app:compileDebugKotlin
```
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit（与 Task 9 合并：使用 `git commit --amend` 把 Task 10 的改动并进去，保持 commit 原子）**

方案 A（推荐，合并）：
```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt
git commit --amend --no-edit
```

方案 B（分开 commit）：
```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt
git commit -m "$(cat <<'EOF'
refactor(android): AgentListScreen 用 displayName 展示 agent

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Android — `ToolCallInputExtractor` 移除 uppercase 特例

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt:38-44`
- Modify: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolCallInputExtractorTest.kt`

- [ ] **Step 1: 简化 `extractInputSummary`**

`ToolCallInputExtractor.kt:36-45` 替换为：

```kotlin
        val keys = KEY_PRIORITY[name] ?: GENERIC_KEYS
        for (key in keys) {
            val value = parsed.optStringOrNull(key) ?: continue
            return truncate(value)
        }
```

（删除 `delegate_to_agent` + `agent_type` 的 uppercase 判断分支；`return truncate(shaped)` 变成 `return truncate(value)`）

- [ ] **Step 2: 更新 `extractKeyParams` 文件顶部注释（如有提及 delegate_to_agent 大小写行为）**

检查 `ToolCallInputExtractor.kt` 文件顶部的 KDoc，把这条删掉：
```
 * - `delegate_to_agent` 摘要显示子代理名（首字母大写），而不是 goal
```
改成：
```
 * - `delegate_to_agent` 摘要显示子代理 agent_type（原值），title-case 由 ToolDisplayName 负责
```

- [ ] **Step 3: 更新单测断言**

在 `ToolCallInputExtractorTest.kt` 里找到 `delegate_to_agent` 相关测试 case，把期望的首字母大写结果改为原值小写（例如 `"Forge"` 改 `"forge"` 或 `"Code"` 改 `"code"`）。

具体做法：
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -n "delegate_to_agent\|replaceFirstChar\|uppercase" ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolCallInputExtractorTest.kt
```

然后对每一条 case 人工改断言：期望的摘要字符串改成 `inputs` JSON 里的原始 `agent_type` 值（不做大写）。

- [ ] **Step 4: 跑单测**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ToolCallInputExtractorTest"
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolCallInputExtractorTest.kt
git commit -m "$(cat <<'EOF'
refactor(android): ToolCallInputExtractor 去掉 delegate_to_agent 的 uppercase 特例

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Android — `ToolDisplayName` 承担 title-case + 新增测试

**Files:**
- Modify: `ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt:22-29`
- Create: `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt`

- [ ] **Step 1: 先写 ToolDisplayNameTest.kt**

新建 `ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt`：

```kotlin
package com.sebastian.android.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class ToolDisplayNameTest {

    @Test
    fun `delegate_to_agent title capitalizes agent_type`() {
        val r = ToolDisplayName.resolve(
            toolName = "delegate_to_agent",
            inputs = """{"agent_type":"forge","goal":"写个网页"}""",
        )
        assertEquals("Agent: Forge", r.title)
        assertEquals("", r.summary)
    }

    @Test
    fun `delegate_to_agent with empty inputs still formats header`() {
        val r = ToolDisplayName.resolve(
            toolName = "delegate_to_agent",
            inputs = "",
        )
        assertEquals("Agent: ", r.title)
    }

    @Test
    fun `spawn_sub_agent uses Worker title and goal summary`() {
        val r = ToolDisplayName.resolve(
            toolName = "spawn_sub_agent",
            inputs = """{"goal":"做件小事"}""",
        )
        assertEquals("Worker", r.title)
        assertEquals("做件小事", r.summary)
    }

    @Test
    fun `unknown tool falls through to toolName as title`() {
        val r = ToolDisplayName.resolve(
            toolName = "Read",
            inputs = """{"file_path":"/tmp/x.txt"}""",
        )
        assertEquals("Read", r.title)
        assertEquals("/tmp/x.txt", r.summary)
    }
}
```

- [ ] **Step 2: 跑测试确认 `delegate_to_agent title` case 失败**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ToolDisplayNameTest"
```
Expected: `delegate_to_agent title capitalizes agent_type` FAIL（当前 title 是 `Agent: forge`，因为 Task 11 移除了 extractor 里的 uppercase）

- [ ] **Step 3: 改 ToolDisplayName.resolve 让测试通过**

`ToolDisplayName.kt:22-29` 替换为：

```kotlin
    fun resolve(toolName: String, inputs: String): Display {
        val rawSummary = ToolCallInputExtractor.extractInputSummary(toolName, inputs)
        return when (toolName) {
            "delegate_to_agent" -> {
                val agentDisplay = rawSummary.replaceFirstChar { it.uppercase() }
                Display(title = "Agent: $agentDisplay", summary = "")
            }
            "spawn_sub_agent" -> Display(title = "Worker", summary = rawSummary)
            else -> Display(title = toolName, summary = rawSummary)
        }
    }
```

- [ ] **Step 4: 跑测试确认全绿**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew :app:testDebugUnitTest --tests "com.sebastian.android.ui.chat.ToolDisplayNameTest"
```
Expected: 4 tests passed

- [ ] **Step 5: Commit**

```bash
git add ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolDisplayNameTest.kt
git commit -m "$(cat <<'EOF'
feat(android): ToolDisplayName 承担 delegate_to_agent 的 title-case 展示

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Android — 全量单测验证

**Files:** 无

- [ ] **Step 1: 全量单测**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew :app:testDebugUnitTest
```
Expected: BUILD SUCCESSFUL，所有测试 pass。如有 mock 构造 `AgentInfo(name = ...)` 的 ViewModel 测试残留，修正后再次 commit。

- [ ] **Step 2: lint**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew :app:lintDebug
```
Expected: BUILD SUCCESSFUL，无新增 error（warning 容忍）

- [ ] **Step 3: 如果 Step 1-2 触发代码修改，commit**

```bash
# 仅在有修改时
git add -u
git commit -m "$(cat <<'EOF'
test(android): 同步 agent name 统一后的测试 mock

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Web 端（`ui/mobile/`）同步

**Files:**
- Modify: `ui/mobile/src/api/agents.ts:16-25`
- Modify: `ui/mobile/src/components/conversation/ToolCallRow.tsx`（如有大小写特例）

- [ ] **Step 1: 修改 `ui/mobile/src/api/agents.ts`**

第 4-10 行 interface 删掉 `name`：

```typescript
interface BackendAgentSummary {
  agent_type: string;
  description: string;
  active_session_count: number;
  max_children: number;
}
```

第 16-25 行 `mapAgentSummary` 改为：

```typescript
function mapAgentSummary(agent: BackendAgentSummary): Agent {
  const displayName = agent.agent_type.charAt(0).toUpperCase() + agent.agent_type.slice(1);
  return {
    id: agent.agent_type,
    name: displayName,
    description: agent.description,
    status: agent.active_session_count > 0 ? 'working' : 'idle',
    active_session_count: agent.active_session_count,
    max_children: agent.max_children,
  };
}
```

- [ ] **Step 2: 检查 `ToolCallRow.tsx` 有无 delegate_to_agent uppercase 特例**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -n "delegate_to_agent\|toUpperCase\|charAt" ui/mobile/src/components/conversation/ToolCallRow.tsx
```

如果有类似 `agent_type.charAt(0).toUpperCase()` 的 delegate_to_agent 专用逻辑，检查是否需要保留（它做的事情和 Android 的 ToolDisplayName 是一样的，应当**保留**——web 端没有独立的 ToolDisplayName，title-case 就在这个组件里做）。

**如果没有，跳过本步。**

- [ ] **Step 3: TypeScript type check（如项目有）**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile && npx tsc --noEmit 2>&1 | head -30
```
Expected: 无新增 error。如果 `Agent` 类型的 `name` 变成必填/可选引发错误，按实际调整。

- [ ] **Step 4: Commit**

```bash
git add ui/mobile/src/api/agents.ts ui/mobile/src/components/conversation/ToolCallRow.tsx
git commit -m "$(cat <<'EOF'
refactor(web): agents 响应移除 name 字段，前端自行 capitalize

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: 文档 README 全仓扫 + 更新

**Files:**
- Modify: `sebastian/agents/README.md`
- Rename + Modify: `sebastian/agents/forge/README.md`（原 `code/README.md`，已被 Task 1 的 git mv 带过来，内容还是 code）
- Modify: `sebastian/orchestrator/README.md`（如涉及 agent roster）
- Modify: `sebastian/gateway/README.md`
- Modify: `sebastian/README.md`
- Modify: `docs/architecture/spec/overview/three-tier-agent.md`
- Modify: `docs/architecture/spec/core/system-prompt.md`
- Modify: 其他命中 `display_name` / `agent_type=.code` / `CodeAgent` 的文件

- [ ] **Step 1: 全仓搜当前相关关键词，生成清单**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -rn "display_name\|CodeAgent\|agents/code\|sebastian\.agents\.code" --include="*.md" --include="*.toml" . | grep -v graphify-out | grep -v ".git/"
```

Expected: 列出所有需要修改的行。

- [ ] **Step 2: 逐个处理 README**

**`sebastian/agents/README.md`**:
- 「如何新增 Sub-Agent」章节里的 `manifest.toml` 示例：删除 `name = "My Agent"  # 用户侧显示名称（display_name）` 行
- 新增说明：
  ```markdown
  > 目录名即 `agent_type`，是系统内部唯一标识。UI 展示时前端对 `agent_type` 做 capitalize（例如 `forge` → `Forge`）。
  > 若希望用不同的显示名（例如本地化），需要同时接受 filesystem / URL / LLM 工具参数等多处使用原 `agent_type`——当前不支持这种差异化。
  ```
- 示例 `agents/code/` 引用改为 `agents/forge/`

**`sebastian/agents/forge/README.md`**（原 code/README.md）：
- 标题 `# code` → `# forge`
- 「目录职责」里 `Code Agent` → `Forge Agent`
- 目录结构树 `code/` → `forge/`
- manifest.toml 示例块：删除 `name = "Forge"` 行，`class_name = "CodeAgent"` → `"ForgeAgent"`

**`sebastian/orchestrator/README.md`**：
- 检查有无 agent roster / display_name 描述，同步到新 prompt 格式

**`sebastian/gateway/README.md`**:
- `state.agent_registry["code"]` 改 `["forge"]`

**`sebastian/README.md`**:
- 顶层 agent 列表里 `code` 改 `forge`

**`docs/architecture/spec/overview/three-tier-agent.md`** / `INDEX.md` / **`docs/architecture/spec/core/system-prompt.md`**：
- 按 Step 1 grep 结果逐条处理
- agent_type / display_name 并列出现的位置，改成"只有 agent_type"叙述
- `code` agent 示例改为 `forge`

- [ ] **Step 3: 验证无遗漏**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -rn "display_name\|CodeAgent\|agents/code\|sebastian\.agents\.code" --include="*.md" --include="*.toml" . | grep -v graphify-out | grep -v ".git/" | grep -v CHANGELOG | grep -v "docs/superpowers"
```
Expected: 无输出（或仅剩历史 CHANGELOG / superpowers spec/plan 文档里的引用——这些保持原样，是历史记录）

- [ ] **Step 4: Commit**

```bash
git add '*.md'
git commit -m "$(cat <<'EOF'
docs: 同步 agent 命名统一（code → forge, 移除 display_name）

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: 写 CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 检查 CHANGELOG 结构**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && head -20 CHANGELOG.md
```
Expected: 能看到 `## [Unreleased]` 或最新版本章节

- [ ] **Step 2: 在 `## [Unreleased]` 下加 `### Breaking Changes`**

如果 `## [Unreleased]` 不存在，就在文件顶部（版权信息之后）插入：

```markdown
## [Unreleased]

### Breaking Changes

- Sub-agent `code` 重命名为 `forge`。同时移除 `manifest.toml` 的 `name` 字段和 `AgentConfig.display_name`——每个 agent 现在只有一个名字 `agent_type`，UI 展示时前端做 capitalize。
- 升级前请处理历史会话数据（任选其一）：

  **选项 A：保留历史（推荐）**
  ```bash
  mv ~/.sebastian/sessions/code ~/.sebastian/sessions/forge
  python3 -c "import json, pathlib; p = pathlib.Path.home()/'.sebastian/sessions/index.json'; d = json.loads(p.read_text()); [e.__setitem__('agent_type','forge') for e in d if e.get('agent_type')=='code']; p.write_text(json.dumps(d, ensure_ascii=False, indent=2))"
  # dev 环境同理（~/.sebastian-dev/）
  ```

  **选项 B：放弃历史**
  ```bash
  rm -rf ~/.sebastian/sessions/code ~/.sebastian-dev/sessions/code
  # 同时手动从 index.json 删除对应条目，或接受 UI 列表出现无法打开的孤儿条目
  ```

- Gateway 启动时会对 `sessions/` 下的孤儿目录（注册表里没有的 agent_type）打 warning 日志，作为提醒。
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(changelog): 记录 agent 命名统一的 breaking change

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: 最终集中验证

**Files:** 无

- [ ] **Step 1: 后端完整验证**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && ruff check sebastian/ tests/ && ruff format --check sebastian/ tests/ && mypy sebastian/ && pytest tests/unit/ -x --timeout=30
```
Expected: 全部通过

- [ ] **Step 2: Android 完整验证**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian/ui/mobile-android && ./gradlew :app:testDebugUnitTest :app:lintDebug
```
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: 文档无残留关键词**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && grep -rn "display_name\|CodeAgent" sebastian/ ui/ docs/architecture/ 2>/dev/null | grep -v __pycache__ | grep -v ".git/"
```
Expected: 无输出。若命中 `docs/architecture/` 里条目，回 Task 15 补齐。

- [ ] **Step 4: 孤儿目录 warning 冒烟验证（可选）**

先在 dev 数据目录制造一个假的孤儿：
```bash
mkdir -p ~/.sebastian-dev/sessions/code
```

启动 gateway 看日志：
```bash
cd /Users/ericw/work/code/ai/sebastian && ./scripts/dev.sh 2>&1 | head -30 | grep -i orphan
```
Expected: 包含 `Found orphan session dirs (not in registry): ['code']` 这样的 warning

结束后清理：
```bash
rmdir ~/.sebastian-dev/sessions/code
```

- [ ] **Step 5: git 状态干净**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && git status
```
Expected: `nothing to commit, working tree clean`

- [ ] **Step 6: 查看 commit 历史**

Run:
```bash
cd /Users/ericw/work/code/ai/sebastian && git log --oneline origin/main..HEAD
```

Expected: 能看到本次工作所有 commit，逻辑清晰、原子化。

- [ ] **Step 7（可选）: push + PR（仅用户要求时才做）**

不自动执行。用户自行决定何时 `git push` 和 `gh pr create`。

---

## 验证清单（落地验证的最终 sanity check）

- [ ] `GET /agents` 返回的 JSON 里无 `name` 字段、`agent_type == "forge"`
- [ ] Android Chat 卡片 header 显示 `Agent: Forge`
- [ ] Android Chat 卡片"参数"展开区显示 `agent_type: forge`（不大写）
- [ ] Android Sub-Agent 列表页显示 `Forge`
- [ ] Sebastian 的 system prompt 里 agent roster 是 `- forge: 编写代码...`
- [ ] `delegate_to_agent` 工具返回文本 `"已安排 Forge 处理：..."`
- [ ] 孤儿目录 warning 在启动日志可见（有历史数据时）
- [ ] CHANGELOG Breaking Changes 可读可操作

## 关键文件索引

- 后端核心：`sebastian/agents/forge/` (新)、`sebastian/agents/_loader.py`、`sebastian/capabilities/tools/delegate_to_agent/__init__.py`、`sebastian/gateway/completion_notifier.py`、`sebastian/gateway/routes/agents.py`、`sebastian/gateway/app.py`、`sebastian/orchestrator/sebas.py`
- Android：`data/model/AgentInfo.kt`、`data/remote/dto/AgentDto.kt`、`ui/subagents/AgentListScreen.kt`、`ui/chat/ToolDisplayName.kt`、`ui/chat/ToolCallInputExtractor.kt`
- Web：`ui/mobile/src/api/agents.ts`
- 测试：`tests/unit/capabilities/test_tool_delegate.py`、`tests/unit/core/test_prompt_builder.py`（新增）、`ui/mobile-android/.../test/.../ToolDisplayNameTest.kt`（新增）、`ui/mobile-android/.../test/.../ToolCallInputExtractorTest.kt`
- 文档：`sebastian/agents/README.md`、`sebastian/agents/forge/README.md`、`sebastian/orchestrator/README.md`、`sebastian/gateway/README.md`、`sebastian/README.md`、`docs/architecture/spec/overview/three-tier-agent.md`、`docs/architecture/spec/core/system-prompt.md`、`CHANGELOG.md`
