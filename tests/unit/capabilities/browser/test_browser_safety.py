from __future__ import annotations

import pytest

from sebastian.capabilities.tools.browser.safety import (
    BrowserSafetyError,
    is_forbidden_ip,
    validate_public_http_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "chrome://settings",
        "about:blank",
        "data:text/html,hi",
        "javascript:alert(1)",
        "ftp://example.com/file",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.10",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://[fe80::1]/",
    ],
)
def test_url_guard_blocks_high_risk_targets(url: str) -> None:
    with pytest.raises(BrowserSafetyError):
        validate_public_http_url(url)


def test_url_guard_allows_public_https_url() -> None:
    parsed = validate_public_http_url("https://example.com/path?q=1")

    assert parsed.scheme == "https"
    assert parsed.hostname == "example.com"
    assert parsed.port is None
    assert parsed.url == "https://example.com/path?q=1"


def test_url_guard_normalizes_idna_host() -> None:
    parsed = validate_public_http_url("https://Bücher.example/path")

    assert parsed.hostname == "xn--bcher-kva.example"
    assert parsed.url == "https://xn--bcher-kva.example/path"


@pytest.mark.parametrize(
    "url",
    [
        "https://user@example.com/",
        "https://user:password@example.com/",
        "https:///missing-host",
        "http://",
        "https://exa mple.com/",
    ],
)
def test_url_guard_rejects_malformed_authority(url: str) -> None:
    with pytest.raises(BrowserSafetyError):
        validate_public_http_url(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.1",
        "192.168.1.10",
        "172.16.0.1",
        "169.254.169.254",
        "169.254.10.10",
        "224.0.0.1",
        "0.0.0.0",
        "fe80::1",
        "fc00::1",
        "2001:db8::1",
    ],
)
def test_is_forbidden_ip_blocks_non_public_ranges(ip: str) -> None:
    assert is_forbidden_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_is_forbidden_ip_allows_public_addresses(ip: str) -> None:
    assert is_forbidden_ip(ip) is False
