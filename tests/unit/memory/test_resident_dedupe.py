from __future__ import annotations

from sebastian.memory.resident_dedupe import (
    canonical_bullet,
    canonical_json,
    normalize_memory_text,
    slot_value_dedupe_key,
)


def test_canonical_bullet_strips_resident_labels() -> None:
    assert canonical_bullet("Profile memory: 用户偏好使用中文交流。") == "用户偏好使用中文交流。"
    assert canonical_bullet("Pinned memory: 用户偏好使用中文交流。") == "用户偏好使用中文交流。"


def test_canonical_bullet_normalizes_markdown_and_whitespace() -> None:
    raw = "  - ## Profile memory:  Hello   WORLD  \n"
    assert canonical_bullet(raw) == "hello world"


def test_normalize_memory_text_removes_code_fences_and_control_chars() -> None:
    raw = "```python\nprint('x')\n```\n用户 偏好中文"
    assert normalize_memory_text(raw) == "用户偏好中文"


def test_canonical_json_is_stable() -> None:
    left = {"b": 2, "a": ["中", 1]}
    right = {"a": ["中", 1], "b": 2}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_json(left) == '{"a":["中",1],"b":2}'


def test_slot_value_dedupe_key_uses_subject_slot_and_value() -> None:
    key = slot_value_dedupe_key(
        subject_id="owner",
        slot_id="user.preference.language",
        structured_payload={"value": "中文", "dimension": "reply_language"},
    )
    assert key is not None
    assert key.startswith("slot_value:sha256:")


def test_slot_value_dedupe_key_returns_none_without_value() -> None:
    assert (
        slot_value_dedupe_key(
            subject_id="owner",
            slot_id="user.preference.language",
            structured_payload={"dimension": "reply_language"},
        )
        is None
    )
