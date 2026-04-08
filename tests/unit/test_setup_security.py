from __future__ import annotations

from sebastian.gateway.setup.security import SetupSecurity


def test_allows_localhost_with_valid_token() -> None:
    token = SetupSecurity.generate_token()
    security = SetupSecurity(token=token)
    assert security.is_allowed("127.0.0.1", token) is True


def test_rejects_non_localhost() -> None:
    token = SetupSecurity.generate_token()
    security = SetupSecurity(token=token)
    assert security.is_allowed("192.168.1.1", token) is False


def test_rejects_missing_token() -> None:
    token = SetupSecurity.generate_token()
    security = SetupSecurity(token=token)
    assert security.is_allowed("127.0.0.1", "") is False


def test_rejects_wrong_token() -> None:
    token = SetupSecurity.generate_token()
    security = SetupSecurity(token=token)
    assert security.is_allowed("127.0.0.1", "wrong-token") is False


def test_allows_ipv6_localhost() -> None:
    token = SetupSecurity.generate_token()
    security = SetupSecurity(token=token)
    assert security.is_allowed("::1", token) is True


def test_generate_token_urlsafe_length() -> None:
    token = SetupSecurity.generate_token()
    assert len(token) >= 32
