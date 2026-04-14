from __future__ import annotations

from sebastian.core.types import SessionStatus
from sebastian.protocol.events.types import EventType


def test_session_status_waiting_exists():
    assert SessionStatus.WAITING == "waiting"


def test_session_status_waiting_distinct_from_stalled():
    assert SessionStatus.WAITING != SessionStatus.STALLED


def test_event_type_session_waiting_exists():
    assert EventType.SESSION_WAITING == "session.waiting"
