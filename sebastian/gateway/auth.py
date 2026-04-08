# mypy: disable-error-code=import-untyped

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from sebastian.config import settings

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return cast(str, _pwd_context.hash(password))


def verify_password(plain: str, hashed: str) -> bool:
    return cast(bool, _pwd_context.verify(plain, hashed))


class JwtSigner:
    """Encapsulates JWT encode/decode with secret loaded from file or env fallback."""

    def __init__(
        self,
        *,
        secret_key_path: Path,
        algorithm: str,
        expire_minutes: int,
        fallback_secret: str = "",
    ) -> None:
        self._algorithm = algorithm
        self._expire_minutes = expire_minutes

        if secret_key_path.exists():
            self._secret = secret_key_path.read_text(encoding="utf-8").strip()
        elif fallback_secret:
            self._secret = fallback_secret
        else:
            raise RuntimeError(
                f"No JWT secret available (file {secret_key_path} missing and no fallback provided)"
            )

    def encode(self, payload: dict[str, Any]) -> str:
        data = payload.copy()
        data["exp"] = datetime.now(UTC) + timedelta(minutes=self._expire_minutes)
        return cast(str, jwt.encode(data, self._secret, algorithm=self._algorithm))

    def decode(self, token: str) -> dict[str, Any]:
        try:
            return cast(
                dict[str, Any],
                jwt.decode(token, self._secret, algorithms=[self._algorithm]),
            )
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


_signer: JwtSigner | None = None


def get_signer() -> JwtSigner:
    """Lazy-loaded global JwtSigner, refreshed by reset_signer()."""
    global _signer
    if _signer is None:
        _signer = JwtSigner(
            secret_key_path=settings.resolved_secret_key_path(),
            algorithm=settings.sebastian_jwt_algorithm,
            expire_minutes=settings.sebastian_jwt_expire_minutes,
            fallback_secret=settings.sebastian_jwt_secret,
        )
    return _signer


def reset_signer() -> None:
    """Drop cached signer so next get_signer() rereads the secret file.

    Used right after the setup wizard generates a new secret.key so that
    subsequent token operations pick it up without a process restart.

    Note: there is a one-request TOCTOU window — if a request arrives between
    a concurrent secret.key rewrite and this call, it may still use the old
    signer for that single request. Acceptable for single-process deployment;
    revisit if we ever run multi-worker.
    """
    global _signer
    _signer = None


def create_access_token(data: dict[str, Any]) -> str:
    return get_signer().encode(data)


def decode_token(token: str) -> dict[str, Any]:
    return get_signer().decode(token)


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict[str, Any]:
    """FastAPI dependency: validates Bearer token and returns the payload."""
    return decode_token(credentials.credentials)
