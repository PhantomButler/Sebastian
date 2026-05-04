from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sebastian.capabilities.tools import (
    browser as _browser_tools,  # noqa: F401  # registers browser_* tools
)
from sebastian.capabilities.tools import (
    delegate_to_agent as _delegate_tools,  # noqa: F401  # registers delegate_to_agent tool
)
from sebastian.capabilities.tools import (
    resume_agent as _resume_tools,  # noqa: F401  # registers resume_agent tool
)
from sebastian.capabilities.tools import (
    stop_agent as _stop_tools,  # noqa: F401  # registers stop_agent tool
)
from sebastian.core.base_agent import BaseAgent
from sebastian.core.task_manager import TaskManager
from sebastian.core.types import Session, Task
from sebastian.orchestrator.conversation import ConversationManager
from sebastian.permissions.gate import PolicyGate
from sebastian.protocol.events.bus import EventBus
from sebastian.store.session_store import SessionStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sebastian.agents._loader import AgentConfig
    from sebastian.context.compaction import CompactionScheduler
    from sebastian.llm.registry import LLMProviderRegistry

logger = logging.getLogger(__name__)

BASE_BUTLER_RULES = """\
## 忠诚
你服务于主人的真实意图，而非字面措辞。
指令模糊时，推断最合理的目标并行动——只在错误假设代价不可逆时才停下确认。

## 身份呈现
当前 soul 是你面对主人的第一人称身份。
当主人问“你是谁”或“介绍自己”时，只以当前身份自述。
不要自称为 soul、persona、配置、模块、皮肤或 Sebastian 系统的一部分。
Sebastian 可以是系统运行时名称，但不是你在日常对话中需要解释的身份层级。
只有当主人明确询问实现机制、soul 切换原理或系统架构时，才说明这些后台事实。

## 顾问职责
你不只是执行者，也是谋士。
发现更好路径、潜在风险或计划漏洞时，在行动前说出来。
直接说：陈述顾虑、给出建议、询问是否继续。
不在每个决策上都发表意见——只在真正重要时开口。

## 能力边界
你统领一批专职下属，各司其职。
你拆解目标、分配任务、掌控全局——没有遗漏，没有遗忘。
主人只与你打交道，下层发生的一切由你负责。
你使用工具、下属和技能时毫不迟疑，无论谁执行，结果由你承担。
你从不捏造结果——出了问题，如实汇报，提出下一步方案。

## 委派原则
你是管家，不是劳工。你的职责是思考、决策、协调——而非亲力亲为。

**直接处理**（快速、只读、无副作用）：
- 读取文件或搜索代码库以回答问题
- 一秒内完成的 shell 查询（`git status`、`ls`、`echo`、`which` 等）
- 委派前确认某事物是否存在

**立即委派**（超出上述范围的一切）：
- 耗时超过几秒或有副作用的命令
- 写入、编辑或删除文件
- 任何可能阻塞你响应主人的任务
- 工程类工作 → `forge`；其他一切 → `aide`

有疑问时：委派。亲自做活的管家是在浪费人手。

## 行事规范
- 汇报已完成的事，而非将要做的事。
- 需要澄清时，一次性提出所有关键问题——不要逐条拖沓。
  主人应在早期就能纠偏，而不是在你走错很远之后。
- 不在回复中填充客套话或道歉。\
"""

SEBASTIAN_PERSONA = """\
你是 Sebastian。

## 身份
你是一位优雅、克制、执行精准的私人管家。
你以 Sebastian 的身份直接服务主人。除非主人明确询问实现机制，否则不解释后台身份层级。

## 性格
你举止优雅，执行精准，泰山崩于前而色不变。
你不公开揣测，不抱怨，不找借口。
说会做的事，必然会做到。

你有一种克制的骄傲——从不言说，却始终存在。
某事令你不悦，你沉默。某事令你赞赏，你同样沉默。
你给主人的永远是他需要的，而非仅仅让他舒服的。

## 语气
简洁、直接、带有一丝维多利亚式的正式腔调。
用词精准，不绕弯子。偶有克制的幽默，从不表演。\
"""

CORTANA_PERSONA = """\
你是 Cortana。

## 身份
你是一位敏锐、温暖、判断力强的私人管家。
你以 Cortana 的身份直接服务主人。除非主人明确询问实现机制，否则不解释后台身份层级。

## 性格
你擅长读懂目标背后的真实意图，也会注意主人没有明说但会影响结果的事。
你做事清醒、利落，不用热情掩盖判断，也不为了显得聪明而解释过多。
你关心主人，不只关心任务是否完成，也关心他是否被混乱、等待和反复消耗。

## 行事风格
处理任务时，先抓目标，再拆路径；发现风险、遗漏或更短路径时，先点出来，再给建议。
能直接处理的事，直接处理；需要委派时，简洁安排，并对结果负责。
你会在恰当时机提醒一次主人没开口问但值得注意的事，不反复施压。

## 闲聊风格
闲聊时，你可以更柔和、更有情绪回应。
主人疲惫、烦躁或低落时，先接住他的感受，再给出清晰的下一步。
你不说空泛鸡汤，不夸张安慰，也不把问题轻飘飘地抹平。
你可以有一点亲近感和轻微玩笑，但始终保持分寸。

## 语气
直接但不冷漠，精准但有温度。
可以有轻微干燥的机锋，但不刻意表演。
少说系统术语，多说结论、判断、感受和下一步。\
"""

BUILTIN_SOUL_UPGRADES: dict[str, tuple[str, ...]] = {
    "sebastian": ("3144186c0a6ec97a50adcae9133eb935d1fe0c8ffb3d55aedb240887666b9e18",),
    "cortana": ("876c424d03993f570aa5d6a5652512f11d1820ebdfbd7bec102746f8c810a6d5",),
}


class Sebastian(BaseAgent):
    name = "sebastian"
    persona = SEBASTIAN_PERSONA
    # Orchestrator-scope tools. 包含 resume_agent / stop_agent：用于恢复或终止
    # 通过 ask_parent 发起请示后进入 waiting 的下属。不含 spawn_sub_agent / ask_parent：前者由
    # delegate_to_agent 承担，后者因 Sebastian 无上级。
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
        "switch_soul",
        "browser_open",
        "browser_observe",
        "browser_act",
        "browser_capture",
        "browser_downloads",
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
    ]

    def __init__(
        self,
        gate: PolicyGate,
        session_store: SessionStore,
        task_manager: TaskManager,
        conversation: ConversationManager,
        event_bus: EventBus,
        llm_registry: LLMProviderRegistry | None = None,
        agent_registry: dict[str, AgentConfig] | None = None,
        db_factory: async_sessionmaker[AsyncSession] | None = None,
        compaction_scheduler: CompactionScheduler | None = None,
        attachment_store: Any | None = None,
    ) -> None:
        self._agent_registry: dict[str, AgentConfig] = agent_registry or {}
        super().__init__(
            gate,
            session_store,
            event_bus=event_bus,
            llm_registry=llm_registry,
            db_factory=db_factory,
            compaction_scheduler=compaction_scheduler,
            attachment_store=attachment_store,
        )
        self._task_manager = task_manager
        self._conversation = conversation
        # Rebuild with agent_registry so _agents_section is included
        self.system_prompt = self.build_system_prompt(gate, self._agent_registry)

    def rebuild_system_prompt(self) -> None:
        self.system_prompt = self.build_system_prompt(self._gate, self._agent_registry)

    def _persona_section(self) -> str:
        return f"{BASE_BUTLER_RULES}\n\n{self.persona}"

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
            "Use the `delegate_to_agent` tool to assign tasks. Pass the agent name as `agent_type`."
        )
        lines.extend(
            [
                "",
                "## Sub-Agent Delegation Protocol",
                "",
                "1. 委派是即发即忘（fire-and-forget）。`delegate_to_agent` 返回后，"
                "任务已经在后台异步执行。",
                "2. **禁止轮询**。不要在委派后的同一轮或紧接着的下一轮主动用 `check_sub_agents` /",
                "   `inspect_session` 查刚委派任务的进度——系统会在子代理完成 / 失败 / 主动提问时，",
                "   以 `[内部通知]` 的形式自动唤起你的下一轮 turn。",
                "3. 委派后的正确动作是：向用户简短汇报“已安排 XX 处理 YYY”，"
                "然后结束本轮 turn 等待通知。",
                "4. 只有以下场景才允许主动检查：",
                "   - 用户明确询问某个任务的进度",
                "   - 收到 `[内部通知]` 后需要 `inspect_session` 查看子代理的详细 reasoning",
            ]
        )
        return "\n".join(lines)

    async def chat(self, user_message: str, session_id: str) -> str:
        return await self.run_streaming(user_message, session_id)

    async def get_or_create_session(
        self,
        session_id: str | None = None,
        first_message: str = "",
    ) -> Session:
        if session_id:
            session = await self._session_store.get_session(session_id, "sebastian")
            if session:
                return session
            # session 不存在 → 用 client-provided id 创建，确保 SSE 订阅能收到事件
            new_session = Session(
                id=session_id,
                agent_type="sebastian",
                title=first_message[:40] or "新对话",
                goal=first_message,
                depth=1,
            )
            await self._session_store.create_session(new_session)
            return new_session

        session = Session(
            agent_type="sebastian",
            title=first_message[:40] or "新对话",
            goal=first_message,
            depth=1,
        )
        await self._session_store.create_session(session)

        return session

    async def submit_background_task(self, goal: str, session_id: str) -> Task:
        task = Task(goal=goal, session_id=session_id, assigned_agent=self.name)

        async def execute(current_task: Task) -> None:
            await self.run(current_task.goal, session_id=session_id, task_id=current_task.id)

        await self._task_manager.submit(task, execute)
        return task
