from __future__ import annotations

import logging

from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.memory.subject import resolve_subject
from sebastian.memory.trace import preview_text, trace
from sebastian.memory.types import MemoryScope
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)


@tool(
    name="memory_search",
    description=(
        "Search long-term memory for relevant facts, preferences, summaries, or episodes. "
        "返回的 items 带有 lane / confidence / citation_type / is_current / source 等元数据，"
        "这些字段仅供你判断如何组织回答（例如区分『当前事实』与『历史回忆』的措辞），"
        "**除非用户明确要求查看这些信息，否则不要在回复中向用户复述置信度、通道、来源等字段**，"
        "只基于记忆 content 自然地回答。"
    ),
    permission_tier=PermissionTier.LOW,
    display_name="Search Memory",
)
async def memory_search(query: str, limit: int = 5) -> ToolResult:
    import sebastian.gateway.state as state
    from sebastian.memory.contracts.retrieval import ExplicitMemorySearchRequest
    from sebastian.memory.writing.feedback import render_memory_search_display

    trace(
        "tool.memory_search.start",
        query_preview=preview_text(query),
        limit=limit,
    )

    if not state.memory_settings.enabled:
        return ToolResult(ok=False, error="记忆功能当前已关闭，无法查询记忆。")

    if not hasattr(state, "db_factory") or state.db_factory is None:
        return ToolResult(ok=False, error="记忆存储暂时不可用，请稍后再试。")

    if state.memory_service is None:
        return ToolResult(ok=False, error="记忆服务暂时不可用，请稍后再试。")

    try:
        ctx = get_tool_context()
        session_id = ctx.session_id if ctx else "unknown"

        subject_id = await resolve_subject(
            MemoryScope.USER,
            session_id=session_id,
            agent_type="memory_search_tool",
        )

        result = await state.memory_service.search(
            ExplicitMemorySearchRequest(
                query=query,
                session_id=session_id,
                agent_type="memory_search_tool",
                subject_id=subject_id,
                limit=limit,
            )
        )
        items = result.items

        trace(
            "tool.memory_search.done",
            query_preview=preview_text(query),
            result_count=len(items),
            current_count=sum(1 for item in items if item.get("is_current")),
            historical_count=sum(1 for item in items if not item.get("is_current")),
        )

        if not items:
            return ToolResult(
                ok=True,
                output={"items": []},
                empty_hint="记忆库中暂无匹配内容",
                display="记忆库中暂无匹配内容。",
            )
        return ToolResult(
            ok=True,
            output={"items": items},
            display=render_memory_search_display(items),
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("memory_search failed")
        trace("tool.memory_search.error", reason=str(exc))
        return ToolResult(ok=False, error="记忆查询失败，请告知用户并建议其排查后台日志。")
