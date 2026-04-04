# sebastian/log/manager.py
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from sebastian.log.schema import LogState

_FORMATTER = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 3


def _make_rotating_handler(log_path: Path) -> logging.handlers.RotatingFileHandler:
    handler = logging.handlers.RotatingFileHandler(
        filename=str(log_path),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(_FORMATTER)
    return handler


class LogManager:
    """管理三个 RotatingFileHandler 的生命周期，支持热切换 llm_stream / sse。"""

    def __init__(
        self,
        data_dir: Path,
        initial_llm_stream: bool = False,
        initial_sse: bool = False,
    ) -> None:
        self._data_dir = data_dir
        self._initial_llm_stream = initial_llm_stream
        self._initial_sse = initial_sse
        self._llm_stream_handler: logging.handlers.RotatingFileHandler | None = None
        self._sse_handler: logging.handlers.RotatingFileHandler | None = None
        self._llm_stream_enabled = False
        self._sse_enabled = False

    def setup(self) -> None:
        """初始化日志目录和 handlers；在 Gateway lifespan 启动时调用一次。"""
        logs_dir = self._data_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # main.log — 覆盖 sebastian root logger，INFO+，始终开启
        main_handler = _make_rotating_handler(logs_dir / "main.log")
        main_handler.setLevel(logging.INFO)
        root = logging.getLogger("sebastian")
        root.setLevel(logging.DEBUG)  # 让子 logger 的 DEBUG 不被 root 截断
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
            root.addHandler(main_handler)

        # 预创建 llm_stream handler（不挂载）
        self._llm_stream_handler = _make_rotating_handler(logs_dir / "llm_stream.log")
        self._llm_stream_handler.setLevel(logging.DEBUG)
        llm_logger = logging.getLogger("sebastian.llm.stream")
        llm_logger.setLevel(logging.DEBUG)
        llm_logger.propagate = False  # 不上冒至 main.log

        # 预创建 sse handler（不挂载）
        self._sse_handler = _make_rotating_handler(logs_dir / "sse.log")
        self._sse_handler.setLevel(logging.DEBUG)
        sse_logger = logging.getLogger("sebastian.gateway.sse")
        sse_logger.setLevel(logging.DEBUG)
        sse_logger.propagate = False  # 不上冒至 main.log

        # 应用初始开关状态
        if self._initial_llm_stream:
            self.set_llm_stream(True)
        if self._initial_sse:
            self.set_sse(True)

    def set_llm_stream(self, enabled: bool) -> None:
        """运行时热切换 llm_stream.log。"""
        if self._llm_stream_handler is None:
            raise RuntimeError("LogManager.setup() must be called before toggling")
        logger = logging.getLogger("sebastian.llm.stream")
        if enabled:
            if self._llm_stream_handler not in logger.handlers:
                logger.addHandler(self._llm_stream_handler)
        else:
            logger.removeHandler(self._llm_stream_handler)
        self._llm_stream_enabled = enabled

    def set_sse(self, enabled: bool) -> None:
        """运行时热切换 sse.log。"""
        if self._sse_handler is None:
            raise RuntimeError("LogManager.setup() must be called before toggling")
        logger = logging.getLogger("sebastian.gateway.sse")
        if enabled:
            if self._sse_handler not in logger.handlers:
                logger.addHandler(self._sse_handler)
        else:
            logger.removeHandler(self._sse_handler)
        self._sse_enabled = enabled

    def get_state(self) -> LogState:
        return LogState(
            llm_stream_enabled=self._llm_stream_enabled,
            sse_enabled=self._sse_enabled,
        )
