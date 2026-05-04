from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sebastian.capabilities.tools.browser.artifacts import upload_browser_artifact
from sebastian.capabilities.tools.browser.downloads import list_downloads, send_download
from sebastian.capabilities.tools.browser.observe import observe_page
from sebastian.capabilities.tools.browser.safety import BrowserSafetyError
from sebastian.core.tool import tool
from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier, ToolReviewPreflight

_BROWSER_UNAVAILABLE = (
    "Browser service is unavailable. Do not retry automatically; "
    "tell the user browser tools are not available in this runtime."
)
_NO_BROWSER_PAGE = (
    "No browser-tool-owned page is currently open. Do not retry automatically; "
    "call browser_open with a public http(s) URL first."
)
_ALLOWED_ACTIONS = {
    "click",
    "type",
    "press",
    "select",
    "wait_for_text",
    "wait_for_selector",
    "back",
    "forward",
    "reload",
}
_CREDENTIAL_PATTERN = re.compile(
    r"(password|passwd|passcode|secret|token|api[_-]?key|credential|auth|login|signin|sign in)",
    re.IGNORECASE,
)
_PAYMENT_PATTERN = re.compile(
    r"\b(pay|payment|purchase|buy|checkout|card|credit|cc-number|cvv|billing|iban)\b",
    re.IGNORECASE,
)
_ACCOUNT_SETTINGS_PATTERN = re.compile(
    r"\b(account|settings|profile|email|phone|address|delete|remove|destroy|transfer)\b",
    re.IGNORECASE,
)


@tool(
    name="browser_open",
    description="Open a public http(s) URL in Sebastian's managed browser session.",
    permission_tier=PermissionTier.MODEL_DECIDES,
    display_name="Browser Open",
)
async def browser_open(url: str) -> ToolResult:
    manager = _browser_manager()
    if manager is None:
        return ToolResult(ok=False, error=_BROWSER_UNAVAILABLE)
    try:
        result = await manager.open(url)
    except Exception:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=(
                "Browser open failed unexpectedly. Do not retry automatically; "
                "tell the user the browser runtime failed."
            ),
        )
    if not getattr(result, "ok", False):
        error = _safe_message(str(getattr(result, "error", "") or "Browser open failed"))
        guidance = _browser_open_guidance(error)
        return ToolResult(
            ok=False,
            error=f"{error}. Do not retry automatically; {guidance}",
        )
    final_url = _sanitize_url(str(getattr(result, "url", "") or url))
    title = getattr(result, "title", None)
    return ToolResult(
        ok=True,
        output={"url": final_url, "title": title, "status": "opened"},
        display=f"Opened {final_url}",
    )


@tool(
    name="browser_observe",
    description=(
        "Observe the current page opened by browser_open with sanitized text "
        "and interactable elements."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
    display_name="Browser Observe",
    review_preflight=lambda inputs, context: _browser_observe_preflight(inputs, context),
)
async def browser_observe(max_chars: int = 4000) -> ToolResult:
    manager = _browser_manager()
    if manager is None:
        return ToolResult(ok=False, error=_BROWSER_UNAVAILABLE)
    try:
        observation = await manager.observe_current_page(observe_page, max_chars=max_chars)
    except RuntimeError:
        return ToolResult(ok=False, error=_NO_BROWSER_PAGE)
    except Exception:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=(
                "Browser observation failed. Do not retry automatically; "
                "tell the user the current page could not be inspected."
            ),
        )
    display = observation.get("text") or observation.get("title") or "Observed browser page"
    return ToolResult(ok=True, output=observation, display=str(display))


@tool(
    name="browser_act",
    description=(
        "Perform a small validated browser action on the current browser_open page. "
        "Supported actions: click, type, press, select."
    ),
    permission_tier=PermissionTier.MODEL_DECIDES,
    display_name="Browser Act",
)
async def browser_act(
    action: str,
    target: str | None = None,
    value: str | None = None,
) -> ToolResult:
    normalized = action.strip().lower()
    if normalized not in _ALLOWED_ACTIONS:
        return ToolResult(
            ok=False,
            error=(
                f"Unknown browser action: {action}. Do not retry automatically; "
                "use one of click, type, press, select, wait_for_text, "
                "wait_for_selector, back, forward, or reload."
            ),
        )
    if _looks_credential_sensitive(target, value):
        return ToolResult(
            ok=False,
            error=(
                "Browser action blocked because it looks credential-sensitive. "
                "Do not retry automatically; ask the user to type passwords or secrets directly."
            ),
        )

    manager = _browser_manager()
    if manager is None:
        return ToolResult(ok=False, error=_BROWSER_UNAVAILABLE)
    try:
        output = await manager.act(
            action=normalized,
            target=target,
            value=value,
            is_blocked=lambda metadata: _target_metadata_sensitive(normalized, metadata),
        )
    except BrowserSafetyError:
        return ToolResult(
            ok=False,
            error=(
                "Browser action blocked because the target looks sensitive or high-impact. "
                "Do not retry automatically; ask the user to handle this action directly."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=(
                f"{_safe_message(str(exc) or 'Browser action failed')}. "
                "Do not retry automatically; inspect the page before trying a different action."
            ),
        )
    return ToolResult(ok=True, output=output, display=f"Browser action completed: {normalized}")


@tool(
    name="browser_capture",
    description="Capture the current browser_open page as an image and send it to the user.",
    permission_tier=PermissionTier.MODEL_DECIDES,
    display_name="Browser Capture",
)
async def browser_capture(display_name: str | None = None) -> ToolResult:
    manager = _browser_manager()
    if manager is None:
        return ToolResult(ok=False, error=_BROWSER_UNAVAILABLE)
    try:
        capture = await _maybe_await(manager.capture_screenshot(full_page=True))
        path = Path(capture.path)
    except Exception:  # noqa: BLE001
        return ToolResult(
            ok=False,
            error=(
                "Browser screenshot failed. Do not retry automatically; "
                "tell the user the current page could not be captured."
            ),
        )
    result = await upload_browser_artifact(
        path=path,
        filename=_artifact_display_name(display_name, path.name),
        mime_type="image/png",
        kind="image",
        delete_after=True,
    )
    if result.ok and isinstance(result.output, dict):
        result.output["filename"] = _artifact_display_name(display_name, path.name)
        result.output["url"] = _sanitize_url(str(getattr(capture, "url", "") or ""))
    return result


@tool(
    name="browser_downloads",
    description="List browser downloads or send a listed download to the user.",
    permission_tier=PermissionTier.MODEL_DECIDES,
    display_name="Browser Downloads",
)
async def browser_downloads(action: str = "list", filename: str | None = None) -> ToolResult:
    manager = _browser_manager()
    if manager is None:
        return ToolResult(ok=False, error=_BROWSER_UNAVAILABLE)
    normalized = action.strip().lower()
    if normalized == "list":
        try:
            downloads = await list_downloads(manager)
        except Exception:  # noqa: BLE001
            return ToolResult(
                ok=False,
                error=(
                    "Browser downloads could not be listed. Do not retry automatically; "
                    "tell the user download listing is unavailable."
                ),
            )
        return ToolResult(
            ok=True,
            output={"downloads": downloads},
            display=f"{len(downloads)} browser downloads",
        )
    if normalized == "send":
        return await send_download(manager, filename)
    return ToolResult(
        ok=False,
        error=(
            f"Unknown browser_downloads action: {action}. Do not retry automatically; "
            "use action='list' or action='send'."
        ),
    )


async def _browser_observe_preflight(
    inputs: dict[str, Any],
    _context: Any,
) -> ToolReviewPreflight:
    manager = _browser_manager()
    if manager is None:
        return ToolReviewPreflight(ok=False, error=_BROWSER_UNAVAILABLE)
    metadata = await manager.current_page_metadata()
    if metadata is None or not bool(getattr(metadata, "opened_by_browser_tool", False)):
        return ToolReviewPreflight(ok=False, error=_NO_BROWSER_PAGE)
    return ToolReviewPreflight(
        ok=True,
        review_input={
            "max_chars": int(inputs.get("max_chars") or 4000),
            "current_url": _sanitize_url(str(getattr(metadata, "url", "") or "")),
            "title": getattr(metadata, "title", None),
            "opened_by_browser_tool": bool(getattr(metadata, "opened_by_browser_tool", False)),
        },
    )


def _target_metadata_sensitive(action: str, metadata: dict[str, str] | None) -> bool:
    if not metadata:
        return False
    haystack = " ".join(str(value) for value in metadata.values() if value)
    if _CREDENTIAL_PATTERN.search(haystack):
        return True
    if _PAYMENT_PATTERN.search(haystack) or _ACCOUNT_SETTINGS_PATTERN.search(haystack):
        return True
    input_type = metadata.get("type", "").lower()
    if action in {"type", "press", "select"} and input_type in {"password", "hidden"}:
        return True
    if action == "click" and metadata.get("isSubmitControl", "").lower() == "true":
        return True
    if action == "click" and metadata.get("formHasFields", "").lower() == "true":
        return True
    if action == "click" and re.search(
        r"\b(delete|remove|destroy|pay|purchase|buy|checkout|send|submit|transfer|confirm)\b",
        haystack,
        re.IGNORECASE,
    ):
        return True
    return False


def _artifact_display_name(display_name: str | None, fallback: str) -> str:
    if not display_name:
        return fallback
    cleaned = Path(display_name.replace("\\", "/")).name.strip()
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


def _browser_manager() -> Any | None:
    state = sys.modules.get("sebastian.gateway.state")
    if state is None:
        import sebastian.gateway.state as _state  # noqa: PLC0415

        state = _state
    return getattr(state, "browser_manager", None)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _looks_credential_sensitive(selector: str | None, value: str | None) -> bool:
    haystack = " ".join(part for part in (selector or "", value or "") if part)
    return bool(_CREDENTIAL_PATTERN.search(haystack))


def _browser_open_guidance(error: str) -> str:
    lowered = error.lower()
    if "playwright install" in lowered or "browser executable is missing" in lowered:
        return "ask the user to run the browser setup command above."
    if "system dependencies" in lowered or "install-deps" in lowered:
        return "ask the user to run the browser dependency command above."
    if "blocked" in lowered:
        return "ask the user for a different public http(s) URL."
    return "tell the user the browser runtime failed and include the setup guidance above."


def _safe_message(message: str) -> str:
    cleaned = message.replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"file://\S+", "[path]", cleaned)
    cleaned = re.sub(r"(/[^\s:]+)+", "[path]", cleaned)
    return cleaned[:500] or "Browser tool failed"


def _sanitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
