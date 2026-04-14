# Agent 命名统一：移除 display_name，只保留 agent_type

## Context

当前 Sub-Agent 有两个名字：

- `agent_type`：目录名派生（`sebastian/agents/code/` → `"code"`），用作注册表 key、filesystem 路径、URL path、LLM 工具参数
- `display_name`：`manifest.toml [agent].name` 配置（如 `"Forge"`），仅用作 UI 展示

这套二元命名在 Android chat 页面暴露出一个 bug：tool-call 卡片 header 显示 `Agent: Code`（agent_type 首字母大写伪装成专有名），用户希望看到 `Agent: Forge`。

追根到底，这个二元设计对当前规模是过度设计：

- 唯一的 sub-agent `code` 的 display_name 是 ASCII 单词，没吃到"支持中文 / 空格 / emoji"的灵活性
- 项目早期磁盘上的历史 session 数据不精贵，可以接受 breaking 重命名
- 双名带来的认知负担 reflects 在 LLM system prompt 里那句别扭指令 "Pass the exact agent_type value (not the display name)"

**决策：移除 `display_name`，让每个 agent 只有一个名字——`agent_type`（小写 identifier）**。用户侧的 title-case 展示由前端在渲染时 capitalize。作为示范性重命名，把 `code` 改成更贴合人格的 `forge`（与主管家 `sebastian` 的命名风格统一）。

## 非目标

- 不改 JSON API 的 `agent_type` 字段 key（只改它的值），避免 Android/Web DTO 大面积变更
- 不写数据迁移脚本：用户自托管、数据在自己机器，CHANGELOG 指示手动 `mv`/`rm` 即可
- 不动 Sebastian orchestrator 自身（它本来就只有一个名字 `sebastian`）
- 不增强 i18n / 中文 display name 能力（真需要时再加）

## 架构

**核心变化**：`AgentConfig.display_name` 字段删除；`manifest.toml [agent].name` 字段废弃；UI title-case 展示下移到前端 `capitalize()`。

**命名约定**：`agent_type` 是小写 identifier（合法 Python 包名 + filesystem 安全 + URL 安全），同时担任：

| 角色 | 位置 | 示例 |
|------|------|------|
| 目录名 | `sebastian/agents/{agent_type}/` | `sebastian/agents/forge/` |
| Python 包名 | `from sebastian.agents.{agent_type} import ...` | `sebastian.agents.forge` |
| 注册表 key | `state.agent_registry[agent_type]` | `"forge"` |
| Session filesystem 路径 | `sessions/{agent_type}/{session_id}/` | `sessions/forge/2026-04-14T.../` |
| URL path param | `GET /agents/{agent_type}/sessions` | `/agents/forge/sessions` |
| LLM tool 参数值 | `delegate_to_agent(agent_type="...")` | `"forge"` |
| UI 展示基底（前端 capitalize） | `agent_type.capitalize()` | `"Forge"` |

## 改动清单

### 后端

**目录 + 类重命名**

- `sebastian/agents/code/` → `sebastian/agents/forge/`
- `code/knowledge/` 子目录跟随
- `__init__.py`: `class CodeAgent` → `class ForgeAgent`, `name = "forge"`（persona 文本不动）
- `manifest.toml`: 删 `name = "Forge"` 行，`class_name` 从 `"CodeAgent"` 改 `"ForgeAgent"`

**`sebastian/agents/_loader.py`**

- `AgentConfig` dataclass 删 `display_name: str` 字段
- 构造 AgentConfig 时不再读 `agent_section.get("name", ...)`
- `manifest.toml` 里历史遗留的 `name = "..."` 字段静默忽略，不报错（实际上我们自己的 forge/manifest.toml 会删掉这个字段，但这里仍然容错）

**`sebastian/capabilities/tools/delegate_to_agent/__init__.py`**

- 删除 `display_name = config.display_name if config else agent_type` 行
- 返回文案 `f"已安排{display_name}处理：{goal}"` → `f"已安排 {agent_type.capitalize()} 处理：{goal}"`

**`sebastian/gateway/completion_notifier.py`**

- 两处使用 `display_name` 的通知文案（[completion_notifier.py:109-124](sebastian/gateway/completion_notifier.py#L109-L124)）改用 `agent_type.capitalize()`
- 删除 `display_name = config.display_name if config else agent_type` 查表逻辑

**`sebastian/gateway/routes/agents.py`**

- JSON 返回体删 `"name": config.display_name`
- 保留字段：`agent_type` / `description` / `active_session_count` / `max_children`

**`sebastian/gateway/app.py`**

- `_initialize_agent_instances` 日志 `"Registered agent instance: %s (%s)"` → `"Registered agent instance: %s"`
- 在 lifespan 末段加启动自检：
  ```python
  orphan_dirs = [
      d.name for d in settings.sessions_dir.iterdir()
      if d.is_dir() and d.name not in {"sebastian", *state.agent_registry.keys()}
  ]
  if orphan_dirs:
      logger.warning(
          "Found orphan session dirs (not in registry): %s. "
          "Likely from a renamed agent. See CHANGELOG for migration.",
          orphan_dirs,
      )
  ```

**`sebastian/orchestrator/sebas.py:102-116`**

- `_agents_section()` 渲染改成：
  ```
  Available sub-agents (delegate via the `delegate_to_agent` tool):
  - forge: 编写代码、调试问题、构建工具

  Pass the agent name as `agent_type`.
  ```
- 删除 "display name" / "exact agent_type" 相关的区分性措辞

### 前端（Android）

**`ui/mobile-android/app/src/main/java/com/sebastian/android/data/remote/dto/AgentDto.kt`**

- 删 `name` 字段（JSON 里后端也不再返回）

**`ui/mobile-android/app/src/main/java/com/sebastian/android/data/model/AgentInfo.kt`**

- 删 `name` 字段
- 新增扩展：
  ```kotlin
  val AgentInfo.displayName: String
      get() = agentType.replaceFirstChar { it.uppercase() }
  ```

**`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/subagents/AgentListScreen.kt`**

- `agent.name` → `agent.displayName`

**`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt`**

- 删除 [行 38-43](ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolCallInputExtractor.kt#L38-L43) 的 `delegate_to_agent` + `agent_type` uppercase 特例
- `extractInputSummary` 回归单纯"按 key 取字符串值"，不掺入展示策略

**`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt`**

- `delegate_to_agent` 分支：
  ```kotlin
  "delegate_to_agent" -> Display(
      title = "Agent: ${rawSummary.replaceFirstChar { it.uppercase() }}",
      summary = "",
  )
  ```
- 大小写展示职责归位此处

### 前端（Web / `ui/mobile/`）

**`ui/mobile/src/api/agents.ts`**

- 删 `agent.name` 的回传映射
- `id` 继续取自 `agent_type`
- `displayName` 从 `titleCase(agent.id)` 派生

**`ui/mobile/src/components/conversation/ToolCallRow.tsx`**

- 若有类似 uppercase 特例，同步删除，改用统一的 title-case 工具函数

### 测试

**`tests/unit/capabilities/test_tool_delegate.py`**

- 断言里含 `display_name` 或 `"Forge"` 字样的测试改成期望 `agent_type` 的 capitalize 形式（`"Forge"` 由 `"forge".capitalize()` 得到，值相同）
- 删除 `AgentConfig(display_name=...)` 的 mock

**`ui/mobile-android/app/src/test/java/com/sebastian/android/ui/chat/ToolCallInputExtractorTest.kt`**

- 删除或改写依赖"首字母大写"断言的 case，期望原始 `agent_type` 字符串

**新增 `ToolDisplayNameTest.kt`**

- JUnit4，风格对齐 `ToolCallInputExtractorTest`
- 覆盖：
  - `delegate_to_agent` + 合法 inputs → `Agent: Forge`
  - `delegate_to_agent` + 空 inputs → `Agent: `（边界）
  - `spawn_sub_agent` + goal → `Worker` + summary
  - 未知工具走 else 分支

**Android ViewModel 测试**

- 如果任何 mock 构造了 `AgentInfo(name="...")`，删该参数

**orchestrator 单测（新增或更新）**

- 断言 `_agents_section()` 输出包含 `- forge:` 且不包含 "Pass the exact agent_type" / "display name" 字样

### 文档（全仓扫一遍）

- `sebastian/agents/README.md`：
  - 删除「如何新增 Sub-Agent」里 `manifest.toml [agent].name` = display_name 的段落
  - 新说明："目录名即 agent_type，是系统唯一标识；UI 展示时前端做 capitalize"
  - 示例 manifest.toml 移除 `name` 字段
- `sebastian/agents/forge/README.md`（原 `code/README.md`）：内容里 `code` 引用全改 `forge`
- `sebastian/orchestrator/README.md`：agent roster 描述与新 prompt 对齐
- `sebastian/gateway/README.md`：`state.agent_registry["code"]` 示例改 `["forge"]`
- `sebastian/README.md`：顶层介绍里提到的 agent 列表
- `docs/architecture/spec/overview/three-tier-agent.md` + `INDEX.md`：检查 `code` / `display_name` 引用
- `docs/architecture/spec/core/system-prompt.md`：agent roster 渲染描述
- `CHANGELOG.md`：新增 `### Breaking Changes` 条目：
  ```markdown
  - 子代理 `code` 重命名为 `forge`；移除 `manifest.toml` 的 `name` 字段和 `AgentConfig.display_name`，agent 只有一个名字（`agent_type`）。
  - 升级前请处理历史会话数据：
    ```bash
    # 选项 A：保留历史
    mv ~/.sebastian/sessions/code ~/.sebastian/sessions/forge
    python3 -c "import json, pathlib; p = pathlib.Path.home()/'.sebastian/sessions/index.json'; d = json.loads(p.read_text()); [e.__setitem__('agent_type','forge') for e in d if e.get('agent_type')=='code']; p.write_text(json.dumps(d, ensure_ascii=False, indent=2))"
    # ~/.sebastian-dev/ 同理

    # 选项 B：放弃历史
    rm -rf ~/.sebastian/sessions/code ~/.sebastian-dev/sessions/code
    # （需要同步从 index.json 删除相应条目，或接受列表里出现但打不开的孤儿条目）
    ```
  - Gateway 启动时会对 `sessions/` 下的孤儿目录（注册表里没有的 agent_type）打 warning 日志，作为提醒。
  ```

### 不动的部分

- `sessions.py:237` / `routes/agents.py:21` / `completion_notifier.py:99` 的 `if agent_type == "sebastian"` 分支：这是"区分 orchestrator 会话 vs sub-agent 会话"的业务逻辑，不是 display_name 衍生
- `Sebastian` orchestrator 类：本来就一个名字，不动
- SSE 事件 payload 字段名：保留 `agent_type`，只是值变了
- DB / index.json 的字段名：保留 `agent_type`，只是值变了

## 数据迁移

**方式：CHANGELOG 说明 + 用户手动**

理由：

- 单用户自托管，数据在用户自己机器
- 项目早期，历史 session 并非不可弃数据
- 写迁移脚本 / 启动自动迁移都是 50+ 行只跑一次的代码，之后成为死代码或维护负担

**启动自检（软提醒）**

Gateway lifespan 末段扫 `sessions/` 下所有目录，不在 registry 且不是 `sebastian` 的打 warning（不做任何数据动作）。用户升级后第一次启动日志就会看到，不用翻 CHANGELOG。

## 回滚

代码：`git revert` 或切到旧 tag。

数据：如果用户已经 `mv sessions/code sessions/forge`，回滚代码后需要手动 `mv` 回去。单用户场景可接受。

## 验证

**后端**

- `pytest tests/unit/capabilities/test_tool_delegate.py -v`
- `pytest tests/integration/test_gateway.py -v`（涉及 `/agents` 路由时）
- `ruff check sebastian/ tests/` + `ruff format --check sebastian/ tests/`
- `mypy sebastian/`
- 手动：`./scripts/dev.sh` 启动 → `curl http://127.0.0.1:8824/agents` 确认 JSON 里无 `name` 字段，值 `agent_type == "forge"`

**Android**

- `./gradlew :app:testDebugUnitTest`（含新增 `ToolDisplayNameTest`）
- `./gradlew :app:lintDebug`
- 手动（由用户 install，agent 不代劳）：
  - Chat 触发 `delegate_to_agent(agent_type="forge", ...)`
  - 卡片 header 显示 `Agent: Forge`
  - 展开"参数"区显示 `agent_type: forge`（原始字段，不 title-case）
  - Sub-Agent 列表页展示 `Forge`

**orchestrator prompt**

- 单测断言 `_agents_section()` 输出包含 `- forge:` 且不含 `"display name"` / `"exact agent_type"` 字样

## 关键文件索引

- 后端核心：`sebastian/agents/_loader.py`, `sebastian/capabilities/tools/delegate_to_agent/__init__.py`, `sebastian/gateway/completion_notifier.py`, `sebastian/gateway/routes/agents.py`, `sebastian/gateway/app.py`, `sebastian/orchestrator/sebas.py`
- 重命名：`sebastian/agents/code/` → `sebastian/agents/forge/`
- Android 核心：`ui/mobile-android/app/src/main/java/com/sebastian/android/ui/chat/ToolDisplayName.kt`, `ToolCallInputExtractor.kt`, `data/model/AgentInfo.kt`, `data/remote/dto/AgentDto.kt`, `ui/subagents/AgentListScreen.kt`
- Web：`ui/mobile/src/api/agents.ts`
- 文档：`sebastian/agents/README.md`, `sebastian/orchestrator/README.md`, `sebastian/gateway/README.md`, `sebastian/README.md`, `docs/architecture/spec/overview/three-tier-agent.md`, `docs/architecture/spec/core/system-prompt.md`, `CHANGELOG.md`
