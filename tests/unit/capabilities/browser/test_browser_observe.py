from __future__ import annotations

import pytest

from sebastian.capabilities.tools.browser.observe import observe_page


class _ContentPage:
    url = "https://example.com/login?token=secret-token"

    async def title(self) -> str:
        return "Login"

    async def content(self) -> str:
        return """
        <html>
          <body>
            <h1>Welcome back</h1>
            <a href="/account?session=hidden">Account</a>
            <button>Sign in</button>
            <input type="text" name="email" value="alice@example.com" aria-label="Email">
            <input type="password" name="password" value="super-secret" aria-label="Password">
            <input type="hidden" name="csrf" value="hidden-token">
            <textarea>this is a very long draft that should not be copied verbatim</textarea>
          </body>
        </html>
        """


@pytest.mark.asyncio
async def test_observe_page_sanitizes_sensitive_form_values_and_url_query() -> None:
    observation = await observe_page(_ContentPage(), max_chars=4000)

    assert observation["url"] == "https://example.com/login"
    assert observation["title"] == "Login"
    assert "Welcome back" in observation["text"]
    assert "Sign in" in observation["interactive_summary"]
    assert "Account" in observation["interactive_summary"]
    assert "Email" in observation["interactive_summary"]
    assert "alice@example.com" not in observation["text"]
    assert "super-secret" not in str(observation)
    assert "hidden-token" not in str(observation)
    assert "very long draft" not in str(observation)


@pytest.mark.asyncio
async def test_observe_page_applies_max_chars_to_text() -> None:
    observation = await observe_page(_ContentPage(), max_chars=12)

    assert len(observation["text"]) <= 13
    assert observation["truncated"] is True
