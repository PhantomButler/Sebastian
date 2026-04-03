from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sebastian.store.session_store import SessionStore


@dataclass
class TurnEntry:
    role: str
    content: str
    ts: str


class EpisodicMemory:
    """Conversation history backed by the file-based SessionStore."""

    def __init__(self, session_store: SessionStore) -> None:
        self._store = session_store

    async def _get_agent_context(self, session_id: str, agent: str) -> tuple[str, str]:
        session = await self._store.get_session_for_agent_type(session_id, agent)
        if session is None:
            raise FileNotFoundError(
                f"Session {session_id!r} not found for agent_type {agent!r}"
            )
        return session.agent_type, session.agent_id

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: str = "sebastian",
    ) -> TurnEntry:
        agent_type, agent_id = await self._get_agent_context(session_id, agent)
        await self._store.append_message(
            session_id,
            role,
            content,
            agent_type=agent_type,
            agent_id=agent_id,
        )
        return TurnEntry(
            role=role,
            content=content,
            ts=datetime.now(UTC).isoformat(),
        )

    async def get_turns(
        self,
        session_id: str,
        agent: str = "sebastian",
        limit: int = 50,
    ) -> list[TurnEntry]:
        agent_type, agent_id = await self._get_agent_context(session_id, agent)
        messages = await self._store.get_messages(
            session_id,
            agent_type=agent_type,
            agent_id=agent_id,
            limit=limit,
        )
        return [
            TurnEntry(role=message["role"], content=message["content"], ts=message.get("ts", ""))
            for message in messages
        ]
