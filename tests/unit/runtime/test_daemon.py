from __future__ import annotations

import os
from pathlib import Path

from sebastian.cli.daemon import is_running, read_pid, remove_pid, write_pid


def test_write_and_read_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "sebastian.pid"
    write_pid(pid_file, 12345)
    assert read_pid(pid_file) == 12345


def test_read_pid_missing(tmp_path: Path) -> None:
    pid_file = tmp_path / "sebastian.pid"
    assert read_pid(pid_file) is None


def test_remove_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "sebastian.pid"
    write_pid(pid_file, 12345)
    remove_pid(pid_file)
    assert not pid_file.exists()


def test_is_running_current_process() -> None:
    assert is_running(os.getpid()) is True


def test_is_running_nonexistent() -> None:
    # PID 99999 大概率不存在
    assert is_running(99999) is False
