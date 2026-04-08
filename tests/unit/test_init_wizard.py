from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sebastian.cli.init_wizard import run_headless_wizard


@pytest.mark.asyncio
async def test_run_headless_wizard_creates_owner_and_secret(tmp_path: Path) -> None:
    owner_store = MagicMock()
    owner_store.owner_exists = AsyncMock(return_value=False)
    owner_store.create_owner = AsyncMock()

    secret_key_path = tmp_path / "secret.key"

    await run_headless_wizard(
        owner_store=owner_store,
        secret_key_path=secret_key_path,
        answers={"name": "Eric", "password": "hunter42"},
    )

    owner_store.create_owner.assert_awaited_once()
    kwargs = owner_store.create_owner.call_args.kwargs
    assert kwargs["name"] == "Eric"
    assert kwargs["password_hash"].startswith("$pbkdf2-sha256$")
    assert secret_key_path.exists()


@pytest.mark.asyncio
async def test_run_headless_wizard_refuses_if_owner_exists(tmp_path: Path) -> None:
    owner_store = MagicMock()
    owner_store.owner_exists = AsyncMock(return_value=True)
    owner_store.create_owner = AsyncMock()

    secret_key_path = tmp_path / "secret.key"

    with pytest.raises(RuntimeError, match="already initialized"):
        await run_headless_wizard(
            owner_store=owner_store,
            secret_key_path=secret_key_path,
            answers={"name": "Eric", "password": "hunter42"},
        )

    owner_store.create_owner.assert_not_awaited()
