from __future__ import annotations

import hmac
import secrets

_ALLOWED_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


class SetupSecurity:
    """Localhost-only + single-use token guard for the setup wizard."""

    def __init__(self, token: str) -> None:
        self._token = token

    def is_allowed(self, host: str, token: str) -> bool:
        if host not in _ALLOWED_HOSTS:
            return False
        if not token:
            return False
        return hmac.compare_digest(self._token, token)

    @classmethod
    def generate_token(cls) -> str:
        return secrets.token_urlsafe(32)
