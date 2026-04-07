from __future__ import annotations

from pathlib import Path

from sebastian.config import settings


def resolve_path(file_path: str) -> Path:
    """将文件路径解析为绝对路径。

    相对路径解析到 workspace_dir；绝对路径直接 resolve()。
    所有文件类工具必须调用此函数，不得使用 os.path.abspath()。
    """
    p = Path(file_path)
    if p.is_absolute():
        return p.resolve()
    return (settings.workspace_dir / file_path).resolve()
