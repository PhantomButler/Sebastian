from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from sebastian.llm.catalog.loader import LLMCatalog, LLMModelSpec, load_builtin_catalog
from sebastian.llm.crypto import decrypt, encrypt
from sebastian.llm.provider import LLMProvider
from sebastian.store.models import (
    AgentLLMBindingRecord,
    LLMAccountRecord,
    LLMCustomModelRecord,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


DEFAULT_BINDING_AGENT_TYPE = "__default__"


def _coerce_thinking(
    effort: str | None,
    capability: str | None,
) -> str | None:
    """按 provider capability 钳制 effort 到合法值。"""
    if capability in ("none", "always_on"):
        return None
    if capability == "toggle":
        if effort in (None, "off"):
            return "off"
        # 任何非空非 off 的值（包括 on/low/medium/high/max）→ on
        return "on"
    if capability == "effort":
        if effort in ("max", "on"):
            return "high"
        return effort
    if capability == "adaptive":
        return effort
    # capability 未知/None → pass-through
    return effort


@dataclass(slots=True)
class ResolvedProvider:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    thinking_effort: str | None
    capability: str | None
    thinking_format: str | None
    account_id: str
    model_display_name: str


def _get_catalog() -> LLMCatalog:
    """Module-level lazy singleton for the builtin catalog."""
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = load_builtin_catalog()
    return _catalog_cache


_catalog_cache: LLMCatalog | None = None


class LLMProviderRegistry:
    """DB-backed registry for LLM providers.

    Resolution: agent_type → binding → account + model_spec → provider instance.
    Falls back to DEFAULT_BINDING_AGENT_TYPE ("__default__") when no agent-specific
    binding exists.
    """

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db_factory = db_factory

    # ------------------------------------------------------------------
    # Core resolution
    # ------------------------------------------------------------------

    async def get_provider(self, agent_type: str | None = None) -> ResolvedProvider:
        """Return ResolvedProvider for the given agent_type.

        Resolution order:
        1. Query AgentLLMBindingRecord for *agent_type*.
        2. If not found, query for DEFAULT_BINDING_AGENT_TYPE.
        3. If neither exists, raise RuntimeError.
        4. Read the LLMAccountRecord for the binding's account_id.
        5. Resolve model spec via get_model_spec().
        6. Compute effective base_url.
        7. Instantiate provider.
        8. Coerce thinking_effort by model spec's thinking_capability.
        9. Return ResolvedProvider with all fields populated.
        """
        binding: AgentLLMBindingRecord | None = None
        if agent_type is not None:
            binding = await self.get_binding(agent_type)

        if binding is None and agent_type != DEFAULT_BINDING_AGENT_TYPE:
            binding = await self.get_binding(DEFAULT_BINDING_AGENT_TYPE)

        if binding is None:
            raise RuntimeError("No default LLM configured. Add one via the Settings page.")

        account = await self.get_account(binding.account_id)
        if account is None:
            raise RuntimeError(f"Account {binding.account_id!r} referenced by binding not found.")

        model_spec = await self.get_model_spec(account, binding.model_id)
        effective_base_url = await self._resolve_effective_base_url(account)

        provider_instance = self._instantiate_account(account, model_spec, effective_base_url)

        effort = _coerce_thinking(binding.thinking_effort, model_spec.thinking_capability)

        return ResolvedProvider(
            provider=provider_instance,
            model=binding.model_id,
            context_window_tokens=model_spec.context_window_tokens,
            thinking_effort=effort,
            capability=model_spec.thinking_capability,
            thinking_format=model_spec.thinking_format,
            account_id=account.id,
            model_display_name=model_spec.display_name,
        )

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    async def get_default(self) -> LLMProvider:
        """Return the default LLMProvider instance (no model info)."""
        resolved = await self.get_provider(DEFAULT_BINDING_AGENT_TYPE)
        return resolved.provider

    async def get_default_with_model(self) -> tuple[LLMProvider, str]:
        """Return (default_provider, model_name) tuple."""
        resolved = await self.get_provider(DEFAULT_BINDING_AGENT_TYPE)
        return resolved.provider, resolved.model

    # ------------------------------------------------------------------
    # Account CRUD
    # ------------------------------------------------------------------

    async def get_account(self, account_id: str) -> LLMAccountRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMAccountRecord).where(LLMAccountRecord.id == account_id)
            )
            return result.scalar_one_or_none()

    async def list_accounts(self) -> list[LLMAccountRecord]:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMAccountRecord).order_by(LLMAccountRecord.created_at)
            )
            return list(result.scalars().all())

    async def create_account(self, record: LLMAccountRecord) -> None:
        async with self._db_factory() as session:
            session.add(record)
            await session.commit()

    async def update_account(self, account_id: str, **kwargs: Any) -> LLMAccountRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMAccountRecord).where(LLMAccountRecord.id == account_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            for key, value in kwargs.items():
                if key == "api_key":
                    setattr(record, "api_key_enc", encrypt(value))
                else:
                    setattr(record, key, value)
            await session.commit()
            await session.refresh(record)
            return record

    async def delete_account(self, account_id: str) -> bool:
        """Delete account. Returns True if deleted, False if not found."""
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMAccountRecord).where(LLMAccountRecord.id == account_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True

    # ------------------------------------------------------------------
    # Binding CRUD
    # ------------------------------------------------------------------

    async def list_bindings(self) -> list[AgentLLMBindingRecord]:
        async with self._db_factory() as session:
            result = await session.execute(select(AgentLLMBindingRecord))
            return list(result.scalars().all())

    async def set_binding(
        self,
        agent_type: str,
        account_id: str,
        model_id: str,
        thinking_effort: str | None = None,
    ) -> AgentLLMBindingRecord:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(AgentLLMBindingRecord.agent_type == agent_type)
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                record = AgentLLMBindingRecord(
                    agent_type=agent_type,
                    account_id=account_id,
                    model_id=model_id,
                    thinking_effort=thinking_effort,
                )
                session.add(record)
            else:
                existing.account_id = account_id
                existing.model_id = model_id
                existing.thinking_effort = thinking_effort
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

    async def get_binding(self, agent_type: str) -> AgentLLMBindingRecord | None:
        async with self._db_factory() as session:
            result = await session.execute(
                select(AgentLLMBindingRecord).where(AgentLLMBindingRecord.agent_type == agent_type)
            )
            return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Model spec resolution
    # ------------------------------------------------------------------

    async def get_model_spec(self, account: LLMAccountRecord, model_id: str) -> LLMModelSpec:
        """Resolve model metadata.

        For built-in accounts (catalog_provider_id != "custom"): load from catalog.
        For custom accounts (catalog_provider_id == "custom"): load from llm_custom_models table.
        """
        if account.catalog_provider_id == "custom":
            return await self._get_custom_model_spec(account.id, model_id)

        catalog = _get_catalog()
        return catalog.get_model(account.catalog_provider_id, model_id)

    async def _get_custom_model_spec(self, account_id: str, model_id: str) -> LLMModelSpec:
        async with self._db_factory() as session:
            result = await session.execute(
                select(LLMCustomModelRecord).where(
                    LLMCustomModelRecord.account_id == account_id,
                    LLMCustomModelRecord.model_id == model_id,
                )
            )
            record = result.scalar_one_or_none()
        if record is None:
            raise RuntimeError(f"Custom model {model_id!r} not found for account {account_id!r}")
        return LLMModelSpec(
            id=record.model_id,
            display_name=record.display_name,
            context_window_tokens=record.context_window_tokens,
            thinking_capability=record.thinking_capability,
            thinking_format=record.thinking_format,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _instantiate_account(
        self,
        account: LLMAccountRecord,
        model_spec: LLMModelSpec,
        effective_base_url: str | None,
    ) -> LLMProvider:
        """Instantiate the correct LLMProvider subclass from account + model spec."""
        plain_key = decrypt(account.api_key_enc)

        if account.provider_type == "anthropic":
            from sebastian.llm.anthropic import AnthropicProvider

            return AnthropicProvider(
                api_key=plain_key,
                base_url=effective_base_url,
                thinking_capability=model_spec.thinking_capability,
            )

        if account.provider_type == "openai":
            from sebastian.llm.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider(
                api_key=plain_key,
                base_url=effective_base_url,
                thinking_format=model_spec.thinking_format,
                thinking_capability=model_spec.thinking_capability,
            )

        raise ValueError(f"Unknown provider_type: {account.provider_type!r}")

    async def _resolve_effective_base_url(self, account: LLMAccountRecord) -> str | None:
        """Return the effective base URL for an account.

        - If account has base_url_override, use it.
        - Otherwise, look up the catalog provider's base_url.
        - Custom accounts without override raise RuntimeError.
        """
        if account.base_url_override:
            return account.base_url_override

        if account.catalog_provider_id == "custom":
            raise RuntimeError(f"Custom account {account.id!r} must have a base_url_override")

        catalog = _get_catalog()
        provider_spec = catalog.get_provider(account.catalog_provider_id)
        return provider_spec.base_url
