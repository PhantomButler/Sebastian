from __future__ import annotations

from sebastian.memory.retrieval.retrieval_lexicon import (
    CONTEXT_LANE_WORDS,
    EPISODE_LANE_WORDS,
    PROFILE_LANE_WORDS,
    RELATION_LANE_STATIC_WORDS,
    SMALL_TALK_WORDS,
)


def test_all_lexicons_are_frozensets() -> None:
    for lex in (
        PROFILE_LANE_WORDS,
        CONTEXT_LANE_WORDS,
        EPISODE_LANE_WORDS,
        RELATION_LANE_STATIC_WORDS,
        SMALL_TALK_WORDS,
    ):
        assert isinstance(lex, frozenset)
        assert len(lex) >= 30, f"lexicon too small: {len(lex)}"  # spec §7.4 要求每条 lane ≥ 30 词


def test_profile_lexicon_covers_preference_verbs() -> None:
    assert "喜欢" in PROFILE_LANE_WORDS
    assert "偏好" in PROFILE_LANE_WORDS
    assert "prefer" in PROFILE_LANE_WORDS


def test_context_lexicon_covers_time_adverbs() -> None:
    assert "现在" in CONTEXT_LANE_WORDS
    assert "最近" in CONTEXT_LANE_WORDS
    assert "now" in CONTEXT_LANE_WORDS


def test_episode_lexicon_covers_recall_verbs() -> None:
    assert "上次" in EPISODE_LANE_WORDS
    assert "记得" in EPISODE_LANE_WORDS
    assert "remember" in EPISODE_LANE_WORDS


def test_relation_static_covers_family_terms() -> None:
    for term in ("老婆", "妻子", "太太", "爱人"):
        assert term in RELATION_LANE_STATIC_WORDS
    assert "同事" in RELATION_LANE_STATIC_WORDS


def test_small_talk_covers_greetings() -> None:
    assert "hi" in SMALL_TALK_WORDS
    assert "你好" in SMALL_TALK_WORDS
    assert "thanks" in SMALL_TALK_WORDS


def test_no_cross_lane_overlap() -> None:
    """验证五条 lane 词库之间无重叠词，防止维护时误将词放错 lane。"""
    lanes = [
        PROFILE_LANE_WORDS,
        CONTEXT_LANE_WORDS,
        EPISODE_LANE_WORDS,
        RELATION_LANE_STATIC_WORDS,
        SMALL_TALK_WORDS,
    ]
    for i in range(len(lanes)):
        for j in range(i + 1, len(lanes)):
            overlap = lanes[i] & lanes[j]
            assert not overlap, f"Lane {i} 和 Lane {j} 存在重叠词: {overlap}"
