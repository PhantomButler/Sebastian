from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from sebastian.llm.provider import LLMProvider
from sebastian.store.models import LLMProviderRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class LLMProviderRegistry:
    """DB-backed registry for LLM providers. Falls back to env-configured Anthropic
    when no default provider is stored."""

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db_factory = db_factory

    async def get_default(self) -> LLMProvider:
        provider, _ = await self.get_default_with_model()
        return provider

    async def get_default_with_model(self) -> tuple[LLMProvider, str]:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.is_default.is_(True)).limit(1)
            )
            record = result.scalar_one_or_none()

        if record is None:
            from sebastian.config import settings
            from sebastian.llm.anthropic import AnthropicProvider

            return AnthropicProvider(api_key=settings.anthropic_api_key), settings.sebastian_model

        return self._instantiate(record), record.model

    async def get_by_id(self, provider_id: str) -> LLMProvider | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == provider_id)
            )
            record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._instantiate(record)

    async def get_provider(self, agent_type: str | None = None) -> tuple[LLMProvider, str]:
        """Return (provider, model) for the given agent_type.

        Checks agents/{agent_type}/manifest.toml [llm] section first.
        Falls back to get_default_with_model() if no manifest config or no matching DB record.
        """
        if agent_type is not None:
            manifest_llm = _read_manifest_llm(agent_type)
            if manifest_llm:
                provider_type = manifest_llm.get("provider_type")
                model = manifest_llm.get("model")
                if provider_type and model:
                    record = await self._get_by_type(provider_type)
                    if record is not None:
                        return self._instantiate(record), model
        return await self.get_default_with_model()

    async def _get_by_type(self, provider_type: str) -> LLMProviderRecord | None:
        """Return first DB record matching provider_type."""
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord)
                .where(LLMProviderRecord.provider_type == provider_type)
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def list_all(self) -> list[LLMProviderRecord]:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).order_by(LLMProviderRecord.created_at)
            )
            return list(result.scalars().all())

    async def create(self, record: LLMProviderRecord) -> None:
        async with self._db_factory() as session:
            session.add(record)
            await session.commit()

    async def update(self, record_id: str, **kwargs: Any) -> LLMProviderRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == record_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            for key, value in kwargs.items():
                setattr(record, key, value)
            await session.commit()
            await session.refresh(record)
            return record

    async def delete(self, record_id: str) -> bool:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == record_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True

    def _instantiate(self, record: LLMProviderRecord) -> LLMProvider:
        from sebastian.llm.crypto import decrypt

        plain_key = decrypt(record.api_key_enc)
        if record.provider_type == "anthropic":
            from sebastian.llm.anthropic import AnthropicProvider

            return AnthropicProvider(api_key=plain_key, base_url=record.base_url)
        if record.provider_type == "openai":
            from sebastian.llm.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider(
                api_key=plain_key,
                base_url=record.base_url,
                thinking_format=record.thinking_format,
            )
        raise ValueError(f"Unknown provider_type: {record.provider_type!r}")


def _read_manifest_llm(agent_type: str) -> dict | None:
    """Read [llm] section from the agent's manifest.toml, or return None if absent."""
    import logging

    # Builtin agents live alongside this package: sebastian/agents/{agent_type}/manifest.toml
    agents_dir = Path(__file__).parent.parent / "agents"
    manifest_path = agents_dir / agent_type / "manifest.toml"
    if not manifest_path.exists():
        return None
    try:
        with manifest_path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        logging.getLogger(__name__).warning("Invalid TOML in manifest for agent %r", agent_type)
        return None
    return data.get("llm")  # None if no [llm] section
