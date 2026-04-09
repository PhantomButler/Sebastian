from __future__ import annotations

import os
import signal
from pathlib import Path


def pid_path(data_dir: Path) -> Path:
    """Return the standard PID file path."""
    return data_dir / "sebastian.pid"


def write_pid(path: Path, pid: int | None = None) -> None:
    """Write current (or given) PID to file."""
    path.write_text(str(pid or os.getpid()))


def read_pid(path: Path) -> int | None:
    """Read PID from file. Returns None if missing or corrupt."""
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_pid(path: Path) -> None:
    """Remove PID file if it exists."""
    path.unlink(missing_ok=True)


def is_running(pid: int) -> bool:
    """Check whether a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_process(path: Path) -> bool:
    """Send SIGTERM to the process recorded in PID file. Returns True if killed."""
    pid = read_pid(path)
    if pid is None or not is_running(pid):
        remove_pid(path)
        return False
    os.kill(pid, signal.SIGTERM)
    remove_pid(path)
    return True
