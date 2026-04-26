from __future__ import annotations

import pytest


@pytest.fixture
def _secret_key_file(tmp_path, monkeypatch):
    """Write a temporary secret.key and point settings.data_dir to it."""
    user_data_dir = tmp_path / "data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    key_file = user_data_dir / "secret.key"
    key_file.write_text("test-secret-abc")
    monkeypatch.setattr(
        "sebastian.config.settings.sebastian_data_dir",
        str(tmp_path),
    )


@pytest.mark.usefixtures("_secret_key_file")
def test_encrypt_decrypt_roundtrip() -> None:
    from sebastian.llm.crypto import decrypt, encrypt

    plain = "sk-ant-api03-test-key"
    assert decrypt(encrypt(plain)) == plain


@pytest.mark.usefixtures("_secret_key_file")
def test_different_plaintexts_produce_different_ciphertext() -> None:
    from sebastian.llm.crypto import encrypt

    assert encrypt("key-a") != encrypt("key-b")


@pytest.mark.usefixtures("_secret_key_file")
def test_ciphertext_is_not_plaintext() -> None:
    from sebastian.llm.crypto import encrypt

    plain = "sk-ant-secret"
    assert plain not in encrypt(plain)
