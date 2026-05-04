from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_INTERACTIVE_TAGS = {"a", "button", "select", "textarea"}
_SKIP_TAGS = {"script", "style", "noscript"}
_MAX_FORM_VALUE_CHARS = 24


@dataclass
class _Element:
    tag: str
    attrs: dict[str, str]
    text: list[str] = field(default_factory=list)


class _ObservationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.interactive: list[str] = []
        self._skip_depth = 0
        self._stack: list[_Element] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "input":
            self._handle_input(attrs_dict)
            return
        if tag in _INTERACTIVE_TAGS:
            self._stack.append(_Element(tag=tag, attrs=attrs_dict))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if self._stack and self._stack[-1].tag == tag:
            element = self._stack.pop()
            label = _clean_text(" ".join(element.text)) or _element_label(element.attrs)
            if label:
                self.interactive.append(f"{tag}: {label}")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _clean_text(data)
        if not text:
            return
        if self._stack and self._stack[-1].tag == "textarea":
            return
        if self._stack:
            self._stack[-1].text.append(text)
        self.text_parts.append(text)

    def _handle_input(self, attrs: dict[str, str]) -> None:
        input_type = attrs.get("type", "text").lower()
        if input_type in {"hidden", "password"}:
            return
        label = _element_label(attrs)
        if not label:
            return
        value = attrs.get("value", "")
        if value and len(value) <= _MAX_FORM_VALUE_CHARS:
            self.interactive.append(f"input {input_type}: {label}")
        else:
            self.interactive.append(f"input {input_type}: {label}")


async def observe_page(page: Any, max_chars: int = 4000) -> dict[str, Any]:
    """Return a compact, sanitized observation of the current browser page."""

    max_chars = max(0, min(max_chars, 12000))
    title = await _safe_title(page)
    url = _sanitize_url(str(getattr(page, "url", "") or ""))
    html = await _safe_content(page)
    parser = _ObservationParser()
    parser.feed(html)

    text = _clean_text(" ".join(parser.text_parts))
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "…"

    interactive = _dedupe(parser.interactive)
    return {
        "url": url,
        "title": title,
        "text": text,
        "interactive_summary": "\n".join(interactive[:80]),
        "truncated": truncated,
    }


async def _safe_title(page: Any) -> str | None:
    try:
        title = await page.title()
        return str(title) if title is not None else None
    except Exception:  # noqa: BLE001
        return None


async def _safe_content(page: Any) -> str:
    content = getattr(page, "content", None)
    if callable(content):
        try:
            return str(await content())
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _element_label(attrs: dict[str, str]) -> str:
    for key in ("aria-label", "placeholder", "name", "id", "title"):
        value = _clean_text(attrs.get(key, ""))
        if value:
            return value
    return ""


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _sanitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
