from __future__ import annotations

from sebastian.memory.feedback import MemorySaveResult, render_memory_save_summary


def _make(**kwargs) -> MemorySaveResult:
    defaults = dict(
        saved_count=0,
        discarded_count=0,
        proposed_slots_registered=[],
        proposed_slots_rejected=[],
    )
    defaults.update(kwargs)
    return MemorySaveResult(**defaults, summary="")  # summary will be regen


def test_summary_single_saved() -> None:
    r = _make(saved_count=1)
    assert "已记住 1 条" in render_memory_save_summary(r)


def test_summary_multi_plus_new_slot() -> None:
    r = _make(saved_count=2, proposed_slots_registered=["user.profile.like_book"])
    out = render_memory_save_summary(r)
    assert "已记住 2 条" in out
    assert "user.profile.like_book" in out


def test_summary_partial_discard() -> None:
    r = _make(saved_count=1, discarded_count=1)
    out = render_memory_save_summary(r)
    assert "已记住 1 条" in out
    assert "跳过" in out or "重复" in out


def test_summary_all_discarded() -> None:
    r = _make(saved_count=0, discarded_count=2)
    assert "没找到明确的记忆点" in render_memory_save_summary(r)


def test_summary_slot_all_rejected() -> None:
    r = _make(saved_count=0, proposed_slots_rejected=[{"slot_id": "bad", "reason": "命名违规"}])
    assert "提议的新分类不合规" in render_memory_save_summary(r)


def test_summary_empty_extraction() -> None:
    r = _make()
    assert "暂无可保存的记忆价值" in render_memory_save_summary(r)
