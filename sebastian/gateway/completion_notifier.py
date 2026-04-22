from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sebastian.agents._loader import AgentConfig
    from sebastian.core.base_agent import BaseAgent
    from sebastian.orchestrator.sebas import Sebastian
    from sebastian.protocol.events.bus import EventBus
    from sebastian.store.session_store import SessionStore

from sebastian.protocol.events.types import Event, EventType

logger = logging.getLogger(__name__)

_MAX_REPORT_CHARS = 500


class CompletionNotifier:
    """订阅子代理 session 生命周期事件，触发父 Agent（Sebastian 或 Leader）的新 LLM turn。"""

    def __init__(
        self,
        event_bus: EventBus,
        session_store: SessionStore,
        sebastian: Sebastian,
        agent_instances: dict[str, BaseAgent],
        agent_registry: dict[str, AgentConfig],
    ) -> None:
        self._session_store = session_store
        self._sebastian = sebastian
        self._agent_instances = agent_instances
        self._agent_registry = agent_registry
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        event_bus.subscribe(self._on_session_event, EventType.SESSION_COMPLETED)
        event_bus.subscribe(self._on_session_event, EventType.SESSION_FAILED)
        event_bus.subscribe(self._on_session_event, EventType.SESSION_WAITING)

    async def _on_session_event(self, event: Event) -> None:
        parent_session_id = event.data.get("parent_session_id")
        if not parent_session_id:
            return
        if parent_session_id not in self._queues:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._queues[parent_session_id] = queue
            self._workers[parent_session_id] = asyncio.create_task(
                self._worker(parent_session_id, queue),
                name=f"completion_notifier_{parent_session_id}",
            )
        item = {"event_type": event.type, "data": event.data}
        await self._queues[parent_session_id].put(item)

    async def _worker(self, parent_session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        while True:
            try:
                item = await queue.get()
                await self._process(parent_session_id, item["event_type"], item["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "CompletionNotifier error for parent session %s", parent_session_id
                )

    async def _process(
        self,
        parent_session_id: str,
        event_type: EventType,
        data: dict[str, Any],
    ) -> None:
        parent_agent = await self._find_parent_agent(parent_session_id)
        if parent_agent is None:
            logger.warning("CompletionNotifier: parent agent not found for %s", parent_session_id)
            return

        notification = await self._build_notification(event_type, data)
        if notification is None:
            return

        try:
            await parent_agent.run_streaming(notification, parent_session_id)
        except Exception:
            logger.exception(
                "CompletionNotifier: run_streaming failed for parent %s", parent_session_id
            )

    async def _find_parent_agent(self, parent_session_id: str) -> BaseAgent | None:
        all_sessions = await self._session_store.list_sessions()
        parent_entry = next((s for s in all_sessions if s.get("id") == parent_session_id), None)
        if parent_entry is None:
            return None
        agent_type = parent_entry.get("agent_type", "")
        if agent_type == "sebastian":
            return self._sebastian
        return self._agent_instances.get(agent_type)

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
                f"agent_type：{agent_type}\n"
                f"session_id：{session_id}"
                "（回复请使用 resume_agent(agent_type, session_id, instruction)）"
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

    async def _get_last_assistant_message(self, session_id: str, agent_type: str) -> str:
        items = await self._session_store.get_recent_timeline_items(
            session_id, agent_type, limit=10
        )
        for item in reversed(items):
            if item.get("kind") == "assistant_message" and item.get("content"):
                content: str = item["content"]
                if len(content) > _MAX_REPORT_CHARS:
                    content = content[:_MAX_REPORT_CHARS] + "…（已截断）"
                return content
        return "（无汇报内容）"

    async def aclose(self) -> None:
        """关闭所有 worker task 并等待退出，供 gateway shutdown 时调用。"""
        for task in self._workers.values():
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._queues.clear()
