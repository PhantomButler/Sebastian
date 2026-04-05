from __future__ import annotations

import os

_file_mtimes: dict[str, float] = {}


def record_read(path: str) -> None:
    """Read 成功后调用，记录当前 mtime。"""
    try:
        _file_mtimes[path] = os.path.getmtime(path)
    except OSError:
        pass


def check_write(path: str) -> None:
    """
    Write 前调用。
    - 文件不存在 → 允许（新建）
    - 文件存在但从未 Read → 拒绝
    - 文件存在且 Read 过但 mtime 变更 → 拒绝
    抛出 ValueError。
    """
    try:
        current_mtime = os.path.getmtime(path)
    except OSError:
        return  # file does not exist — allow creation

    if path not in _file_mtimes:
        raise ValueError(
            f"File has not been read yet. Call Read first before writing: {path}"
        )
    if current_mtime != _file_mtimes[path]:
        raise ValueError(
            f"File has been modified externally since last read. "
            f"Call Read again before writing: {path}"
        )


def invalidate(path: str) -> None:
    """Write/Edit 成功后调用，更新缓存 mtime。"""
    try:
        _file_mtimes[path] = os.path.getmtime(path)
    except OSError:
        _file_mtimes.pop(path, None)
