# tests/unit/test_log_manager.py
from __future__ import annotations

import logging
from pathlib import Path


def test_setup_creates_logs_dir(tmp_path: Path) -> None:
    """setup_logging 应在 data_dir/logs 下创建目录。"""
    from sebastian.log.manager import LogManager

    mgr = LogManager(data_dir=tmp_path)
    mgr.setup()
    assert (tmp_path / "logs").is_dir()


def test_main_log_file_created(tmp_path: Path) -> None:
    """setup 后写一条日志，main.log 应存在。"""
    from sebastian.log.manager import LogManager

    mgr = LogManager(data_dir=tmp_path)
    mgr.setup()
    logging.getLogger("sebastian.test_main").info("hello")
    assert (tmp_path / "logs" / "main.log").exists()


def test_llm_stream_toggle(tmp_path: Path) -> None:
    """开启 llm_stream 后写 DEBUG 日志，llm_stream.log 应收到内容；关闭后不再写入。"""
    from sebastian.log.manager import LogManager

    mgr = LogManager(data_dir=tmp_path)
    mgr.setup()
    log_path = tmp_path / "logs" / "llm_stream.log"

    # 默认关闭，写日志不落盘
    logging.getLogger("sebastian.llm.stream").debug("should not appear")
    assert not log_path.exists() or log_path.read_text() == ""

    # 开启后写日志应落盘
    mgr.set_llm_stream(True)
    logging.getLogger("sebastian.llm.stream").debug("delta token")
    assert log_path.exists()
    assert "delta token" in log_path.read_text()

    # 关闭后新内容不再追加
    mgr.set_llm_stream(False)
    size_before = log_path.stat().st_size
    logging.getLogger("sebastian.llm.stream").debug("after disable")
    assert log_path.stat().st_size == size_before


def test_sse_toggle(tmp_path: Path) -> None:
    """开启 sse 后写日志，sse.log 应收到内容。"""
    from sebastian.log.manager import LogManager

    mgr = LogManager(data_dir=tmp_path)
    mgr.setup()
    log_path = tmp_path / "logs" / "sse.log"

    mgr.set_sse(True)
    logging.getLogger("sebastian.gateway.sse").debug("sse payload")
    assert log_path.exists()
    assert "sse payload" in log_path.read_text()


def test_get_state_reflects_toggles(tmp_path: Path) -> None:
    """get_state 应返回当前开关状态。"""
    from sebastian.log.manager import LogManager

    mgr = LogManager(data_dir=tmp_path)
    mgr.setup()

    state = mgr.get_state()
    assert state.llm_stream_enabled is False
    assert state.sse_enabled is False

    mgr.set_llm_stream(True)
    assert mgr.get_state().llm_stream_enabled is True

    mgr.set_sse(True)
    assert mgr.get_state().sse_enabled is True
