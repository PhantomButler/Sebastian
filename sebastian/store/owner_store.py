from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sebastian.store.models import UserRecord


class OwnerStore:
    """Thin helper around UserRecord scoped to the single-owner account."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def owner_exists(self) -> bool:
        async with self._session_factory() as session:
            stmt = select(UserRecord).where(UserRecord.role == "owner").limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def get_owner(self) -> UserRecord | None:
        async with self._session_factory() as session:
            stmt = select(UserRecord).where(UserRecord.role == "owner").limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_owner(self, *, name: str, password_hash: str) -> UserRecord:
        if await self.owner_exists():
            raise ValueError("owner already exists")

        async with self._session_factory() as session:
            record = UserRecord(
                id=str(uuid4()),
                name=name,
                password_hash=password_hash,
                role="owner",
                created_at=datetime.now(UTC),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record
