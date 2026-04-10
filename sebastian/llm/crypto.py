from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _read_secret() -> str:
    """Read the encryption secret from the secret.key file."""
    from sebastian.config import settings

    path = settings.resolved_secret_key_path()
    if not path.exists():
        raise RuntimeError(
            f"Secret key file not found: {path}. Run `sebastian serve` to initialize."
        )
    return path.read_text(encoding="utf-8").strip()


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(_read_secret().encode()).digest())
    return Fernet(key)


def encrypt(plain: str) -> str:
    """Encrypt a plaintext string. Returns URL-safe base64 ciphertext."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(enc: str) -> str:
    """Decrypt a Fernet-encrypted string back to plaintext."""
    return _fernet().decrypt(enc.encode()).decode()
