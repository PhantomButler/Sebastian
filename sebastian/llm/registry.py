from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from sebastian.llm.provider import LLMProvider
from sebastian.store.models import AgentLLMBindingRecord, LLMProviderRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


_EFFORT_ALIASES = {"off", "on", "low", "medium", "high", "max"}


def _coerce_thinking(
    effort: str | None,
    adaptive: bool,
    capability: str | None,
) -> tuple[str | None, bool]:
    """按 provider capability 钳制 effort/adaptive 到合法组合。"""
    if capability in ("none", "always_on"):
        return (None, False)
    if capability == "toggle":
        if effort in (None, "off"):
            return ("off", False)
        if effort == "on":
            return ("on", False)
        # low/medium/high/max → 统一视为 on
        return ("on", False)
    if capability == "effort":
        if effort == "max":
            return ("high", False)
        if effort == "on":
            return ("high", False)
        return (effort, False)
    if capability == "adaptive":
        return (effort, adaptive)
    # capability 未知/None → pass-through
    return (effort, adaptive)


@dataclass
class ResolvedProvider:
    provider: LLMProvider
    model: str
    thinking_effort: str | None
    thinking_adaptive: bool
    capability: str | None


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
            raise RuntimeError("No default LLM provider configured. Add one via the Settings page.")

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

    async def get_provider(self, agent_type: str | None = None) -> ResolvedProvider:
        """Return ResolvedProvider for the given agent_type.

        Resolution order:
        1. If agent_type has a binding row with a non-null provider_id → use that record.
        2. Otherwise fallback to global default provider.
        """
        record: LLMProviderRecord | None = None
        binding: AgentLLMBindingRecord | None = None
        if agent_type is not None:
            binding = await self._get_binding(agent_type)
            if binding is not None and binding.provider_id is not None:
                record = await self._get_record(binding.provider_id)

        if record is None:
            # fallback: 全局默认
            async with self._db_factory() as session:
                result = await session.execute(
                    select(LLMProviderRecord).where(LLMProviderRecord.is_default.is_(True)).limit(1)
                )
                record = result.scalar_one_or_none()

        if record is None:
            raise RuntimeError("No default LLM provider configured. Add one via the Settings page.")

        effort_raw = binding.thinking_effort if binding else None
        adaptive_raw = binding.thinking_adaptive if binding else False
        effort, adaptive = _coerce_thinking(effort_raw, adaptive_raw, record.thinking_capability)

        return ResolvedProvider(
            provider=self._instantiate(record),
            model=record.model,
            thinking_effort=effort,
            thinking_adaptive=adaptive,
            capability=record.thinking_capability,
        )

    async def list_all(self) -> list[LLMProviderRecord]:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).order_by(LLMProviderRecord.created_at)
            )
            return list(result.scalars().all())

    async def create(self, record: LLMProviderRecord) -> None:
        async with self._db_factory() as session:
            if record.is_default:
                await self._clear_default_provider(session)
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
            if kwargs.get("is_default") is True:
                await self._clear_default_provider(session, exclude_id=record_id)
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

    async def list_bindings(self) -> list[AgentLLMBindingRecord]:
        async with self._db_factory() as session:
            result = await session.execute(select(AgentLLMBindingRecord))
            return list(result.scalars().all())

    async def set_binding(
        self,
        agent_type: str,
        provider_id: str | None,
        thinking_effort: str | None = None,
        thinking_adaptive: bool = False,
    ) -> AgentLLMBindingRecord:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(AgentLLMBindingRecord.agent_type == agent_type)
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                record = AgentLLMBindingRecord(
                    agent_type=agent_type,
                    provider_id=provider_id,
                    thinking_effort=thinking_effort,
                    thinking_adaptive=thinking_adaptive,
                )
                session.add(record)
            else:
                existing.provider_id = provider_id
                existing.thinking_effort = thinking_effort
                existing.thinking_adaptive = thinking_adaptive
                record = existing
            await session.commit()
            await session.refresh(record)
            return record

    async def clear_binding(self, agent_type: str) -> None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(AgentLLMBindingRecord.agent_type == agent_type)
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                await session.delete(existing)
                await session.commit()

    async def _get_binding(self, agent_type: str) -> AgentLLMBindingRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(AgentLLMBindingRecord.agent_type == agent_type)
            )
            return result.scalar_one_or_none()

    async def _get_record(self, provider_id: str) -> LLMProviderRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMProviderRecord).where(LLMProviderRecord.id == provider_id)
            )
            return result.scalar_one_or_none()

    async def _clear_default_provider(
        self,
        session: AsyncSession,
        *,
        exclude_id: str | None = None,
    ) -> None:
        stmt = update(LLMProviderRecord).where(LLMProviderRecord.is_default.is_(True))
        if exclude_id is not None:
            stmt = stmt.where(LLMProviderRecord.id != exclude_id)
        await session.execute(stmt.values(is_default=False))

    def _instantiate(self, record: LLMProviderRecord) -> LLMProvider:
        from sebastian.llm.crypto import decrypt

        plain_key = decrypt(record.api_key_enc)
        if record.provider_type == "anthropic":
            from sebastian.llm.anthropic import AnthropicProvider

            return AnthropicProvider(
                api_key=plain_key,
                base_url=record.base_url,
                thinking_capability=record.thinking_capability,
            )
        if record.provider_type == "openai":
            from sebastian.llm.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider(
                api_key=plain_key,
                base_url=record.base_url,
                thinking_format=record.thinking_format,
                thinking_capability=record.thinking_capability,
            )
        raise ValueError(f"Unknown provider_type: {record.provider_type!r}")
