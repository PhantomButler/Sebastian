# sebastian/log/__init__.py
from __future__ import annotations

from pathlib import Path

from sebastian.log.manager import LogManager
from sebastian.log.schema import LogConfigPatch, LogState

_log_manager: LogManager | None = None


def setup_logging(data_dir: Path, llm_stream: bool = False, sse: bool = False) -> LogManager:
    """初始化全局 LogManager 并调用 setup()。Gateway lifespan 调用一次。"""
    global _log_manager
    _log_manager = LogManager(
        data_dir=data_dir,
        initial_llm_stream=llm_stream,
        initial_sse=sse,
    )
    _log_manager.setup()
    return _log_manager


def get_log_manager() -> LogManager:
    """获取全局 LogManager 单例（需在 setup_logging() 之后调用）。"""
    if _log_manager is None:
        raise RuntimeError("setup_logging() has not been called")
    return _log_manager


__all__ = ["LogManager", "LogState", "LogConfigPatch", "setup_logging", "get_log_manager"]
