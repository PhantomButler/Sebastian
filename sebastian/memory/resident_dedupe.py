from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_LIST_MARKER = re.compile(r"^\s*[-*+]\s+")
_RESIDENT_LABEL = re.compile(r"^(profile memory|pinned memory|memory)\s*:\s*", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
# Remove spaces between adjacent CJK characters (artifacts of copy-paste or line joining).
_CJK_SPACE = re.compile(r"(?<=[一-鿿㐀-䶿]) (?=[一-鿿㐀-䶿　-〿＀-￯])")


def normalize_memory_text(value: str, *, max_chars: int = 300) -> str:
    """Strip fenced code blocks, control chars, headings, list markers; collapse whitespace."""
    text = _FENCED_BLOCK.sub("", value)
    text = _CONTROL_CHARS.sub("", text)
    # Strip list markers first so that "  - ## Heading" is correctly de-headed.
    text = "\n".join(_LIST_MARKER.sub("", line) for line in text.splitlines())
    text = _HEADING.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    text = _CJK_SPACE.sub("", text)
    return text[:max_chars].strip()


def canonical_bullet(value: str) -> str:
    """Normalize to canonical form for exact-bullet deduplication."""
    text = normalize_memory_text(value)
    text = _RESIDENT_LABEL.sub("", text).strip()
    return text.lower()


def canonical_json(value: Any) -> str:
    """Stable JSON with sorted keys, no extra whitespace, UTF-8."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def slot_value_dedupe_key(
    *,
    subject_id: str | None,
    slot_id: str | None,
    structured_payload: dict[str, Any] | None,
) -> str | None:
    """Generate slot_value dedupe key. Returns None if structured_payload has no 'value'."""
    if not subject_id or not slot_id or not structured_payload:
        return None
    if "value" not in structured_payload:
        return None
    raw = canonical_json([subject_id, slot_id, structured_payload["value"]])
    return f"slot_value:{sha256_text(raw)}"
