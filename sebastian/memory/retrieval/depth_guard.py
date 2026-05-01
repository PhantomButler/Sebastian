from __future__ import annotations


def is_memory_eligible(depth: int | None) -> bool:
    """记忆功能（注入 + 提取）仅对 depth=1 的主会话开放。

    depth 为 None 时（未初始化）fail-closed 返回 False。
    如需调整开放范围，只改这里即可。
    """
    return depth == 1
