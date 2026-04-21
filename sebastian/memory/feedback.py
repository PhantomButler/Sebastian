from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MemorySaveResult(BaseModel):
    saved_count: int
    discarded_count: int
    proposed_slots_registered: list[str]
    proposed_slots_rejected: list[dict[str, Any]]
    summary: str


def render_memory_save_summary(result: MemorySaveResult) -> str:
    """根据结构化结果渲染自然语言 summary。"""
    if result.saved_count == 0:
        if result.proposed_slots_rejected and not result.proposed_slots_registered:
            return "提议的新分类不合规，未保存对应内容。"
        if result.discarded_count > 0:
            return "内容里没找到明确的记忆点。"
        return "内容暂无可保存的记忆价值。"

    parts = [f"已记住 {result.saved_count} 条"]
    if result.proposed_slots_registered:
        slot_list = "、".join(result.proposed_slots_registered)
        parts.append(f"并新增了分类 {slot_list}")
    if result.discarded_count > 0:
        parts.append(f"另有 {result.discarded_count} 条因重复被跳过")
    return "，".join(parts) + "。"
