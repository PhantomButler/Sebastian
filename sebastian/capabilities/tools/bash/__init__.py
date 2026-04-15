from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sebastian.config import settings
from sebastian.core.tool import tool
from sebastian.core.tool_context import get_tool_context
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 10_000
_DEFAULT_TIMEOUT = 600
_HEARTBEAT_INTERVAL_S: float = 3.0

# 执行后通常无 stdout 的命令——无输出时返回 "Done" 而非 "no output"
_SILENT_COMMANDS: frozenset[str] = frozenset({
    "mv", "cp", "rm", "mkdir", "rmdir", "chmod", "chown",
    "chgrp", "touch", "ln", "cd", "export", "unset", "wait",
})

# 退出码具有特殊语义的命令：exit code → 人类可读说明
# 仅匹配命令行第一个 token（不处理 pipeline 中间的子命令）
_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "grep":  {1: "No matches found (not an error)"},
    "find":  {1: "No matches found (not an error)"},
    "diff":  {1: "Files differ (not an error)"},
    "test":  {1: "Condition false (not an error)"},
    "[":     {1: "Condition false (not an error)"},
}


def _is_silent_command(command: str) -> bool:
    """返回 True 当命令第一个 token 在 _SILENT_COMMANDS 白名单中。"""
    base = command.strip().split()[0] if command.strip() else ""
    return base in _SILENT_COMMANDS


def _interpret_exit_code(command: str, returncode: int) -> str | None:
    """返回退出码的语义解释。仅匹配命令行第一个 token，无解释时返回 None。"""
    base = command.strip().split()[0] if command.strip() else ""
    return _EXIT_CODE_SEMANTICS.get(base, {}).get(returncode)


async def _heartbeat(
    progress_cb: Callable[[dict[str, Any]], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    """每隔 _HEARTBEAT_INTERVAL_S 秒调用一次 progress_cb，直到 stop_event 被设置。"""
    start = time.monotonic()
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_HEARTBEAT_INTERVAL_S)
            return  # stop_event 已 set，命令结束
        except TimeoutError:
            elapsed = int(time.monotonic() - start)
            try:
                await progress_cb({"elapsed_seconds": elapsed})
            except Exception:
                logger.warning("bash heartbeat publish failed", exc_info=True)


@tool(
    name="Bash",
    description=(
        "Execute a shell command. Returns stdout, stderr, and return code. "
        "Non-zero return codes are not automatically errors. "
        "Default timeout is 600 seconds."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
)
async def bash(
    command: str,
    timeout: int | None = None,
    description: str | None = None,
) -> ToolResult:
    logger.debug("bash[%s]: %s", description or command[:60], command)

    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    workspace = settings.workspace_dir
    workspace.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(workspace),
    )

    # 进度心跳：仅当 ToolCallContext 有 progress_cb 时启动
    ctx = get_tool_context()
    stop_event = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    if ctx is not None and ctx.progress_cb is not None:
        heartbeat_task = asyncio.create_task(
            _heartbeat(ctx.progress_cb, stop_event)
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(effective_timeout),
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(ok=False, error=f"Command timed out after {effective_timeout}s")
    finally:
        stop_event.set()
        if heartbeat_task is not None:
            await heartbeat_task

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")
    assert proc.returncode is not None  # communicate() always sets returncode
    truncated = False

    if len(stdout) > _MAX_OUTPUT_CHARS:
        stdout = stdout[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True
    if len(stderr) > _MAX_OUTPUT_CHARS:
        stderr = stderr[:_MAX_OUTPUT_CHARS] + "\n...[truncated]"
        truncated = True

    # 语义化退出码：写入 output dict，LLM 可直接读取
    interpretation = _interpret_exit_code(command, proc.returncode)

    # output dict：LLM 通过 json.dumps 看到的内容
    output: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": proc.returncode,
        "truncated": truncated,
    }
    if interpretation:
        output["returncode_interpretation"] = interpretation

    # empty_hint：无任何输出时给 LLM 的语义化提示（优先于 output dict）
    empty_hint: str | None = None
    if not stdout and not stderr:
        if interpretation:
            empty_hint = f"exit {proc.returncode}: {interpretation}"
        elif _is_silent_command(command):
            empty_hint = "Done"
        else:
            empty_hint = f"Command exited with code {proc.returncode}, no output"

    # display：用户/日志可见的字符串，含 stderr 和语义解释后缀
    if proc.returncode != 0 and stderr:
        display: str | None = (
            f"{stdout}\n--- stderr ---\n{stderr}" if stdout else f"--- stderr ---\n{stderr}"
        )
    else:
        display = stdout or None

    if interpretation and (stdout or stderr):
        suffix = f"(exit {proc.returncode}: {interpretation})"
        display = f"{display}\n{suffix}" if display else suffix

    return ToolResult(
        ok=True,
        output=output,
        display=display,
        empty_hint=empty_hint,
    )
