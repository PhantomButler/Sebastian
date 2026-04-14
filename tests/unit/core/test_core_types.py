from __future__ import annotations


def test_task_defaults() -> None:
    from sebastian.core.types import Task, TaskStatus

    task = Task(goal="Buy groceries", session_id="session-123")
    assert task.status == TaskStatus.CREATED
    assert task.assigned_agent == "sebastian"
    assert task.id  # auto-generated UUID
    assert task.plan is None
    assert task.session_id == "session-123"


def test_task_status_values() -> None:
    from sebastian.core.types import TaskStatus

    assert TaskStatus.CREATED.value == "created"
    assert TaskStatus.COMPLETED.value == "completed"


def test_tool_result_ok() -> None:
    from sebastian.core.types import ToolResult

    r = ToolResult(ok=True, output={"stdout": "hello"})
    assert r.ok
    assert r.error is None


def test_tool_result_error() -> None:
    from sebastian.core.types import ToolResult

    r = ToolResult(ok=False, error="command not found")
    assert not r.ok
    assert r.error == "command not found"


def test_checkpoint_defaults() -> None:
    from sebastian.core.types import Checkpoint

    cp = Checkpoint(task_id="abc", step=1, data={"key": "val"})
    assert cp.id
    assert cp.step == 1


def test_session_defaults() -> None:
    from sebastian.core.types import Session, SessionStatus

    session = Session(
        agent_type="sebastian",
        title="Test",
    )
    assert session.status == SessionStatus.ACTIVE
    assert session.agent_type == "sebastian"
    assert "/" not in session.id


def test_task_has_session_id() -> None:
    from sebastian.core.types import Task

    task = Task(goal="do something", session_id="abc")
    assert task.session_id == "abc"


def test_session_has_agent_type() -> None:
    from sebastian.core.types import Session

    session = Session(agent_type="stock", title="test")

    assert session.agent_type == "stock"
    assert not hasattr(session, "agent_id")
    assert not hasattr(session, "agent")
