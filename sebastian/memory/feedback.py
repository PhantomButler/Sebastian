from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_LANE_LABELS: dict[str, str] = {
    "profile": "画像",
    "context": "近况",
    "episode": "回忆",
    "relation": "关系",
}


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


def render_memory_search_display(items: list[dict[str, Any]]) -> str:
    """把 memory_search items 渲染成人类可读的多行文本（供 App UI 展示）。

    输出格式：
        找到 N 条相关记忆：
        • [画像] 以后回答简洁中文
        • [回忆] 上次讨论了 Python 异步编程

    不带 confidence/lane 之外的技术字段；lane 中文化后作为前缀，便于用户
    一眼分辨"当前事实"与"历史回忆"。
    """
    if not items:
        return "记忆库中暂无匹配内容。"

    lines = [f"找到 {len(items)} 条相关记忆："]
    for item in items:
        lane_key = str(item.get("lane", ""))
        lane_label = _LANE_LABELS.get(lane_key, lane_key or "记忆")
        content = str(item.get("content", "")).strip() or "（无内容）"
        lines.append(f"• [{lane_label}] {content}")
    return "\n".join(lines)
