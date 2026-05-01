from __future__ import annotations

import asyncio
import logging

import sebastian.gateway.state as state
from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.memory.constants import MEMORY_SAVE_TIMEOUT_SECONDS
from sebastian.memory.writing.feedback import MemorySaveResult, render_memory_save_summary
from sebastian.memory.trace import preview_text, trace
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool(
    name="memory_save",
    description=(
        "保存用户明确要求记住的内容。仅当用户直接要求你记住某件事时调用，例如'帮我记住……'。"
        "返回的结构化字段（saved_count、discarded_count 等）仅供你判断是否保存成功，"
        "除非用户明确询问「记了几条」「有没有重复」这类细节，否则不要在回复里复述这些元数据；"
        "output 里的 summary 字段已是面向用户的自然语言结果，可直接引用。"
    ),
    permission_tier=PermissionTier.LOW,
)
async def memory_save(content: str) -> ToolResult:
    trace(
        "tool.memory_save.start",
        content_preview=preview_text(content),
    )

    if not state.memory_settings.enabled:
        return ToolResult(ok=False, error="记忆功能当前已关闭，无法保存。")

    if not hasattr(state, "db_factory") or state.db_factory is None:
        return ToolResult(ok=False, error="记忆存储暂时不可用，无法保存，请稍后再试。")

    ctx = get_tool_context()
    session_id: str | None = ctx.session_id if ctx else None
    agent_type: str = (ctx.agent_type if ctx else None) or "default"

    try:
        result = await asyncio.wait_for(
            _do_save(content, session_id, agent_type),
            timeout=MEMORY_SAVE_TIMEOUT_SECONDS,
        )
        trace("tool.memory_save.done", saved=result.saved_count)
        return ToolResult(
            ok=True,
            output=result.model_dump(),
            display=result.summary,
        )
    except TimeoutError:
        trace("tool.memory_save.timeout")
        return ToolResult(ok=False, error="保存失败，请告知用户稍后再试。")
    except Exception as exc:  # noqa: BLE001
        logger.exception("memory_save failed")
        trace("tool.memory_save.error", reason=str(exc))
        return ToolResult(ok=False, error="保存失败，请告知用户并建议其排查后台日志。")


async def _do_save(content: str, session_id: str | None, agent_type: str) -> MemorySaveResult:
    from sebastian.memory.contracts.writing import MemoryWriteRequest
    from sebastian.memory.errors import InvalidSlotProposalError
    from sebastian.memory.consolidation.extraction import ExtractorInput, ExtractorOutput, MemoryExtractor
    from sebastian.memory.writing.slot_proposals import validate_proposed_slot
    from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY

    if state.memory_service is None:
        raise RuntimeError("memory_service 未初始化，无法保存记忆。")

    extractor = MemoryExtractor(state.llm_registry)
    known_slots = [
        {
            "slot_id": s.slot_id,
            "scope": s.scope.value,
            "subject_kind": s.subject_kind,
            "cardinality": s.cardinality.value,
            "resolution_policy": s.resolution_policy.value,
            "kind_constraints": [k.value for k in s.kind_constraints],
            "description": s.description,
        }
        for s in DEFAULT_SLOT_REGISTRY.list_all()
    ]

    async def attempt_register(output: ExtractorOutput) -> list[tuple[str, str]]:
        """回调：预检 proposed_slots；返回被拒的 (slot_id, reason) 列表。

        只做校验，不真正注册（真正注册在 write_candidates 里统一做）。
        """
        rejected: list[tuple[str, str]] = []
        for p in output.proposed_slots:
            try:
                validate_proposed_slot(p)
            except InvalidSlotProposalError as exc:
                rejected.append((p.slot_id, str(exc)))
        return rejected

    extractor_output = await extractor.extract_with_slot_retry(
        ExtractorInput(
            subject_context={"agent_type": agent_type},
            conversation_window=[{"role": "user", "content": content}],
            known_slots=known_slots,
        ),
        attempt_register=attempt_register,
    )

    write_result = await state.memory_service.write_candidates(
        MemoryWriteRequest(
            candidates=extractor_output.artifacts,
            proposed_slots=extractor_output.proposed_slots,
            session_id=session_id or "",
            agent_type=agent_type,
            worker_id="memory_save_tool",
            model_name=None,
            rule_version="spec-a-v1",
            input_source={"type": "memory_save_tool", "session_id": session_id},
            proposed_by="extractor",
        )
    )

    save_result = MemorySaveResult(
        saved_count=write_result.saved_count,
        discarded_count=write_result.discarded_count,
        proposed_slots_registered=write_result.proposed_slots_registered,
        proposed_slots_rejected=write_result.proposed_slots_rejected,
        summary="",
    )
    save_result.summary = render_memory_save_summary(save_result)
    return save_result
