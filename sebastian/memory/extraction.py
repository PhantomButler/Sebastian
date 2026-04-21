from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from sebastian.memory.prompts import build_extractor_prompt
from sebastian.memory.provider_bindings import MEMORY_EXTRACTOR_BINDING
from sebastian.memory.types import CandidateArtifact, ProposedSlot

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry, ResolvedProvider

logger = logging.getLogger(__name__)


class ExtractorInput(BaseModel):
    task: Literal["extract_memory_artifacts"] = "extract_memory_artifacts"
    subject_context: dict[str, Any]
    conversation_window: list[dict[str, Any]]
    known_slots: list[dict[str, Any]]


class ExtractorOutput(BaseModel):
    artifacts: list[CandidateArtifact]
    proposed_slots: list[ProposedSlot] = []


class MemoryExtractor:
    """LLM-backed extractor that converts a conversation window into candidate memory artifacts.

    On any failure (provider network/timeout error OR JSON parse/schema failure)
    the extractor retries up to *max_retries* times with exponential backoff
    (0.5s, 1s, 2s, ...), then returns an empty output — it never raises.
    """

    def __init__(self, llm_registry: LLMProviderRegistry, *, max_retries: int = 1) -> None:
        self._registry = llm_registry
        self._max_retries = max_retries

    async def extract(self, input: ExtractorInput) -> ExtractorOutput:
        """Call LLM to extract candidate memory artifacts using the shared prompt template.

        Returns ExtractorOutput(artifacts=[], proposed_slots=[]) on any failure after retries.
        """
        resolved = await self._registry.get_provider(MEMORY_EXTRACTOR_BINDING)
        known_slots_by_kind = _group_known_slots(input.known_slots)
        system = build_extractor_prompt(known_slots_by_kind)
        messages: list[dict[str, Any]] = [{"role": "user", "content": input.model_dump_json()}]
        return await self._try_once(resolved, system, messages)

    async def extract_with_slot_retry(
        self,
        input: ExtractorInput,
        *,
        attempt_register: Callable[[ExtractorOutput], Awaitable[list[tuple[str, str]]]],
    ) -> ExtractorOutput:
        """与 extract() 的区别：

        - attempt_register 回调由调用方传入（SlotProposalHandler.register_or_reuse 的包装或预检）
        - 回调返回被拒的 (slot_id, reason) 元组列表
        - 若列表非空：把被拒列表（含原因）追加到对话里作为反馈，再调一次 LLM（共最多 2 次 LLM 请求）
        - 无论重试结果如何，最多重试 1 次（slot_retry=1）
        """
        resolved = await self._registry.get_provider(MEMORY_EXTRACTOR_BINDING)
        known_slots_by_kind = _group_known_slots(input.known_slots)
        system = build_extractor_prompt(known_slots_by_kind)
        messages: list[dict[str, Any]] = [{"role": "user", "content": input.model_dump_json()}]

        output = await self._try_once(resolved, system, messages)

        rejected_with_reasons = await attempt_register(output)
        if not rejected_with_reasons:
            return output

        # 追加 assistant + user 消息，注入失败反馈后重试一次
        feedback = _build_slot_retry_feedback(rejected_with_reasons)
        messages.extend(
            [
                {"role": "assistant", "content": output.model_dump_json()},
                {"role": "user", "content": feedback},
            ]
        )
        return await self._try_once(resolved, system, messages)

    async def _try_once(
        self,
        resolved: ResolvedProvider,
        system: str,
        messages: list[dict[str, Any]],
    ) -> ExtractorOutput:
        """单次 LLM 调用 + JSON 解析，内部走 max_retries 重试，仍失败返回空 output。"""
        empty = ExtractorOutput(artifacts=[], proposed_slots=[])
        for attempt in range(self._max_retries + 1):
            try:
                raw = await self._call_llm(resolved, system, messages)
                return ExtractorOutput.model_validate_json(_strip_code_fence(raw))
            except Exception as exc:  # noqa: BLE001 — provider exception types vary
                if attempt < self._max_retries:
                    logger.warning(
                        "Extractor attempt %d failed: %s",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                logger.warning(
                    "Extractor exhausted %d retries, returning empty: %s",
                    self._max_retries + 1,
                    exc,
                )
                return empty
        return empty  # unreachable; satisfies type checker

    async def _call_llm(
        self,
        resolved: ResolvedProvider,
        system: str,
        messages: list[dict[str, Any]],
    ) -> str:
        """Stream from LLM and collect all TextDelta events into a single string."""
        from sebastian.core.stream_events import TextDelta

        text = ""
        # Note: temperature is not exposed in the current LLMProvider abstraction;
        # providers use their configured default temperature.
        async for event in resolved.provider.stream(
            system=system,
            messages=messages,
            tools=[],
            model=resolved.model,
            max_tokens=2048,
        ):
            if isinstance(event, TextDelta):
                text += event.delta
        return text


def _strip_code_fence(raw: str) -> str:
    """Strip markdown code fences (```json ... ```) from LLM output before JSON parsing."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


def _group_known_slots(known_slots: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """把 known_slots（SlotDefinition.model_dump() 格式列表）按 kind 分桶，供 prompt 使用。"""
    grouped: dict[str, list[dict[str, str]]] = {}
    for s in known_slots:
        entry: dict[str, str] = {
            "slot_id": s["slot_id"],
            "cardinality": s["cardinality"],
            "resolution_policy": s["resolution_policy"],
            "description": s["description"],
        }
        for kind in s.get("kind_constraints", []):
            grouped.setdefault(kind, []).append(entry)
    return grouped


def _build_slot_retry_feedback(rejected: list[tuple[str, str]]) -> str:
    """生成回注 prompt 的反馈文本，要求 LLM 修正被拒 slot 后重新输出完整 JSON。"""
    bullets = "\n".join(f"- slot_id: {slot_id}，拒绝原因：{reason}" for slot_id, reason in rejected)
    return f"""\
上一轮提议的以下 slot 不合规，请重命名后再输出一轮完整 JSON（artifacts + proposed_slots）：

失败项：
{bullets}

约束提醒：
- 三段式命名，纯小写，下划线分隔，总长 ≤ 64
- 首段必须是 user / session / project / agent 之一
- 禁止与 known_slots 已有 slot_id 重名

请重新给出完整 JSON。被拒 slot 对应的 artifact 也请一并重新给出（slot_id 改为新名字）。"""
